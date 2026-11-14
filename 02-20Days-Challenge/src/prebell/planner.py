"""整学期一次性展开静态提醒表（不做运行时周次推断）。

每条记录以 {date}-{period}-{stage} 为唯一键；同一节课必有 depart 与 enter 两条。
"""
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prebell import model

HERE = Path(__file__).resolve().parent


def load_json(name):
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def build(timetable=None, config=None):
    timetable = timetable or load_json("timetable.json")
    config = config or load_json("config.example.json")

    starts = {p["id"]: p["start"] for p in timetable["periods"]}
    entries = []
    day = date.fromisoformat(config["plan_from"])
    end = date.fromisoformat(config["plan_to"])

    while day <= end:
        dow = day.isoweekday()
        for period in model.PERIODS:
            if dow not in timetable["has_class_days"].get(period, []):
                continue
            class_start = starts[period]
            for stage in model.STAGES:
                minutes_before = config["stages"][stage]["minutes_before"]
                fire_at = model.fire_at_of(class_start, minutes_before)
                utc_dt = model.utc_datetime(day, fire_at)
                entries.append({
                    "key": model.make_key(day.isoformat(), period, stage),
                    "date": day.isoformat(),
                    "period": period,
                    "stage": stage,
                    "class_start": class_start,
                    "fire_at": fire_at,
                    "fire_utc": utc_dt.strftime("%H:%M"),
                    "dow": dow,
                    "minutes_before": minutes_before,
                    "message_key": stage,
                    "course": None,
                })
        day += timedelta(days=1)

    per_week = {}
    for e in entries:
        d = date.fromisoformat(e["date"])
        week = d.isocalendar()[:2]
        per_week[week] = per_week.get(week, 0) + 1

    anchor = timetable["anchor"]
    return {
        "generated_at": datetime.now(model.CST).isoformat(timespec="seconds"),
        "plan_from": config["plan_from"],
        "plan_to": config["plan_to"],
        "based_on": "estimated" if not anchor.get("verified") else "verified",
        "anchor": anchor,
        "count_per_week": max(per_week.values()) if per_week else 0,
        "total_entries": len(entries),
        "entries": entries,
        "limits_note": "上课时刻源自估算锚点；无单双周/调休支持；9/10 课表格未核对，课程名一律显示「课程（课表未核对）」。",
    }


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="生成静态提醒表 schedule.json")
    ap.add_argument("--out", default=str(HERE / "schedule.json"))
    ap.add_argument("--check", action="store_true", help="只校验不写文件")
    args = ap.parse_args(argv)

    data = build()
    keys = [e["key"] for e in data["entries"]]
    assert len(keys) == len(set(keys)), "唯一键重复"
    assert data["count_per_week"] == 20, "每周应为 20 条（10 个有课大节 × 2 阶段）"
    pairs = {}
    for e in data["entries"]:
        pairs.setdefault((e["date"], e["period"]), set()).add(e["stage"])
    assert all(v == set(model.STAGES) for v in pairs.values()), "存在缺少阶段的条目"
    if not args.check:
        Path(args.out).write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("已生成 %s：%d 条，%d 条/周" % (args.out, data["total_entries"], data["count_per_week"]))
    else:
        print("校验通过：%d 条，%d 条/周" % (data["total_entries"], data["count_per_week"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
