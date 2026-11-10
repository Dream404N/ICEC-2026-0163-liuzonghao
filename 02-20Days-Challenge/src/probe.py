"""单轮入口：抓公开页 → 找新公告 → 抽截止日 → 记日志 → 生成日历和网页。

    python 02-20Days-Challenge/src/probe.py

由 GitHub Actions 每 30 分钟调用一次；本机不常驻、不自启。
零第三方依赖，只用 Python 标准库。状态全部落在仓库文件里，
因为每次都是全新 runner，内存里的东西留不到下一轮。

诚实原则：抓不到就是抓不到，解析不出来就记 parse_error，
不模拟、不回放、不填占位值，缺勤轮次不补写。
"""
from __future__ import annotations

import html as html_lib
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from chain import (PUBLICDIR, STATEDIR, append_round, canonical, fingerprint,
                   now, scrub, write_daily_summary)  # noqa: E402

HERE = Path(__file__).resolve().parent
CONFIG = json.loads((HERE / "sources.json").read_text(encoding="utf-8"))

_RE_LINK = re.compile(
    r'href=["\']([^"\']*\d{4,}\.html?)["\'][^>]*>(.*?)</a>(.{0,240})',
    re.I | re.S)
_RE_TAG = re.compile(r"<[^>]+>")
_RE_DATE_ISO = re.compile(r"(20\d{2})-(\d{1,2})-(\d{1,2})")
_RE_DATE_CN = re.compile(r"(?:20\d{2}年)?(\d{1,2})月(\d{1,2})日")
_RE_KEYWORD = re.compile(r"截止|截至|之前|前完成|报名|提交|报送|逾期|deadline|ddl", re.I)


def load_state(name, default):
    path = STATEDIR / name
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return default
    return default


def save_state(name, data):
    STATEDIR.mkdir(parents=True, exist_ok=True)
    (STATEDIR / name).write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def clean(text):
    s = _RE_TAG.sub(" ", text or "")
    s = html_lib.unescape(s)
    return re.sub(r"\s+", " ", s).strip()[:120]


def find_due(title, tail):
    """确定性规则抽截止日期：只看标题和紧随其后的短文本，不用大模型。"""
    blob = title + " " + clean(tail)
    if not _RE_KEYWORD.search(blob):
        return None
    m = _RE_DATE_ISO.search(blob)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        m = _RE_DATE_CN.search(blob)
        if not m:
            return None
        y, mo, d = now().year, int(m.group(1)), int(m.group(2))
    try:
        return "%04d-%02d-%02d" % (y, mo, d)
    except (ValueError, TypeError):
        return None


