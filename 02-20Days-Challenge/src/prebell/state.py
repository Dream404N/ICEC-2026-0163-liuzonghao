"""按三元组唯一键去重的运行状态。

注意：state/ 是 protected 目录，只在云端 GitHub Actions 里生成；
本地 dry-run 与单元测试一律把 root 指向临时目录。
"""
import json
from pathlib import Path
from prebell import model

SCHEMA = 1


def state_path(root):
    return Path(root) / "state" / "pushed.json"


def load(root):
    p = state_path(root)
    if not p.exists():
        return {"schema": SCHEMA, "updated_at_utc": None, "pushed": []}
    data = json.loads(p.read_text(encoding="utf-8"))
    data.setdefault("pushed", [])
    return data


def find(state, key):
    for row in state["pushed"]:
        if row.get("key") == key:
            return row
    return None


def record(state, key, status, channel, at_utc):
    row = {"key": key, "status": status, "channel": channel, "at_utc": at_utc}
    old = find(state, key)
    if old is None:
        state["pushed"].append(row)
    else:
        old.update(row)
    state["updated_at_utc"] = at_utc
    return row


def save(state, root):
    p = state_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
