"""workflow_dispatch 入口：一次唤醒 = 一条提醒 = 一条日志。

时序：拼三元组唯一键 → 查计划 → 查去重 → 迟到/硬截止判定 → 推送 → 写日志 → 写状态。
任何跳过或失败都如实落 JSONL 明细，不补推、不回填、不编造时间戳。
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


def run_once(*, root, day, period, stage, source="cron", now_utc=None,
             config=None, schedule=None, sender=None, messages=None):
    config = config or load_json("config.example.json")
    schedule = schedule or load_json("schedule.json")
    messages = messages or notifier.load_messages()
    now = now_utc or datetime.now(model.UTC)
    key = model.make_key(day, period, stage)
    entry = find_entry(schedule, key)

    base = {
        "seq": len(ledger.read_records(root, day)) + 1,
        "key": key,
        "date": day,
        "period": period,
        "stage": stage,
        "source": source,
        "ts": now.astimezone(model.CST).strftime("%Y-%m-%d %H:%M") + "（脱敏·分钟级）",
        "fired_utc": model.iso_utc(now),
    }

    if entry is None:
        rec = dict(base, action="no_schedule", scheduled_utc=None, latency_ms=0,
                   late=False, channel=None, http_status=0, duration_ms=0,
                   result="skipped", error="no matching schedule entry")
        ledger.append_record(root, day, rec)
        return rec

    scheduled = model.utc_datetime(day, entry["fire_at"])
    class_start = model.utc_datetime(day, entry["class_start"])
    latency = int((now - scheduled).total_seconds() * 1000)
    tolerance = config["stages"][stage]["late_tolerance_min"] * 60_000

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
    elif sent_today >= config.get("max_push_per_day", 6):
        action = terminal = "throttled"
    else:
        title, content = notifier.render(stage, entry, messages,
                                         course=entry.get("course"))
        sender = sender or channels.build_sender(config)
        raw = sender(title, content)
        terminal = "sent" if raw["status"] == "ok" else "failed"

    if terminal == "sent":
        result = "ok"
    elif terminal == "failed":
        result = "error"
    else:
        result = "skipped"

    rec = dict(
        base,
        action=action,
        scheduled_utc=model.iso_utc(scheduled),
        latency_ms=latency,
        late=latency > tolerance,
        channel=raw["channel"] if raw else None,
        http_status=raw["http_status"] if raw else 0,
        duration_ms=raw["duration_ms"] if raw else 0,
        result=result,
        error=model.scrub_text(raw["error"]) if (raw and raw["error"]) else None,
    )
    ledger.append_record(root, day, rec)

    if terminal not in ("duplicate",):
        state_store.record(st, key, terminal, rec["channel"], model.iso_utc(now))
        state_store.save(st, root)
    return rec


def main(argv=None):
    ap = argparse.ArgumentParser(description="执行一条课表提醒")
    ap.add_argument("--period", required=True, choices=model.PERIODS)
    ap.add_argument("--stage", required=True, choices=model.STAGES)
    ap.add_argument("--source", default="cron", choices=["cron", "manual", "test"])
    ap.add_argument("--date", default=None, help="YYYY-MM-DD，默认取 UTC 当天")
    ap.add_argument("--now", default=None, help="测试用 UTC 时刻 YYYY-MM-DDTHH:MM:SSZ")
    ap.add_argument("--root", default=None, help="覆盖数据根目录（测试用）")
    ap.add_argument("--config", default=None)
    ap.add_argument("--schedule", default=None)
    ap.add_argument("--dry-run", action="store_true", help="临时目录 + 假通道，不写真数据")
    args = ap.parse_args(argv)

    now = (datetime.strptime(args.now, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=model.UTC)
           if args.now else datetime.now(model.UTC))
    day = args.date or now.date().isoformat()

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

    rec = run_once(root=root, day=day, period=args.period, stage=args.stage,
                   source=args.source, now_utc=now, sender=sender,
                   config=load_json("config.example.json", args.config),
                   schedule=load_json("schedule.json", args.schedule))
    print(json.dumps(rec, ensure_ascii=False))
    # 业务失败已如实入日志，退出码保持 0，避免中断 Actions 的每日提交证据链。
    return 0


if __name__ == "__main__":
    sys.exit(main())
