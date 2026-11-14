"""JSONL 明细日志 + SHA-256 哈希链 + 每日汇总。

官网项目四要求的四类字段由代码赋值，不手写：
  ts           脱敏时间戳（日期 + 分钟级，不含账号/设备/IP）
  seq          当天第几次调用（调用频次）
  duration_ms  推送耗时
  error        报错记录（脱敏后）
"""
import hashlib
import json
from pathlib import Path

from prebell import model


def log_path(root, day):
    return Path(root) / "process_logs" / ("%s.jsonl" % day)


def summary_path(root, day):
    return Path(root) / "process_logs" / ("%s.summary.json" % day)


def canonical(record):
    d = {k: v for k, v in record.items() if k not in ("prev_hash", "hash")}
    return json.dumps(d, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def chain_hash(prev_hash, record):
    raw = (prev_hash + canonical(record)).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def read_records(root, day):
    p = log_path(root, day)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def append_record(root, day, record):
    """追加一条记录并续上哈希链；重复调用不会覆盖历史。"""
    p = log_path(root, day)
    p.parent.mkdir(parents=True, exist_ok=True)
    rows = read_records(root, day)
    prev = rows[-1]["hash"] if rows else "genesis"
    record["prev_hash"] = prev
    record["hash"] = chain_hash(prev, record)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return record


def rollup(root, day, expected):
    """每日汇总。无课日 expected=0，heartbeat=true 表示汇总任务真实运行过。"""
    rows = read_records(root, day)

    def count(pred):
        return sum(1 for r in rows if pred(r))

    latencies = [
        r["latency_ms"] for r in rows
        if isinstance(r.get("latency_ms"), int) and r["latency_ms"] >= 0
    ]
    summary = {
        "date": day,
        "timezone": "UTC+8",
        "heartbeat": True,
        "expected": expected,
        "attempted": count(lambda r: r.get("action") == "send"),
        "sent": count(lambda r: r.get("result") == "ok"),
        "failed": count(lambda r: r.get("result") == "error"),
        "skipped_late": count(lambda r: r.get("action") == "skipped_late"),
        "skipped_after_class": count(lambda r: r.get("action") == "skipped_after_class"),
        "duplicate": count(lambda r: r.get("action") == "duplicate"),
        "skipped_early": count(lambda r: r.get("action") == "skipped_early"),
        "throttled": count(lambda r: r.get("action") == "throttled"),
        "no_schedule": count(lambda r: r.get("action") == "no_schedule"),
        "per_period": {
            p: count(lambda r, p=p: r.get("period") == p) for p in model.PERIODS
        },
        "channels_used": sorted({r["channel"] for r in rows if r.get("channel")}),
        "latency_ms": {
            "max": max(latencies) if latencies else 0,
            "avg": int(sum(latencies) / len(latencies)) if latencies else 0,
        },
        "chain_head": rows[-1]["hash"] if rows else "",
        "chain_len": len(rows),
    }
    p = summary_path(root, day)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary
