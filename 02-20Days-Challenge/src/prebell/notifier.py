"""两套提醒文案。课表未核对时绝不编造课程名。"""
import json
from pathlib import Path

UNKNOWN_COURSE = "课程（课表未核对）"


def load_messages(path=None):
    p = Path(path) if path else Path(__file__).with_name("messages.json")
    return json.loads(p.read_text(encoding="utf-8"))


def render(stage, entry, messages, course=None):
    """返回 (title, content)；企业微信 text 类型没有标题字段，标题放正文首行。"""
    tpl = messages[stage]
    values = {
        "course": course or UNKNOWN_COURSE,
        "date": entry["date"],
        "period": entry["period"],
        "class_start": entry["class_start"],
        "fire_at": entry["fire_at"],
    }
    body = tpl["body"].format(**values)
    return tpl["title"], body
