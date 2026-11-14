"""验真：唯一键三元组、哈希链、7 天连续、明细/汇总计数一致、无未来时间戳。"""
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prebell import ledger, model

HERE = Path(__file__).resolve().parent


def load_schedule(path=None):
    p = Path(path) if path else HERE / "schedule.json"
    return json.loads(p.read_text(encoding="utf-8"))


def verify_day(root, day, schedule=None):
    schedule = schedule or load_schedule()
    rows = ledger.read_records(root, day)
    valid_keys = {e["key"] for e in schedule["entries"] if e["date"] == day}

    chain_ok, prev = True, "genesis"
    for r in rows:
        if r.get("prev_hash") != prev:
            chain_ok = False
            break
        if r.get("hash") != ledger.chain_hash(prev, r):
            chain_ok = False
            break
        prev = r["hash"]

    key_ok = all(r.get("key") in valid_keys for r in rows)
    no_future = True
    for r in rows:
        try:
            t = datetime.strptime(r.get("ts", "")[:16], "%Y-%m-%d %H:%M").replace(tzinfo=model.CST)
            if t > datetime.now(model.CST) + timedelta(minutes=1):
                no_future = False
        except ValueError:
            no_future = False

    sp = ledger.summary_path(root, day)
    count_ok = False
    if sp.exists():
        s = json.loads(sp.read_text(encoding="utf-8"))
        tally = sum(s.get(k, 0) for k in (
            "sent", "failed", "skipped_late", "skipped_after_class",
            "duplicate", "skipped_early", "throttled", "no_schedule"))
        count_ok = (s.get("attempted", -1) == s.get("sent", 0) + s.get("failed", 0)
                    and tally == s.get("chain_len") == len(rows)
                    and s.get("expected") == len(valid_keys))

    return {
        "date": day,
        "key_triplet_ok": key_ok,
        "chain_ok": chain_ok,
        "count_ok": count_ok,
        "no_future_ts": no_future,
        "records": len(rows),
        "expected": len(valid_keys),
        "all_ok": key_ok and chain_ok and count_ok and no_future,
    }


def verify_window(root, end_day, days=7, schedule=None):
    end = date.fromisoformat(end_day)
    out = []
    for i in range(days - 1, -1, -1):
        d = (end - timedelta(days=i)).isoformat()
        has_log = ledger.log_path(root, d).exists()
        has_summary = ledger.summary_path(root, d).exists()
        out.append({"date": d, "log": has_log, "summary": has_summary,
                    "verified": verify_day(root, d, schedule)["all_ok"]})
    return {"window_days": days, "continuous": all(x["log"] for x in out), "days": out}


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="验真每日日志与证据链")
    ap.add_argument("--date", default=datetime.now(model.UTC).date().isoformat())
    ap.add_argument("--window", type=int, default=0, help="检查最近 N 天连续")
    ap.add_argument("--root", default=str(HERE.parents[1]))
    args = ap.parse_args(argv)

    report = verify_day(args.root, args.date)
    if args.window:
        report["window"] = verify_window(args.root, args.date, args.window)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["all_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
