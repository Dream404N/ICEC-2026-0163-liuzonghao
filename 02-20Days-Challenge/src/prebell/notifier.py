"""把「这一大节 + 今天全天」渲染成一条真正能当日程用的微信消息。

设计原则：一条消息就该看完今天。哪怕后面某一轮 GitHub cron 排队丢了，
第一条推送里也已经写全了全天课程，不会让人漏课。
"""
import json
from datetime import date
from pathlib import Path

from prebell import model


def load_messages(path=None):
    p = Path(path) if path else Path(__file__).with_name("messages.json")
    return json.loads(p.read_text(encoding="utf-8"))


def course_line(c):
    bits = [c.get("name") or "（课程名待核对）"]
    if c.get("room"):
        bits.append(c["room"])
    if c.get("form"):
        bits.append(c["form"])
    return " · ".join(bits)


def render(entry, today_entries, messages=None, late_by_min=0):
    """entry: 本轮要提醒的大节；today_entries: 当天全部大节（按时间排序）。"""
    m = messages or load_messages()
    courses = entry["courses"]
    first = courses[0].get("name") or m["no_course_label"]
    title = m["title"].format(start=entry["class_start"], first_course=first)[:32]

    d = date.fromisoformat(entry["date"])
    wd = model.WEEKDAY_CN[d.weekday()]
    lines = [
        "**今天 · %s %s · 第 %d 周**" % (d.strftime("%m月%d日"), wd, entry["week"]),
        "",
        "### ⏰ %s %s" % (entry["class_start"], first),
    ]
    for c in courses:
        lines.append("- **%s**" % course_line(c))
    if entry.get("span_note"):
        lines.append("- %s" % entry["span_note"])
    if late_by_min and late_by_min > 0:
        lines.append("- ⚠ 这条实际晚到 **%d 分钟**（GitHub 定时任务排队），已如实记录。" % late_by_min)
    lines.append("")

    rest = [e for e in today_entries if e["key"] != entry["key"]]
    if rest:
        lines += ["### 今天其余的课", ""]
        for e in sorted(rest, key=lambda x: x["class_start"]):
            for c in e["courses"]:
                lines.append("- %s %s" % (e["class_start"], course_line(c)))
        lines.append("")
    else:
        lines += ["今天只有这一节。", ""]

    lines.append(m["footer"])
    return title, "\n".join(lines)