def fetch(item):
    """返回 (status, ms, bytes, text, error_note)。失败也如实返回。"""
    req = urllib.request.Request(
        item["url"],
        headers={"User-Agent": CONFIG["user_agent"],
                 "Accept-Encoding": "identity"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=CONFIG["timeout_sec"]) as resp:
            raw = resp.read()
            status = resp.status
            enc = item.get("encoding") or "utf-8"
            try:
                text = raw.decode(enc)
            except UnicodeDecodeError:
                text = raw.decode("utf-8", errors="replace")
            return status, int((time.time() - t0) * 1000), len(raw), text, ""
    except urllib.error.HTTPError as e:
        return e.code, int((time.time() - t0) * 1000), 0, "", fingerprint(e)
    except Exception as e:  # 超时、DNS、TLS、证书，全部如实记录
        return 0, int((time.time() - t0) * 1000), 0, "", fingerprint(e)


def parse_links(page_text):
    out = []
    for m in _RE_LINK.finditer(page_text):
        href, title, tail = m.group(1), clean(m.group(2)), m.group(3)
        if not title or len(title) < 4:
            continue
        out.append({"url": href, "title": scrub(title), "tail": tail})
    return out


def render(items, day_rows, summary):
    PUBLICDIR.mkdir(parents=True, exist_ok=True)
    due = [i for i in items if i.get("due") and i["due"] >= now().strftime("%Y-%m-%d")]
    due.sort(key=lambda x: x["due"])
    recent = sorted(items, key=lambda x: x.get("found_at", ""), reverse=True)[:20]

    lines = ["BEGIN:VCALENDAR", "VERSION:2.0",
             "PRODID:-//ICEC P04//Campus Radar//ZH", "CALSCALE:GREGORIAN",
             "METHOD:PUBLISH", "X-WR-CALNAME:校园节点雷达"]
    for i in due:
        d = i["due"].replace("-", "")
        y, mo, dd = int(d[:4]), int(d[4:6]), int(d[6:8])
        nxt = "%04d%02d%02d" % (y, mo, dd + 1) if dd < 28 else d
        uid = fingerprint(i["url"] + i["due"])
        lines += [
            "BEGIN:VEVENT", "UID:" + uid + "@icec-p04",
            "DTSTAMP:" + now().strftime("%Y%m%dT%H%M%S"),
            "DTSTART;VALUE=DATE:" + d, "DTEND;VALUE=DATE:" + nxt,
            "SUMMARY:" + i["title"].replace(",", "\\,").replace(";", "\\;")[:70],
            "DESCRIPTION:来源 " + i["source"] + " · 由校园节点雷达自动收录",
            "BEGIN:VALARM", "TRIGGER:-P1D", "ACTION:DISPLAY",
            "DESCRIPTION:明天截止：" + i["title"][:50], "END:VALARM",
            "END:VEVENT"]
    lines.append("END:VCALENDAR")
    (PUBLICDIR / "calendar.ics").write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")

    def row(i):
        left = i["due"] + " · 截止" if i.get("due") else "未识别到明确截止日"
        return ('<div class="row"><div><div class="t">%s</div>'
                '<div class="meta">%s · %s</div></div>'
                '<div class="tag">%s</div></div>') % (
            html_lib.escape(i["title"][:60]), html_lib.escape(i["source"]),
            html_lib.escape(left), html_lib.escape(left[:12]))

    ticks = []
    for r in day_rows[-48:]:
        cls = "fail" if any(s.get("status") != 200 for s in r.get("sources", [])) else \
              "new" if r.get("new_items", 0) > 0 else ""
        ticks.append('<div class="tick %s"></div>' % cls)

    doc = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>校园节点雷达 · 实时数据</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--line:#e3e6ea;--text:#1c1f23;--muted:#6b7280;--accent:#2563a8;--accent-bg:#eaf2fb;--err:#b03a3a}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.6 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
.page{max-width:980px;margin:0 auto;padding:28px 20px 60px}h1{font-size:22px;font-weight:600;margin:0 0 4px}
.sub{color:var(--muted);font-size:13px;margin:0 0 20px}.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:18px;margin-bottom:14px}
.card h2{font-size:14px;font-weight:600;margin:0 0 14px}.row{display:flex;justify-content:space-between;gap:10px;padding:11px 0;border-top:1px solid var(--line)}
.row:first-of-type{border-top:0;padding-top:0}.t{font-weight:500}.meta{color:var(--muted);font-size:12px;margin-top:2px}
.tag{flex:none;font-size:12px;padding:2px 8px;border-radius:5px;height:fit-content;background:var(--accent-bg);color:var(--accent)}
.grid7{display:grid;grid-template-columns:repeat(48,1fr);gap:2px;margin-top:10px}.tick{height:16px;border-radius:2px;background:#e8eaed}
.tick.new{background:var(--accent)}.tick.fail{background:var(--err)}.foot{color:var(--muted);font-size:12px}
.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:14px}
.metric{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.metric .k{color:var(--muted);font-size:12px}.metric .v{font-size:24px;font-weight:600;margin-top:4px}
</style></head><body><div class="page">
<h1>校园节点雷达</h1>
<p class="sub">真实运行数据 · 由 GitHub Actions 每 30 分钟自动生成 · 最后更新 __STAMP__</p>
<div class="metrics">
<div class="metric"><div class="k">监控公开页</div><div class="v">__NSRC__</div></div>
<div class="metric"><div class="k">累计收录公告</div><div class="v">__NITEM__</div></div>
<div class="metric"><div class="k">进行中的截止项</div><div class="v">__NDUE__</div></div>
<div class="metric"><div class="k">今日已跑轮次</div><div class="v">__NROUND__</div></div>
</div>
<div class="card"><h2>日历里的事项（下载 calendar.ics 导入手机）</h2>__DUE__</div>
<div class="card"><h2>最近收录的公告</h2>__ROWS__</div>
<div class="card"><h2>今日运行心跳</h2><div class="grid7">__TICKS__</div>
<p class="foot">灰 = 无变化　蓝 = 发现新公告　红 = 有源抓取失败。每格一轮，不补写、不回放。</p></div>
<p class="foot">本页数据来自公开网页，日志与校验脚本见仓库 process_logs/ 与 src/verify.py。</p>
</div></body></html>"""
    sub = {
        "__STAMP__": now().strftime("%Y-%m-%d %H:%M"),
        "__NSRC__": str(len(CONFIG["sources"])),
        "__NITEM__": str(len(items)),
        "__NDUE__": str(len(due)),
        "__NROUND__": str(len(day_rows)),
        "__DUE__": "".join(row(i) for i in due[:12]) or '<p class="foot">暂未识别到带明确截止日的公告。</p>',
        "__ROWS__": "".join(row(i) for i in recent[:12]) or '<p class="foot">尚无收录记录。</p>',
        "__TICKS__": "".join(ticks),
    }
    for k, v in sub.items():
        doc = doc.replace(k, v)
    (PUBLICDIR / "index.html").write_text(doc, encoding="utf-8")
    return len(due)


def main():
    stamp = now()
    date = stamp.strftime("%Y-%m-%d")
    seen = load_state("seen.json", {})
    items = load_state("items.json", [])
    baseline = not seen
    known = {i["key"] for i in items}
    new_items = 0
    source_rows = []

    for src in CONFIG["sources"]:
        status, ms, size, text, err = fetch(src)
        found, parse_err = [], ""
        if text:
            try:
                found = parse_links(text)
            except Exception as e:
                parse_err = fingerprint(e)
        for link in found:
            key = src["name"] + "|" + link["url"]
            if key in known:
                continue
            known.add(key)
            due = find_due(link["title"], link["tail"])
            items.append({
                "key": key, "source": src["label"], "title": link["title"],
                "url": link["url"], "due": due,
                "found_at": stamp.strftime("%Y-%m-%d %H:%M"),
                "is_new": not baseline,
            })
            if not baseline:
                new_items += 1
        seen[src["name"]] = [l["url"] for l in found]
        source_rows.append({
            "name": src["name"], "status": status, "ms": ms, "bytes": size,
            "links": len(found), "error": err, "parse_error": parse_err,
        })

    ok = sum(1 for s in source_rows if s["status"] == 200)
    record = {
        "seq": len(load_day_rows(date)) + 1,
        "date": date,
        "minute": stamp.strftime("%H:%M"),
        "planned_minute": stamp.strftime("%H:00") if stamp.minute < 30 else stamp.strftime("%H:30"),
        "baseline": baseline,
        "calls": len(source_rows),
        "ok": ok,
        "failed": len(source_rows) - ok,
        "new_items": new_items,
        "items_total": len(items),
        "sources": source_rows,
    }
    append_round(record)
    save_state("seen.json", seen)
    save_state("items.json", items[-2000:])

    day_rows = load_day_rows(date)
    summary = write_daily_summary(date) if stamp.hour >= 23 and stamp.minute >= 30 else None
    n_due = render(items, day_rows, summary)
    out = {
        "date": date, "minute": record["minute"], "baseline": baseline,
        "ok": ok, "failed": len(source_rows) - ok, "new_items": new_items,
        "items_total": len(items), "due_in_calendar": n_due,
        "hash": record["hash"],
        "merkle_root": (summary or {}).get("merkle_root", ""),
    }
    print(canonical(out))
    return 0


def load_day_rows(date):
    from chain import LOGDIR
    p = LOGDIR / (date + ".jsonl")
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


if __name__ == "__main__":
    raise SystemExit(main())
