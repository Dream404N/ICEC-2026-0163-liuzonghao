"""单轮入口：一次唤醒 = 查表 = 最多一条提醒 = 一条改不动的日志。

    python prebell/run.py --period P1                 # 云端 cron 调用
    python prebell/run.py                            # 不传 period 时自动挑当前该响的大节
    python prebell/run.py --dry-run --period P1       # 本机预览，不联网不写真数据
    python prebell/run.py --preview 2026-11-16       # 手工预览：推一条指定日期的全天课表（不写日志）

诚实原则：
  - 表里没有这一天这一节（本周没课）就静默跳过，不打扰；
  - 迟到 ≤15 分钟照发并在消息里写明晚到多久，超过就记 skipped_late 不发；
  - 上课后才醒就记 skipped_after_class，绝不补推、绝不回填历史；
  - 推送失败记 HTTP 状态 + 脱敏错误，不重试打爆免费额度，也不写「成功」；
  - SendKey 只从环境变量读，缺失就记 failed。
"""
import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prebell import channels, ledger, model, notifier, state as state_store

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parents[1]  # 02-20Days-Challenge/


def load_json(name, override=None):
    p = Path(override) if override else HERE / name
    return json.loads(p.read_text(encoding="utf-8"))


def find_entry(schedule, key):
    for e in schedule["entries"]:
        if e["key"] == key:
            return e
    return None


def pick_period(now, schedule, day):
    """不传 --period 时，找离当前时刻最近的那个提醒点（±15 分钟内）。"""
    best, best_gap = None, None
    for p in load_json("timetable.json")["periods"]:
        fire = model.utc_datetime(day, p["remind_at"])
        gap = abs((now - fire).total_seconds())
        if gap <= 15 * 60 and (best_gap is None or gap < best_gap):
            if find_entry(schedule, model.make_key(day, p["id"])):
                best, best_gap = p["id"], gap
    return best


def run_once(*, root, day, period, source="cron", now_utc=None,
             config=None, schedule=None, sender=None, messages=None):
    config = config or load_json("config.example.json")
    schedule = schedule or load_json("schedule.json")
    messages = messages or notifier.load_messages()
    now = now_utc or datetime.now(model.UTC)
    key = model.make_key(day, period)
    entry = find_entry(schedule, key)

    base = {
        "seq": len(ledger.read_records(root, day)) + 1,
        "key": key,
        "date": day,
        "period": period,
        "source": source,
        "ts": now.astimezone(model.CST).strftime("%Y-%m-%d %H:%M") + "（脱敏·分钟级）",
        "fired_utc": model.iso_utc(now),
    }

    if entry is None:
        rec = dict(base, action="no_schedule", scheduled_utc=None, latency_ms=0,
                   late=False, channel=None, http_status=0, duration_ms=0,
                   result="skipped", error=None)
        ledger.append_record(root, day, rec)
        return rec

    scheduled = model.utc_datetime(day, entry["remind_at"])
    class_start = model.utc_datetime(day, entry["class_start"])
    latency = int((now - scheduled).total_seconds() * 1000)
    tolerance = int(config["late_tolerance_min"]) * 60_000
    late_by_min = max(0, round(latency / 60_000))

    st = state_store.load(root)
    sent_today = sum(
        1 for row in st["pushed"]
        if row.get("key", "").startswith(day + "-") and row.get("status") == "sent"
    )

    action, terminal, raw = "send", "sent", None
    if state_store.find(st, key) is not None:
        action = terminal = "duplicate"
    elif config.get("hard_stop_at_class_start", True) and now >= class_start:
        action = terminal = "skipped_after_class"
    elif latency > tolerance:
        action = terminal = "skipped_late"
    elif latency < -60_000:
        action = terminal = "skipped_early"
    elif sent_today >= int(config.get("max_push_per_day", 4)):
        action = terminal = "throttled"
    else:
        today_entries = [e for e in schedule["entries"] if e["date"] == day]
        title, content = notifier.render(entry, today_entries, messages, late_by_min)
        sender = sender or channels.build_sender(config)
        raw = sender(title, content)
        terminal = "sent" if raw["status"] == "ok" else "failed"

    result = "ok" if terminal == "sent" else ("error" if terminal == "failed" else "skipped")
    rec = dict(
        base,
        action=action,
        scheduled_utc=model.iso_utc(scheduled),
        latency_ms=latency,
        late=latency > tolerance,
        week=entry["week"],
        courses=[c["name"] for c in entry["courses"]],
        channel=raw["channel"] if raw else None,
        http_status=raw["http_status"] if raw else 0,
        duration_ms=raw["duration_ms"] if raw else 0,
        result=result,
        error=model.scrub_text(raw["error"]) if (raw and raw["error"]) else None,
    )
    ledger.append_record(root, day, rec)

    if terminal != "duplicate":
        state_store.record(st, key, terminal, rec["channel"], model.iso_utc(now))
        state_store.save(st, root)
    return rec


