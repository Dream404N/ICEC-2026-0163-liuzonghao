"""日志哈希链与脱敏。零第三方依赖，Python 3.8+。

设计口径：
  - 每条记录含前一条的 hash，改任何一行，后面全部对不上；
  - 每天全部记录两两归约出一个 Merkle root，写进当天最后一次 commit message；
  - 时间只到分钟，不记录毫秒、IP、主机名、绝对路径、请求正文；
  - 错误文本先脱敏，另留 8 位指纹便于归类，不写原始报错。
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOGDIR = ROOT / "process_logs"
STATEDIR = ROOT / "state"
PUBLICDIR = ROOT / "public"
CST = timezone(timedelta(hours=8))
ZERO = "0" * 64

_RE_PATH = re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+[^\s\"']+", re.I)
_RE_IP = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
_RE_URL = re.compile(r"https?://\S+")


def now():
    return datetime.now(CST)


def canonical(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def scrub(text) -> str:
    """把报错/标题里可能带个人信息的片段抹掉。"""
    s = str(text or "")
    s = _RE_PATH.sub("[path]", s)
    s = _RE_IP.sub("[ip]", s)
    s = _RE_URL.sub("[url]", s)
    return s[:200]


def fingerprint(text) -> str:
    return hashlib.sha256(scrub(text).encode("utf-8")).hexdigest()[:8]


def entry_hash(record: dict, prev: str) -> str:
    payload = dict(record)
    payload.pop("hash", None)
    payload.pop("prev_hash", None)
    return hashlib.sha256((prev + canonical(payload)).encode("utf-8")).hexdigest()


def last_hash(path: Path) -> str:
    if not path.exists():
        return ZERO
    last = ZERO
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                last = json.loads(line).get("hash", last)
            except json.JSONDecodeError:
                continue
    return last


def append_round(record: dict) -> str:
    """追加一轮记录，返回本轮 hash。只追加，绝不回填历史。"""
    LOGDIR.mkdir(parents=True, exist_ok=True)
    path = LOGDIR / (record["date"] + ".jsonl")
    prev = last_hash(path)
    record["prev_hash"] = prev
    record["hash"] = entry_hash(record, prev)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(canonical(record) + "\n")
    return record["hash"]


def merkle_root(hashes):
    if not hashes:
        return hashlib.sha256(b"empty-day").hexdigest()
    layer = [bytes.fromhex(h) for h in hashes]
    while len(layer) > 1:
        if len(layer) % 2:
            layer.append(layer[-1])
        layer = [hashlib.sha256(layer[i] + layer[i + 1]).digest()
                 for i in range(0, len(layer), 2)]
    return layer[0].hex()


def load_day(date: str):
    path = LOGDIR / (date + ".jsonl")
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                out.append({"__corrupt__": True, "raw": line[:120]})
    return out


def write_daily_summary(date: str) -> dict:
    rows = load_day(date)
    hashes = [r["hash"] for r in rows if "hash" in r]
    ok = sum(1 for r in rows for s in r.get("sources", []) if s.get("status") == 200)
    calls = sum(len(r.get("sources", [])) for r in rows)
    failed = sum(1 for r in rows for s in r.get("sources", []) if s.get("status") != 200)
    new_items = sum(r.get("new_items", 0) for r in rows)
    summary = {
        "date": date,
        "rounds": len(rows),
        "source_calls": calls,
        "source_ok": ok,
        "source_failed": failed,
        "new_items": new_items,
        "merkle_root": merkle_root(hashes),
        "generated_at": now().strftime("%Y-%m-%d %H:%M"),
    }
    LOGDIR.mkdir(parents=True, exist_ok=True)
    (LOGDIR / (date + ".summary.json")).write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary
