"""共享常量、唯一键、周次解析与北京/UTC 时刻换算。

唯一键 {date}-{period} 只允许由 make_key() 生成：推送表、去重状态、
运行日志、验真报告四处必须用同一个函数，否则会误判重复或多推。
"""
import re
from datetime import date, datetime, timedelta, timezone

UTC = timezone.utc
CST = timezone(timedelta(hours=8))

PERIODS = ("P1", "P2", "P3", "P4")
WEEKDAY_CN = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


def make_key(day, period):
    """day: YYYY-MM-DD；period: P1/P2/P3/P4。一节一次提醒，不存在第二个阶段。"""
    if period not in PERIODS:
        raise ValueError("unknown period: %s" % period)
    return "%s-%s" % (day, period)


def parse_weeks(raw):
    """展开周次原文，如 '3-13周,16-18周(混合)' / '3周,6周,9周,12周,17周(实践)'。

    只认「数字」「数字-数字」与逗号；括注（讲课/实践/混合/实训）只作形式说明，不参与周次。
    遇到无法解析的片段直接抛错，绝不悄悄跳过——漏一周就会漏一节课。
    """
    if not raw:
        return []
    s = re.sub(r"\([^)]*\)", "", str(raw))
    s = s.replace("（", "(").replace("）", ")")
    s = re.sub(r"\([^)]*\)", "", s)
    s = s.replace("周", "").replace("，", ",").replace("、", ",")
    out = []
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        m = re.fullmatch(r"(\d+)\s*[-~至]\s*(\d+)", part)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if a > b:
                raise ValueError("reversed week range: %r" % part)
            out.extend(range(a, b + 1))
        elif re.fullmatch(r"\d+", part):
            out.append(int(part))
        else:
            raise ValueError("unparsed week token %r in %r" % (part, raw))
    return sorted(set(out))


def parse_form(raw):
    m = re.search(r"\(([^)]*)\)", str(raw or ""))
    return m.group(1) if m else ""


def week_index(day, first_monday):
    """第几教学周；早于锚点返回非正数。"""
    d = date.fromisoformat(day) if isinstance(day, str) else day
    a = date.fromisoformat(first_monday) if isinstance(first_monday, str) else first_monday
    return (d - a).days // 7 + 1


def hhmm_to_minutes(text):
    h, m = text.split(":")
    return int(h) * 60 + int(m)


def minutes_to_hhmm(total):
    h, m = divmod(int(total), 60)
    return "%02d:%02d" % (h, m)


def fire_at_of(class_start, minutes_before):
    return minutes_to_hhmm(hhmm_to_minutes(class_start) - minutes_before)


def utc_datetime(day, hhmm):
    """把北京时间的 (日期, HH:MM) 转成 aware UTC datetime。"""
    d = date.fromisoformat(day) if isinstance(day, str) else day
    h, m = (int(x) for x in hhmm.split(":"))
    return datetime(d.year, d.month, d.day, h, m, tzinfo=CST).astimezone(UTC)


def iso_utc(dt):
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def scrub_text(text):
    """日志脱敏：SendKey / Webhook key / URL 一律抹掉，绝不留进仓库。"""
    s = str(text)
    s = re.sub(r"key=[A-Za-z0-9_\-]+", "key=[redacted]", s)
    s = re.sub(r"sctp?[A-Za-z0-9_\-]{8,}", "[sendkey]", s, flags=re.I)
    s = re.sub(r"\b(?:SPT_|AT_)[A-Za-z0-9_\-]{6,}", "[token]", s, flags=re.I)
    s = re.sub(r"https?://\S+", "[url]", s)
    return s[:300]
