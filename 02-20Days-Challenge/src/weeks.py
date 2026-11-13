"""课表周次表达式解析（零第三方依赖）。

学校课表把「哪几周上课」塞在单元格文字里，写法混杂：

    3-13周,16-18周(混合)
    4-7周,12-13周,16周(讲课)
    3周,6周,9周,12周,17周(实践)
    18周(实践) / 10周(讲课) / 3-11周(理论)

本模块只做确定性展开：范围、单周、逗号混排统一处理，括注里的教学形式单独取出
只作展示、不推断含义。解析不了的片段进 unknown，由调用方标 needs_review，
绝不猜一个值填进去。
"""
from __future__ import annotations

import re

_RE_WEEK = re.compile(r"(\d{1,2})\s*(?:-\s*(\d{1,2}))?\s*周")
_RE_FORM = re.compile(r"\((讲课|实验|实训|混合|实践|理论|上机|习题|研讨)\)")
_RE_SEP = re.compile(r"[,，、;；\s]+")
MAX_WEEK = 30


def parse_weeks(raw):
    """返回 (sorted_weeks, form, unknown)。

    raw 为 None 或空时返回 ([], "", ["<empty>"])，由调用方决定是否跳过该课，
    不返回占位周次。
    """
    if not raw or not str(raw).strip():
        return [], "", ["<empty>"]
    text = str(raw)
    weeks = set()
    unknown = []

    for m in _RE_WEEK.finditer(text):
        a = int(m.group(1))
        b = int(m.group(2)) if m.group(2) else a
        if a < 1 or b > MAX_WEEK or a > b:
            unknown.append(m.group(0))
            continue
        weeks.update(range(a, b + 1))

    form_match = _RE_FORM.search(text)
    form = form_match.group(1) if form_match else ""

    # 去掉所有能解释的片段，剩下的就是无法解析的残留
    residue = _RE_WEEK.sub("", text)
    residue = _RE_FORM.sub("", residue)
    residue = _RE_SEP.sub("", residue)
    if residue:
        unknown.append(residue[:80])

    return sorted(weeks), form, unknown


def parse_cell_courses(cell):
    """把一格里的所有课程解析出 weeks 列表，并汇总 unknown。

    返回 (courses, unknown, conflicts)。conflicts 是同一周命中多门课的周号列表，
    显式上报，不静默挑一门。
    """
    courses = []
    unknown = []
    for c in cell.get("courses", []):
        item = dict(c)
        w, form, unk = parse_weeks(c.get("weeks_raw"))
        item["weeks"] = w
        if form and not item.get("form"):
            item["form"] = form
        item["parse_unknown"] = unk
        unknown.extend("%s: %s" % (c.get("course_id", "?"), u) for u in unk)
        courses.append(item)

    by_week = {}
    for c in courses:
        for w in c["weeks"]:
            by_week.setdefault(w, []).append(c.get("course_id", "?"))
    conflicts = sorted(w for w, ids in by_week.items() if len(ids) > 1)
    return courses, unknown, conflicts


SAMPLES = [
    "3-13周,16-18周(混合)",
    "4-7周,12-13周,16周(讲课)",
    "3周,6周,9周,12周,17周(实践)",
    "18周(实践)",
    "10周(讲课)",
    "3-11周(理论)",
]


def self_test():
    for s in SAMPLES:
        w, form, unk = parse_weeks(s)
        print("  %-34s -> %-38s form=%-4s unknown=%s" % (s, str(w), form or "-", unk))
    return 0


if __name__ == "__main__":
    raise SystemExit(self_test())
