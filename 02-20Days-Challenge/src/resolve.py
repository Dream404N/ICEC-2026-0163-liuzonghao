"""把课表一次性展开成整学期的推送时刻表（离线、只读源数据）。

    python src/resolve.py            # 生成 schedule.json / schedule.md / out/cron-hints.txt
    python src/resolve.py --check    # 只读：校验已生成的表是否与课表同步，不写任何文件

为什么要有这个文件
------------------
课表是一学期的常量，不是天天变的数据。原设计让 GitHub Actions 每 5 分钟醒一次，
每次都重算「第几周 / 下一大节 / 这周有没有课」——同样的输入算同样的结果，
一周空转七十多次，还说不清算得对不对。

改成：在这里算一次，落成可读可审的表；运行时只查表。
课表改了，重跑本文件，并照着 out/cron-hints.txt 改闹钟。

诚实边界
--------
- 周次锚点是估算的（anchor.verified=false），表里每条都带 estimated=true，不粉饰；
- 解析不了的周次片段照样进 unknown，不猜一个值填进去；
- 同一格同一周命中多门课记 conflicts 并列，不静默挑一门；
- 表包含整学期（含已过去的周），这样产物是确定性的，不会因为「今天几号」而变。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from chain import now  # noqa: E402
from weeks import parse_cell_courses  # noqa: E402

TIMETABLE = HERE / "timetable.json"
CONFIG = HERE / "config.example.json"
SCHEDULE = HERE / "schedule.json"
SCHEDULE_MD = HERE / "schedule.md"
HINTS = HERE / "out" / "cron-hints.txt"
WORKFLOW = HERE.parents[1] / ".github" / "workflows" / "prebell.yml"

WEEKDAY_CN = ["一", "二", "三", "四", "五", "六", "日"]
DEFAULT_LEAD = 20


# ---------------- 小工具 ----------------

def load_json(path, default=None):
    if not path.exists():
        return default if default is not None else {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default if default is not None else {}


def minutes_of(s):
    h, m = str(s).split(":")
    return int(h) * 60 + int(m)


def shift_minutes(hhmm, delta):
    """把 HH:MM 平移 delta 分钟，返回 (HH:MM, 跨了几天的偏移)。"""
    total = minutes_of(hhmm) + delta
    day_shift = total // (24 * 60)
    total %= 24 * 60
    return "%02d:%02d" % (total // 60, total % 60), day_shift


def end_time_of(periods, cell):
    start_idx = int(cell.get("period", 1)) - 1
    span = max(1, int(cell.get("span", 1)))
    end_idx = min(len(periods) - 1, start_idx + span - 1)
    return periods[end_idx]["end"]


def cron_field(hhmm_cst):
    """北京时刻 -> (UTC 分钟, UTC 小时, 跨天天数)。

    跨天天数在本课表恒为 0（推送点都在北京白天）；保留计算是为了以后
    改时段时不至于把星期算错却不自知。
    """
    utc, shift = shift_minutes(hhmm_cst, -8 * 60)
    h, m = utc.split(":")
    return int(m), int(h), shift


# ---------------- 主计算 ----------------

def build(t, lead_min):
    """把 timetable.json 展开成排好序的推送槽列表 + 统计。"""
    periods = t["periods"]
    anchor = date.fromisoformat(t["anchor"]["first_monday"])
    term_weeks = int(t["meta"].get("term_weeks", 18))
    verified = bool(t["anchor"].get("verified"))

    slots = {}
    unknown_all = []
    conflicts_all = []

    for cell in t["cells"]:
        wd = int(cell["weekday"])
        pid = int(cell["period"])
        p = periods[pid - 1]
        class_end = end_time_of(periods, cell)
        push_at, day_shift = shift_minutes(p["start"], -lead_min)
        if day_shift != 0:
            # 提前量不该跨日；真跨日了说明课太早，必须显式报出来而不是悄悄算错
            raise SystemExit("推送时刻跨日：period=%s start=%s lead=%d" % (pid, p["start"], lead_min))

        courses, unknown, conflicts = parse_cell_courses(cell)
        unknown_all.extend("%s: %s" % (cell.get("id"), u) for u in unknown)
        conflicts_all.extend({"cell_id": cell.get("id"), "week": w} for w in conflicts)

        for c in courses:
            for w in c.get("weeks", []):
                if not (1 <= w <= term_weeks):
                    continue
                d = anchor + timedelta(weeks=w - 1, days=wd - 1)
                key = "%s-P%s" % (d.isoformat(), pid)
                slot = slots.get(key)
                if slot is None:
                    slot = slots[key] = {
                        "id": key,
                        "date": d.isoformat(),
                        "weekday": wd,
                        "weekday_cn": "星期" + WEEKDAY_CN[wd - 1],
                        "week": w,
                        "period": pid,
                        "period_label": p["label"],
                        "class_start": p["start"],
                        "class_end": class_end,
                        "push_at": push_at,
                        "lead_minutes": lead_min,
                        "estimated": not verified,
                        "courses": [],
                        "needs_review": False,
                    }
                slot["courses"].append({
                    "course_id": c.get("course_id"),
                    "name": c.get("name"),
                    "room": c.get("room"),
                    "teacher": c.get("teacher"),
                    "form": c.get("form"),
                    "weeks_raw": c.get("weeks_raw"),
                    "cell_id": cell.get("id"),
                    "merged": bool(cell.get("merged")),
                    "unclear": list(c.get("unclear") or []),
                })
                if c.get("unclear") or cell.get("unclear"):
                    slot["needs_review"] = True

    ordered = sorted(slots.values(), key=lambda s: (s["date"], s["period"]))
    return ordered, unknown_all, conflicts_all


def cron_hints(t, lead_min):
    """由「课表上哪一格有课」反推需要几条定时闹钟。

    这里读的是 cells 而不是 push_slots，这一点很关键：某格的周次没辨认出来时
    那周不会进推送表，但这门课确实存在、闹钟仍然该在。宁可多响一次让脚本
    自己判「本周无课」，也不能因为转录缺个字段就整天不响。
    """
    periods = t["periods"]
    by_period = {}
    for cell in t["cells"]:
        by_period.setdefault(int(cell["period"]), set()).add(int(cell["weekday"]))

    hints = []
    for pid in sorted(by_period):
        p = periods[pid - 1]
        push_at, _ = shift_minutes(p["start"], -lead_min)
        minute, hour, day_shift = cron_field(push_at)
        wds = sorted(by_period[pid])
        # isoweekday(1=周一…7=周日) -> cron(0=周日, 1=周一…6=周六)，再按 UTC 跨天回退
        fields = sorted({((w % 7) + day_shift) % 7 for w in wds})
        hints.append({
            "period": pid,
            "period_label": p["label"],
            "class_start": p["start"],
            "push_at_cst": push_at,
            "cron_utc": "%d %d * * %s" % (minute, hour, ",".join(str(x) for x in fields)),
            "weekdays_cn": [WEEKDAY_CN[w - 1] for w in wds],
        })
    return hints


# ---------------- 产物 ----------------

def render_hints(hints, total, term_weeks):
    lines = [
        "# 由 src/resolve.py 从 src/timetable.json 生成，勿手改。",
        "# 时区：UTC（北京 = UTC + 8）。cron-job.org 的 job 时区保持 UTC 即可。",
        "# 每组对应一个 job，body 里的 \"period\" 填下面的数字。",
        "# 课表变了就重跑 resolve.py，回来照抄这一段。",
        "#",
        "# 本表共 %d 条推送，覆盖第 1-%d 周。" % (total, term_weeks),
        "",
    ]
    for h in hints:
        lines.append(
            "period=%d  北京 %s（%s %s）  ->  cron: %s"
            % (h["period"], h["push_at_cst"], h["period_label"], h["class_start"], h["cron_utc"]))
        lines.append("           出现在：%s" % "、".join("周" + w for w in h["weekdays_cn"]))
    lines.append("")
    lines.append("# 对应的 workflow 触发 body：")
    for h in hints:
        lines.append('#   {"ref":"main","inputs":{"period":"%d","source":"cronjob"}}' % h["period"])
    return "\n".join(lines) + "\n"


def render_md(payload):
    meta = payload["meta"]
    slots = payload["push_slots"]
    lines = [
        "# PreBell · 整学期推送表",
        "",
        "> 由 `src/resolve.py` 从 `src/timetable.json` 生成，**不要手改**。",
        "> 第 1 周周一 = %s（%s），推送提前 %d 分钟。"
        % (meta["anchor_first_monday"],
           "已核对" if meta["anchor_verified"] else "**估算、尚未核对**", meta["lead_minutes"]),
        "> 全部条目共 %d 条，覆盖第 1–%d 周。" % (len(slots), meta["term_weeks"]),
        "",
    ]
    if not meta["anchor_verified"]:
        lines += ["> ⚠ 锚点是估算值，表中每个日期都是推导出来的，核对前请勿当作真实提醒。", ""]

    # 按周汇总
    by_week = {}
    for s in slots:
        by_week.setdefault(s["week"], []).append(s)
    lines += ["## 按周汇总", "", "| 周 | 日期区间 | 推送条数 |", "|---|---|---|"]
    for w in sorted(by_week):
        days = [date.fromisoformat(s["date"]) for s in by_week[w]]
        lines.append("| 第 %d 周 | %s ~ %s | %d |"
                     % (w, min(days).isoformat(), max(days).isoformat(), len(by_week[w])))
    lines.append("")

    # 明细
    lines += ["## 明细", "",
              "| # | 日期 | 星期 | 周 | 大节 | 上课 | 推送 | 课程 | 教室 | 待核对 |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for i, s in enumerate(slots, 1):
        names = "<br>".join(c.get("name") or "〈待核对〉" for c in s["courses"])
        rooms = "<br>".join(c.get("room") or "—" for c in s["courses"])
        lines.append("| %d | %s | %s | %d | %s | %s | **%s** | %s | %s | %s |"
                     % (i, s["date"], s["weekday_cn"].replace("星期", ""), s["week"], s["period"],
                        s["class_start"], s["push_at"], names, rooms,
                        "是" if s["needs_review"] else ""))
    lines.append("")

    if payload["parse_unknown"]:
        lines += ["## 解析不了的周次片段", ""]
        lines += ["- `%s`" % u for u in payload["parse_unknown"]]
        lines.append("")
    if payload["conflicts"]:
        lines += ["## 同格同周多门课", ""]
        lines += ["- `%s` 第 %d 周" % (c["cell_id"], c["week"]) for c in payload["conflicts"]]
        lines.append("")
    lines += ["## 闹钟", "",
              "```",
              render_hints(payload["cron_hints"], len(slots), meta["term_weeks"]).rstrip(),
              "```", ""]
    return "\n".join(lines) + "\n"


def payload_of(t, lead_min):
    slots, unknown, conflicts = build(t, lead_min)
    hints = cron_hints(t, lead_min)
    return {
        "meta": {
            "generated_by": "src/resolve.py",
            "generated_at": now().strftime("%Y-%m-%d %H:%M"),
            "anchor_first_monday": t["anchor"]["first_monday"],
            "anchor_verified": bool(t["anchor"].get("verified")),
            "anchor_note": t["anchor"].get("display_wording", ""),
            "term_weeks": int(t["meta"].get("term_weeks", 18)),
            "lead_minutes": lead_min,
            "proofread": bool(t["meta"].get("proofread")),
            "note": "整学期一次性展开，运行时只查表不重算。锚点未核对时所有日期为推导值。",
        },
        "cron_hints": hints,
        "push_slots": slots,
        "parse_unknown": unknown,
        "conflicts": conflicts,
    }


# ---------------- 自查 ----------------

def check_workflow_has_no_cron():
    """workflow 里不该再有生效的 schedule——定时已经搬到 cron-job.org。"""
    if not WORKFLOW.exists():
        return []
    issues = []
    for i, line in enumerate(WORKFLOW.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            continue
        if "cron:" in stripped or stripped.startswith("schedule:"):
            issues.append("prebell.yml 第 %d 行仍有生效的 schedule/cron：%s" % (i, stripped))
    return issues


def main():
    ap = argparse.ArgumentParser(description="整学期推送表生成 / 校验")
    ap.add_argument("--check", action="store_true", help="只读校验，不写文件")
    args = ap.parse_args()

    t = load_json(TIMETABLE, {})
    if not t:
        print("timetable.json 缺失或无法解析")
        return 1
    cfg = load_json(CONFIG, {})
    lead_min = int(cfg.get("push_lead_minutes", DEFAULT_LEAD))

    fresh = payload_of(t, lead_min)
    issues = check_workflow_has_no_cron()

    if not args.check:
        SCHEDULE.write_text(json.dumps(fresh, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        SCHEDULE_MD.write_text(render_md(fresh), encoding="utf-8")
        HINTS.parent.mkdir(parents=True, exist_ok=True)
        HINTS.write_text(
            render_hints(fresh["cron_hints"], len(fresh["push_slots"]), fresh["meta"]["term_weeks"]),
            encoding="utf-8")
        print("已生成：")
        print("  %s  （%d 条）" % (SCHEDULE.relative_to(HERE.parent), len(fresh["push_slots"])))
        print("  %s" % SCHEDULE_MD.relative_to(HERE.parent))
        print("  %s" % HINTS.relative_to(HERE.parent))
    else:
        old = load_json(SCHEDULE, {})
        if not old:
            issues.append("schedule.json 还不存在，先跑一次不带 --check 的生成")
        else:
            old_ids = [s["id"] for s in old.get("push_slots", [])]
            new_ids = [s["id"] for s in fresh["push_slots"]]
            added = [i for i in new_ids if i not in set(old_ids)]
            removed = [i for i in old_ids if i not in set(new_ids)]
            if added or removed:
                issues.append(
                    "课表与已生成的表不同步：新增 %d 条、移除 %d 条。请重跑 resolve.py 并检查 cron 是否需要改。"
                    % (len(added), len(removed)))
                for i in added[:5]:
                    print("  + " + i)
                for i in removed[:5]:
                    print("  - " + i)
            old_cron = [h["cron_utc"] for h in old.get("cron_hints", [])]
            new_cron = [h["cron_utc"] for h in fresh["cron_hints"]]
            if old_cron != new_cron:
                issues.append("cron 建议变了：%s -> %s。cron-job.org 上的 job 需要同步修改。"
                              % (old_cron, new_cron))

    print("PreBell · 整学期推送表")
    print("-" * 70)
    for h in fresh["cron_hints"]:
        print("  第%d大节 %s 上课 → %s 推送（北京） | cron UTC: %s | 周%s"
              % (h["period"], h["class_start"], h["push_at_cst"], h["cron_utc"],
                 "、".join(h["weekdays_cn"])))
    print("-" * 70)
    print("共 %d 条推送；解析残留 %d 处；同格冲突 %d 处；待核对 %d 条"
          % (len(fresh["push_slots"]), len(fresh["parse_unknown"]), len(fresh["conflicts"]),
             sum(1 for s in fresh["push_slots"] if s["needs_review"])))

    if issues:
        print("\n发现问题：")
        for i in issues:
            print("  - " + i)
        return 1
    print("\n校验通过：表与课表同步，workflow 里没有残留的 schedule。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
