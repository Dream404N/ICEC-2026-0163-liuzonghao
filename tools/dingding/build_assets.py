"""叮叮课表 · 三端产物生成器（纯本地，不联网）

一份课表数据，一次生成：
  windows/叮叮课表.html      Windows 双击即用（浏览器打开）
  windows/叮叮课表.ics       导入 Windows 日历 / Outlook，系统负责提醒
  android/assets/index.html  APK 内嵌界面（WebView 加载，自动切到安卓模式）

课表唯一来源是 02-20Days-Challenge/src/prebell/schedule.json（140 条真实课程）。
改课表只需重跑 planner.py 再跑本脚本，三端同步，不手工抄任何一格。
"""
import json
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SCHEDULE = REPO / "02-20Days-Challenge" / "src" / "prebell" / "schedule.json"
TEMPLATE = HERE / "templates" / "app.html"
OUT_WIN = HERE / "windows"
OUT_AND = HERE / "android" / "assets"
APP_NAME = "叮叮课表"


def fold(line):
    """iCalendar 折行：按 UTF-8 字节计，续行以一个空格开头。"""
    if len(line.encode("utf-8")) <= 75:
        return line
    out, cur, n = [], "", 0
    for ch in line:
        w = len(ch.encode("utf-8"))
        if n + w > 74:
            out.append(cur)
            cur, n = " " + ch, 1 + w
        else:
            cur, n = cur + ch, n + w
    out.append(cur)
    return "\r\n".join(out)


def esc(s):
    return (str(s or "").replace("\\", "\\\\").replace(";", "\\;")
            .replace(",", "\\,").replace("\n", "\\n"))


def stamp(d, t):
    return d.replace("-", "") + "T" + t.replace(":", "") + "00"


def build_ics(entries):
    now = datetime.now().strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//DingDingTimetable//CN",
             "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
             "X-WR-CALNAME:" + APP_NAME, "X-WR-TIMEZONE:Asia/Shanghai"]
    for e in entries:
        lines += [
            "BEGIN:VEVENT",
            "UID:dingding-%s-%s@icec" % (e["d"], e["p"]),
            "DTSTAMP:" + now,
            "DTSTART:" + stamp(e["d"], e["s"]),
            "DTEND:" + stamp(e["d"], e["e"]),
            "SUMMARY:" + esc(" / ".join(e["n"])),
            "LOCATION:" + esc(" / ".join(x for x in e["m"] if x)),
            "DESCRIPTION:" + esc("第%d周 · %s" % (e["w"], e["pl"])),
            "BEGIN:VALARM", "TRIGGER:-PT20M", "ACTION:DISPLAY",
            "DESCRIPTION:" + APP_NAME + "：该去上课了", "END:VALARM",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(x) for x in lines) + "\r\n"


def slim(raw):
    periods = [{"id": p["id"], "label": p["label"], "start": p["start"],
                "end": p["end"], "remind_at": p["remind_at"]}
               for p in raw["periods"]]
    entries = []
    for e in raw["entries"]:
        entries.append({
            "d": e["date"], "w": e["week"], "p": e["period"],
            "pl": e["period_label"], "s": e["class_start"],
            "e": e["class_end"], "r": e["remind_at"],
            "n": [c["name"] for c in e["courses"]],
            "m": [c.get("room") or "" for c in e["courses"]],
        })
    entries.sort(key=lambda x: (x["d"], x["s"]))
    anchor = raw.get("anchor", {})
    verified = bool(anchor.get("verified")) and bool(raw.get("meta", {}).get("proofread"))
    return {
        "name": APP_NAME,
        "anchor": anchor.get("first_monday", "2026-09-07"),
        "anchor_verified": verified,
        "periods": periods,
        "entries": entries,
    }


def main():
    raw = json.loads(SCHEDULE.read_text(encoding="utf-8"))
    data = slim(raw)
    assert data["entries"], "课表是空的，拒绝生成空壳"
    assert all(e["n"] and e["n"][0] for e in data["entries"]), "存在空课程名"
    assert len(set((e["d"], e["p"]) for e in data["entries"])) == len(data["entries"]), "提醒键重复"

    js = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    html = TEMPLATE.read_text(encoding="utf-8").replace("__DINGDING_DATA__", js)
    assert "__DINGDING_DATA__" not in html, "模板占位符未替换"

    OUT_WIN.mkdir(parents=True, exist_ok=True)
    OUT_AND.mkdir(parents=True, exist_ok=True)
    (OUT_WIN / "叮叮课表.html").write_text(html, encoding="utf-8")
    (OUT_AND / "index.html").write_text(html, encoding="utf-8")
    (OUT_WIN / "叮叮课表.ics").write_text(build_ics(data["entries"]), encoding="utf-8", newline="")

    print("叮叮课表：%d 条真实课程，覆盖 %s ~ %s"
          % (len(data["entries"]), data["entries"][0]["d"], data["entries"][-1]["d"]))
    print("  windows/叮叮课表.html / 叮叮课表.ics")
    print("  android/assets/index.html")
    print("  第 1 周锚点 %s，已核对=%s" % (data["anchor"], data["anchor_verified"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