def preview(day, config=None, schedule=None, messages=None, sender=None):
    """手工预览：推一条指定日期的全天课表，让用户立刻看到成品长什么样。

    这不是自动运行，因此**不写 process_logs**——手工消息不冒充 7 天无人值守证据。
    """
    config = config or load_json("config.example.json")
    schedule = schedule or load_json("schedule.json")
    messages = messages or notifier.load_messages()
    entries = sorted([e for e in schedule["entries"] if e["date"] == day],
                     key=lambda e: e["class_start"])
    d = datetime.strptime(day, "%Y-%m-%d").date()
    wd = model.WEEKDAY_CN[d.weekday()]
    week = entries[0]["week"] if entries else 0
    lines = ["**%s %s · 第 %d 周全天课表**" % (d.strftime("%m月%d日"), wd, week), ""]
    if not entries:
        lines.append("这一天没课。")
    for e in entries:
        for c in e["courses"]:
            lines.append("- **%s %s** · %s · %s" % (
                e["class_start"], c["name"], c.get("room") or "教室待核对",
                c.get("form") or ""))
    lines += ["", "> 这条是手工预览，用来确认推送内容；**不计入自动运行日志**。"
              "课前 20 分钟的自动提醒从 11-16 起由 GitHub Actions 发出。"]
    title = "预备铃｜%s 全天课表" % d.strftime("%m/%d")
    sender = sender or channels.build_sender(config)
    res = sender(title, "\n".join(lines))
    return {"title": title, "result": res, "courses": sum(len(e["courses"]) for e in entries)}


def main(argv=None):
    ap = argparse.ArgumentParser(description="PreBell 单轮入口")
    ap.add_argument("--period", choices=model.PERIODS, default=None)
    ap.add_argument("--source", default="cron", choices=["cron", "manual", "test"])
    ap.add_argument("--date", default=None, help="YYYY-MM-DD，默认取北京当天")
    ap.add_argument("--now", default=None, help="测试用 UTC 时刻 YYYY-MM-DDTHH:MM:SSZ")
    ap.add_argument("--root", default=None)
    ap.add_argument("--config", default=None)
    ap.add_argument("--schedule", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--preview", default=None, metavar="DATE",
                    help="手工推送指定日期的全天课表（不写日志）")
    args = ap.parse_args(argv)

    if args.preview:
        out = preview(args.preview,
                      config=load_json("config.example.json", args.config),
                      schedule=load_json("schedule.json", args.schedule))
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    now = (datetime.strptime(args.now, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=model.UTC)
           if args.now else datetime.now(model.UTC))
    day = args.date or now.astimezone(model.CST).date().isoformat()
    schedule = load_json("schedule.json", args.schedule)
    period = args.period or pick_period(now, schedule, day)
    if not period:
        print(json.dumps({"date": day, "action": "no_period_now",
                          "note": "当前时刻不在任何提醒点 ±15 分钟内，也未传 --period"},
                         ensure_ascii=False))
        return 0

    if args.dry_run:
        import tempfile
        root = Path(args.root) if args.root else Path(tempfile.mkdtemp(prefix="prebell-dry-"))
        sender = lambda title, content: {
            "status": "ok", "http_status": 200, "duration_ms": 1,
            "error": None, "channel": "dry-run",
        }
    else:
        root = Path(args.root) if args.root else PROJECT_ROOT
        sender = None

    rec = run_once(root=root, day=day, period=period, source=args.source,
                   now_utc=now, sender=sender,
                   config=load_json("config.example.json", args.config),
                   schedule=schedule)
    print(json.dumps(rec, ensure_ascii=False))
    # 业务失败已如实入日志，退出码保持 0，避免中断 Actions 的每日提交证据链。
    return 0


if __name__ == "__main__":
    sys.exit(main())
