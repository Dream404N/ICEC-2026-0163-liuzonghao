"""共享常量、唯一键与北京/UTC 时刻换算。

唯一键 {date}-{period}-{stage} 只允许由 make_key() 生成：
提醒表 / 去重状态 / 运行日志 / 验真报告四处必须使用同一个函数，
否则同一节课的第二次提醒会被误判成重复或多推。
"""
import re
from datetime import date, datetime, timedelta, timezone

UTC = timezone.utc
CST = timezone(timedelta(hours=8))

STAGES = ("depart", "enter")
PERIODS = ("P1", "P3", "P4")

DEFAULT_STAGES = {
    "depart": {"minutes_before": 30, "late_tolerance_min": 10},
    "enter": {"minutes_before": 5, "late_tolerance_min": 3},
}

TERMINAL_STATES = (
    "sent", "failed", "skipped_late", "skipped_after_class", "duplicate",
)


def make_key(day, period, stage):
    """day: YYYY-MM-DD；period: P1/P3/P4；stage: depart/enter。"""
    if stage not in STAGES:
        raise ValueError("unknown stage: %s" % stage)
    return "%s-%s-%s" % (day, period, stage)


def hhmm_to_minutes(text):
    h, m = text.split(":")
    return int(h) * 60 + int(m)


def minutes_to_hhmm(total):
    h, m = divmod(int(total), 60)
    return "%02d:%02d" % (h, m)


def fire_at_of(class_start, minutes_before):
    """由上课时刻倒推推送时刻（北京 HH:MM）。"""
    return minutes_to_hhmm(hhmm_to_minutes(class_start) - minutes_before)


def utc_datetime(day, hhmm):
    """把北京时间的 (日期, HH:MM) 转成 aware UTC datetime。"""
    d = date.fromisoformat(day) if isinstance(day, str) else day
    h, m = (int(x) for x in hhmm.split(":"))
    return datetime(d.year, d.month, d.day, h, m, tzinfo=CST).astimezone(UTC)


def iso_utc(dt):
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def scrub_text(text):
    """日志脱敏：webhook key、SendKey、URL 一律抹掉，绝不留进仓库。"""
    s = str(text)
    s = re.sub(r"key=[A-Za-z0-9_\-]+", "key=[redacted]", s)
    s = re.sub(r"sctp?[A-Za-z0-9]{8,}", "[sendkey]", s, flags=re.I)
    s = re.sub(r"https?://\S+", "[url]", s)
    return s[:300]
