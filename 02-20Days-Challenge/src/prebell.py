"""PreBell（预备铃）· 单轮入口。

    python src/prebell.py                # 正常一轮（由 GitHub Actions 调用）
    python src/prebell.py --dry-run      # 本机预览：不推送、不写受保护目录
    python src/prebell.py --probe        # 连通性探测（不带 SendKey）
    python src/prebell.py --test-push    # 发一条真实测试消息

做什么：算「今天第几周 / 下一大节 / 本周有没有这节课」→ 查重与节流 →
Server酱官方接口推微信 → 复用 chain.py 追加一条改不动的日志 → 生成 .ics / 网页兜底。

诚实原则（与课题 02、09 一致）：
  - SendKey 只从环境变量读，缺失就记 skipped/no_key，绝不硬编码兜底；
  - 推送失败如实记 HTTP 状态与 8 位错误指纹，绝不写「成功」，也不重发打爆额度；
  - 周次锚点是估算就全链路标注，核对前不当真实提醒；
  - 截图转录里看不清的字段标 unclear，推送文案带「课表未校对」声明；
  - 缺勤轮次不补写，cron 排队延迟如实记录。
"""
from __future__ import annotations

import argparse
import hashlib
import html as html_lib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from chain import (  # noqa: E402
    LOGDIR, STATEDIR, PUBLICDIR, append_round, canonical, fingerprint,
    now, scrub, write_daily_summary,
)
from weeks import parse_cell_courses  # noqa: E402

TIMETABLE = HERE / "timetable.json"
CONFIG = HERE / "config.example.json"
DRY_OUT = HERE / "out"

SENDKEY_ENV = "PREBELL_SENDKEY"
API_HOST = "https://sctapi.ftqq.com"
DAILY_PUSH_LIMIT = 5
PUSH_LEAD_MIN = 20
TIMEOUT_SEC = 10


# ---------------- 基础读写 ----------------

def load_json(path, default=None):
    if not path.exists():
        return default if default is not None else {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default if default is not None else {}


def config():
    c = load_json(CONFIG, {})
    return {
        "sendkey_env": c.get("sendkey_env", SENDKEY_ENV),
        "daily_push_limit": int(c.get("daily_push_limit", DAILY_PUSH_LIMIT)),
        "push_lead_minutes": int(c.get("push_lead_minutes", PUSH_LEAD_MIN)),
        "timeout_sec": int(c.get("timeout_sec", TIMEOUT_SEC)),
    }


def state_dir(dry):
    return DRY_OUT if dry else STATEDIR


def load_state(name, default, dry):
    return load_json(state_dir(dry) / name, default)


def save_state(name, data, dry):
    d = state_dir(dry)
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def last_round_minute(day_str, dry):
    """读上一轮日志的真实分钟，用于算 gap_from_prev_min。

    这是可测的「中间有没有漏跑」，不依赖 GitHub 是否暴露计划时刻。
    """
    if dry:
        return None
    path = LOGDIR / (day_str + ".jsonl")
    if not path.exists():
        return None
    last = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
            if r.get("minute"):
                last = r["minute"]
        except json.JSONDecodeError:
            continue
    return last


def hhmm(dt):
    return dt.strftime("%H:%M")


def minutes_of(s):
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def parse_monday(s):
    return date.fromisoformat(s)


# ---------------- 课表计算 ----------------

def week_index_of(today, monday, term_weeks):
    n = (today - monday).days // 7 + 1
    return n, (1 <= n <= term_weeks)


def target_period(periods, cur_min):
    """返回 (period, phase)。phase: before / in_window / after / none。

    in_window 是 [push_at, start)。GitHub cron 会排队迟到，若已经过了 start，
    记 after 并写 missed，绝不补推。
    """
    for p in periods:
        a = minutes_of(p["push_at"])
        b = minutes_of(p["start"])
        if a <= cur_min < b:
            return p, "in_window"
    upcoming = [p for p in periods if minutes_of(p["start"]) > cur_min]
    if upcoming:
        return upcoming[0], "before"
    passed = [p for p in periods if minutes_of(p["start"]) <= cur_min]
    if passed:
        return passed[-1], "after"
    return None, "none"


def hits_for(cells, weekday, period_id, week_no, term_weeks):
    """找出该星期几、该大节、本周真正要上的课。

    一格多课时同周命中多门 → 记 conflict，全部列出，不静默挑一门。
    """
    hits, conflicts, unknown = [], [], []
    for cell in cells:
        if cell.get("weekday") != weekday:
            continue
        if cell.get("period") != period_id:
            continue
        courses, unk, conf = parse_cell_courses(cell)
        unknown.extend(unk)
        for c in courses:
            if week_no in c.get("weeks", []):
                hits.append((cell, c))
        for w in conf:
            if w == week_no:
                conflicts.append({
                    "cell_id": cell.get("id"),
                    "week": w,
                    "course_ids": [c.get("course_id") for c in courses if w in c.get("weeks", [])],
                })
    return hits, conflicts, unknown


def end_time_of(periods, cell):
    start_idx = int(cell.get("period", 1)) - 1
    span = max(1, int(cell.get("span", 1)))
    end_idx = min(len(periods) - 1, start_idx + span - 1)
    return periods[end_idx]["end"]


# ---------------- 微信推送 ----------------

def sendkey():
    return os.environ.get(SENDKEY_ENV, "").strip()


def push(title, desp, timeout=TIMEOUT_SEC):
    """Server酱 Turbo 官方接口：一个 POST form。绝不重试打爆免费额度。

    成功 / 失败都返回结构化结果；任何异常只留 8 位指纹，URL 由 chain.scrub()
    自动抹成 [url]，SendKey 不会落进日志。
    """
    key = sendkey()
    if not key:
        return {"status": "skipped", "http": 0, "reason": "no_key", "attempts": 0, "ms": 0}

    url = API_HOST + "/" + key + ".send"
    data = urllib.parse.urlencode({
        "title": title[:32],
        "desp": desp,
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
            "User-Agent": "ICEC-P04-PreBell/1.0",
        },
    )
    for attempt in range(1, 3):  # 最多 2 次，且仅 5xx/网络才重试
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read().decode("utf-8", "ignore")
                ms = int((time.time() - t0) * 1000)
                try:
                    code = json.loads(body).get("code", -1)
                except json.JSONDecodeError:
                    code = -1
                ok = (r.status == 200 and code == 0)
                return {
                    "status": "ok" if ok else "failed",
                    "http": r.status, "ms": ms, "biz_code": code,
                    "attempts": attempt,
                    "fingerprint": "" if ok else fingerprint(body[:200]),
                }
        except urllib.error.HTTPError as e:
            fp = fingerprint(e)
            if e.code >= 500 and attempt == 1:
                time.sleep(2)
                continue
            return {"status": "failed", "http": e.code, "ms": int((time.time() - t0) * 1000),
                    "fingerprint": fp, "attempts": attempt}
        except Exception as e:  # DNS / TLS / 超时 → HTTP 0，如实记
            return {"status": "failed", "http": 0, "ms": int((time.time() - t0) * 1000),
                    "fingerprint": fingerprint(e), "attempts": attempt}
    return {"status": "failed", "http": 0, "fingerprint": "retry_exhausted", "attempts": 2, "ms": 0}


def probe_channel(timeout=TIMEOUT_SEC):
    """不带 SendKey 的最小连通性探测。只判断 DNS/TCP/TLS，不假装能推。"""
    req = urllib.request.Request(API_HOST + "/", headers={"User-Agent": "ICEC-P04-PreBell/1.0"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return {"status": "reachable", "http": r.status, "ms": int((time.time() - t0) * 1000),
                    "fingerprint": ""}
    except urllib.error.HTTPError as e:
        return {"status": "reachable", "http": e.code, "ms": int((time.time() - t0) * 1000),
                "fingerprint": fingerprint(e)}
    except Exception as e:
        return {"status": "failed", "http": 0, "ms": int((time.time() - t0) * 1000),
                "fingerprint": fingerprint(e)}


# ---------------- 消息文案 ----------------

def build_message(t, period, hits, week_no, cell, conflicts):
    anchor = t["anchor"]
    verified = bool(anchor.get("verified"))
    reviewed = bool(t["meta"].get("proofread"))
    p = period
    lines = [
        "### 下一大节 · %s–%s（%s）" % (p["start"], p["end"], p["sessions"]),
        "",
    ]
    for _, c in hits:
        lines.append("**%s**" % c.get("name", "（课程名待核对）"))
        lines.append("- 教室：%s" % (c.get("room") or "〈截图看不清，待核对〉"))
        lines.append("- 教师：%s" % (c.get("teacher") or "〈截图看不清，待核对〉"))
        lines.append("- 周次原文：`%s`" % (c.get("weeks_raw") or "〈未辨认〉"))
        lines.append("- 教学形式：%s" % (c.get("form") or "〈未辨认〉"))
        if c.get("unclear"):
            lines.append("- 待核对字段：%s" % "、".join(c["unclear"]))
        lines.append("")
    if cell and cell.get("merged"):
        lines.append("> 该格为跨行合并单元格，连上 4 节，按一条连续日程处理。")
        lines.append("")
    lines.append("- 本周：**%s第 %d 周**" % ("估算" if not verified else "", week_no))
    if conflicts:
        lines.append("- ⚠ 同格有 %d 门课周次重叠，截图无法判定，已列入待核对清单。" % len(conflicts))
    lines.append("")
    if not verified:
        lines.append("> ⚠ %s" % anchor["display_wording"])
    if not reviewed:
        lines.append("> ⚠ 课表由一张截图人工转录，**尚未逐格校对**；请以原课表为准。")
    lines.append("> 本条由 GitHub Actions 自动推送；没收到可看网页或导入 `calendar.ics` 兜底。")
    title = "预备铃｜%s %s有课" % (p["start"], p["label"])
    return title, "\n".join(lines)


# ---------------- 兜底产物 ----------------

def ics_escape(s):
    return str(s or "").replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")


def build_ics(t, out_dir):
    periods = t["periods"]
    anchor = parse_monday(t["anchor"]["first_monday"])
    term_weeks = int(t["meta"].get("term_weeks", 18))
    verified = bool(t["anchor"].get("verified"))
    note = t["anchor"]["display_wording"] if not verified else "学期周次锚点已核对"

    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//ICEC P04//PreBell//ZH",
        "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
        "X-WR-CALNAME:预备铃 · 课表%s" % ("" if verified else "（第1周周一为估算，未核对）"),
        "BEGIN:VTIMEZONE", "TZID:Asia/Shanghai", "BEGIN:STANDARD",
        "DTSTART:19700101T000000", "TZOFFSETFROM:+0800", "TZOFFSETTO:+0800",
        "TZNAME:CST", "END:STANDARD", "END:VTIMEZONE",
    ]
    n = 0
    for cell in t["cells"]:
        courses, _, _ = parse_cell_courses(cell)
        wd = int(cell["weekday"])
        pid = int(cell["period"])
        p = periods[pid - 1]
        end = end_time_of(periods, cell)
        for c in courses:
            for w in c.get("weeks", []):
                if not (1 <= w <= term_weeks):
                    continue
                d = anchor + timedelta(weeks=w - 1, days=wd - 1)
                ds = d.strftime("%Y%m%d")
                uid_seed = "%s-%s-%s-%s" % (w, wd, pid, c.get("course_id", ""))
                uid = hashlib.sha256(uid_seed.encode()).hexdigest()[:12]
                desc = "课程：%s\n教室：%s\n教师：%s\n周次原文：%s\n教学形式：%s\n第%d周 %s\n%s" % (
                    c.get("name", ""), c.get("room") or "待核对", c.get("teacher") or "待核对",
                    c.get("weeks_raw") or "未辨认", c.get("form") or "未辨认",
                    w, ["一", "二", "三", "四", "五"][wd - 1] if wd <= 5 else "?", note,
                )
                lines += [
                    "BEGIN:VEVENT", "UID:prebell-%s@icec-p04" % uid,
                    "DTSTAMP:" + now().strftime("%Y%m%dT%H%M%SZ"),
                    "DTSTART;TZID=Asia/Shanghai:%sT%s00" % (ds, p["start"].replace(":", "")),
                    "DTEND;TZID=Asia/Shanghai:%sT%s00" % (ds, end.replace(":", "")),
                    "SUMMARY:" + ics_escape("预备铃 · %s @%s" % (c.get("name", ""), c.get("room") or "教室待核对")),
                    "LOCATION:" + ics_escape(c.get("room") or "待核对"),
                    "DESCRIPTION:" + ics_escape(desc),
                    "CATEGORIES:" + ("VERIFIED" if verified else "ESTIMATED-ANCHOR"),
                    "TRANSP:OPAQUE",
                    "BEGIN:VALARM", "ACTION:DISPLAY", "TRIGGER:-PT20M",
                    "DESCRIPTION:" + ics_escape("预备铃：20 分钟后 %s" % c.get("name", "")),
                    "END:VALARM", "END:VEVENT",
                ]
                n += 1
    lines.append("END:VCALENDAR")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "calendar.ics").write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
    return n


def build_html(t, out_dir, channel, day_str, week_no, phase, push_result):
    anchor = t["anchor"]
    verified = bool(anchor.get("verified"))
    reviewed = bool(t["meta"].get("proofread"))
    ch = channel or {}
    ch_bad = ch.get("status") == "failed" or (push_result or {}).get("status") == "failed"
    fp = (push_result or {}).get("fingerprint") or ch.get("fingerprint") or ""

    banner = []
    if not verified:
        banner.append("⚠ %s" % anchor["display_wording"])
    if not reviewed:
        banner.append("⚠ 课表由一张截图人工转录，尚未逐格校对；请以原课表为准。")
    if ch_bad:
        banner.append("⚠ 微信推送当前不可用（错误指纹 %s），已降级为日历订阅。" % (fp or "unknown"))

    periods = t["periods"]
    weekdays = ["一", "二", "三", "四", "五"]
    rows = []
    for p in periods:
        cells_html = []
        for wd in range(1, 6):
            found = []
            for cell in t["cells"]:
                if cell.get("weekday") != wd or cell.get("period") != p["id"]:
                    continue
                courses, _, _ = parse_cell_courses(cell)
                for c in courses:
                    if week_no in c.get("weeks", []):
                        found.append(html_lib.escape(c.get("name") or "待核对") +
                                     "<span class='room'> @ " +
                                     html_lib.escape(c.get("room") or "教室待核对") + "</span>")
            cells_html.append("<td>%s</td>" % ("<br>".join(found) if found else "<span class='empty'>—</span>"))
        rows.append("<tr><th>%s<br><span>%s–%s</span></th>%s</tr>" % (
            html_lib.escape(p["label"]), p["start"], p["end"], "".join(cells_html)))

    unclear = []
    for cell in t["cells"]:
        for u in cell.get("unclear", []):
            unclear.append("<li>%s：%s</li>" % (html_lib.escape(cell["id"]), html_lib.escape(u)))

    doc = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>预备铃 · 本周课表</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--line:#e3e6ea;--text:#1c1f23;--muted:#6b7280;--accent:#2563a8;--accent-bg:#eaf2fb;--warn:#9a5b00;--warn-bg:#fff5e2}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.6 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
.page{max-width:980px;margin:0 auto;padding:28px 20px 60px}h1{font-size:22px;font-weight:600;margin:0 0 4px}
.sub{color:var(--muted);font-size:13px;margin:0 0 18px}.banner{background:var(--warn-bg);border:1px solid #f0d9a8;color:var(--warn);padding:10px 14px;border-radius:8px;font-size:13px;margin-bottom:16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:18px;margin-bottom:14px}
.card h2{font-size:14px;font-weight:600;margin:0 0 12px}table{width:100%;border-collapse:collapse;font-size:13px}
th,td{border:1px solid var(--line);padding:9px 8px;text-align:left;vertical-align:top}thead th{background:#f8f9fb}
tbody th{background:#fafbfc;width:120px}tbody th span{color:var(--muted);font-size:12px;font-weight:400}
.room{color:var(--accent);font-size:12px}.empty{color:#c8ccd2}.note{color:var(--muted);font-size:12px}
ul{margin:6px 0;padding-left:20px}li{margin:3px 0}.tag{display:inline-block;background:var(--accent-bg);color:var(--accent);padding:2px 8px;border-radius:5px;font-size:12px}
</style></head><body><div class="page">
<h1>预备铃 · 本周课表</h1>
<p class="sub">课表微信提醒的兜底页 · 数据来自人工转录的 timetable.json · 生成于 __STAMP__</p>
<div class="banner">__BANNER__</div>
<div class="card"><h2>__WEEK__ · 本周有课情况</h2><table>
<thead><tr><th>节次</th>__HEAD__</tr></thead><tbody>__ROWS__</tbody></table>
<p class="note">「—」表示该周这一节没有课。周次由估算锚点推导，核对前请勿当作真实提醒。</p></div>
<div class="card"><h2>本轮状态</h2>
<p>日期 __DAY__ ｜ 阶段 __PHASE__ ｜ 微信推送 __PUSH__</p></div>
<div class="card"><h2>待核对清单（迭代 #1 用）</h2><ul>__UNCLEAR__</ul>
<p class="note">对照 <code>src/timetable-source.png</code> 逐格核对，结果写回 <code>review.changes</code>。</p></div>
<p class="note">微信推送走 Server酱官方公开接口；本程序不读取微信本地数据、不逆向、不登录客户端。</p>
</div></body></html>"""
    head = "".join("<th>星期%s</th>" % w for w in weekdays)
    vals = {
        "__STAMP__": html_lib.escape(day_str),
        "__BANNER__": "<br>".join(html_lib.escape(b) for b in banner) or "已核对，无待办声明",
        "__WEEK__": ("估算" if not verified else "") + "第 %d 周" % week_no,
        "__HEAD__": head,
        "__ROWS__": "".join(rows),
        "__DAY__": html_lib.escape(day_str),
        "__PHASE__": html_lib.escape(phase),
        "__PUSH__": html_lib.escape((push_result or {}).get("status", "skipped")),
        "__UNCLEAR__": "".join(unclear) or "<li>暂无</li>",
    }
    for k, v in vals.items():
        doc = doc.replace(k, v)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.html").write_text(doc, encoding="utf-8")


# ---------------- 主流程 ----------------

def main():
    ap = argparse.ArgumentParser(description="PreBell 单轮入口")
    ap.add_argument("--dry-run", action="store_true", help="本机预览：不推送、不写 process_logs/state/public")
    ap.add_argument("--probe", action="store_true", help="只做连通性探测（不带 SendKey）")
    ap.add_argument("--test-push", action="store_true", help="发一条真实测试消息")
    args = ap.parse_args()
    dry = args.dry_run

    t = load_json(TIMETABLE, {})
    if not t:
        print("timetable.json 缺失或无法解析，已中止")
        return 1
    cfg = config()
    dt = now()
    today = dt.date()
    day_str = today.isoformat()
    minute = hhmm(dt)
    cur_min = minutes_of(minute)
    weekday = dt.isoweekday()  # 1=周一
    monday = parse_monday(t["anchor"]["first_monday"])
    week_no, in_term = week_index_of(today, monday, int(t["meta"].get("term_weeks", 18)))

    channel = load_state("channel.json", {}, dry)
    pushed = load_state("pushed.json", {}, dry)
    day_state = pushed.get(day_str, {"count": 0, "limit": cfg["daily_push_limit"], "periods": {}})
    day_state.setdefault("periods", {})
    day_state["limit"] = cfg["daily_push_limit"]

    out_dir = DRY_OUT if dry else PUBLICDIR
    push_result = {"status": "skipped", "reason": "not_in_window"}
    phase = "weekend"
    period = None
    hits, conflicts, unknown = [], [], []
    reason = ""

    # 连通性探测 / 测试消息是独立事件，不参与课前判断
    if args.probe:
        r = probe_channel(cfg["timeout_sec"])
        channel = {"status": r["status"], "http": r["http"], "fingerprint": r.get("fingerprint", ""),
                   "probed_at": dt.strftime("%Y-%m-%d %H:%M"),
                   "note": "仅探测域名可达性，不代表推送成功；SendKey 不参与本请求"}
        save_state("channel.json", channel, dry)
        out = {"date": day_str, "minute": minute, "event": "connectivity_probe", "result": r,
               "hash": "", "merkle_root": ""}
        print(canonical(out))
        return 0

    if args.test_push:
        title = "预备铃 · 连通性测试"
        desp = ("这是一条真实测试消息，用于确认微信通道可用。\n\n> %s\n> 课表尚未逐格校对，请勿当作真实提醒。"
                % t["anchor"]["display_wording"])
        r = push(title, desp, cfg["timeout_sec"])
        day_state["count"] = int(day_state.get("count", 0)) + (1 if r["status"] != "skipped" else 0)
        day_state["periods"]["test"] = {"at": minute, "status": r["status"], "http": r.get("http", 0)}
        pushed[day_str] = day_state
        save_state("pushed.json", pushed, dry)
        if not dry:
            rec = {"task": "prebell", "event": "test_push", "date": day_str, "minute": minute,
                   "push": r, "channel": channel.get("status", "unknown")}
            append_round(rec)
            s = write_daily_summary(day_str)
            out = {"date": day_str, "minute": minute, "event": "test_push", "push": r,
                   "hash": rec["hash"], "merkle_root": s["merkle_root"]}
        else:
            out = {"date": day_str, "minute": minute, "event": "test_push", "push": r,
                   "hash": "", "merkle_root": ""}
        print(canonical(out))
        return 0

    # 正常一轮
    if weekday > 5:
        phase = "weekend"
        reason = "weekend_heartbeat"
    elif not in_term:
        phase = "out_of_term"
        reason = "week_index_out_of_term"
    else:
        period, phase = target_period(t["periods"], cur_min)
        if phase == "in_window" and period:
            hits, conflicts, unknown = hits_for(
                t["cells"], weekday, period["id"], week_no, int(t["meta"].get("term_weeks", 18)))
            pid = str(period["id"])
            if not hits:
                reason = "no_class_this_week"
            elif pid in day_state["periods"]:
                reason = "already_pushed"
            elif int(day_state.get("count", 0)) >= cfg["daily_push_limit"]:
                reason = "throttled"
                push_result = {"status": "skipped", "reason": "throttled", "http": 0}
            elif channel.get("status") == "failed":
                reason = "channel_failed"
                push_result = {"status": "skipped", "reason": "channel_failed", "http": 0,
                               "fingerprint": channel.get("fingerprint", "")}
            else:
                cell = hits[0][0] if hits else None
                title, desp = build_message(t, period, hits, week_no, cell, conflicts)
                push_result = push(title, desp, cfg["timeout_sec"])
                push_result["period"] = period["id"]
                push_result["title_hash"] = fingerprint(title)
                # 无论成功失败都标记 attempted：绝不因重试打爆免费额度
                day_state["periods"][pid] = {
                    "at": minute, "status": push_result["status"],
                    "http": push_result.get("http", 0),
                    "fingerprint": push_result.get("fingerprint", ""),
                }
                if push_result["status"] != "skipped":
                    day_state["count"] = int(day_state.get("count", 0)) + 1
                pushed[day_str] = day_state
                save_state("pushed.json", pushed, dry)
                reason = "pushed" if push_result["status"] == "ok" else "push_failed"
        elif phase == "after":
            reason = "missed_no_backfill"
        else:
            reason = "waiting_for_window"

    # 兜底产物（正常模式写 public/；dry-run 写 src/out/）
    n_ics = build_ics(t, out_dir)
    build_html(t, out_dir, channel, dt.strftime("%Y-%m-%d %H:%M"), week_no, phase, push_result)

    prev_min = last_round_minute(day_str, dry)
    gap_from_prev = None
    if prev_min:
        try:
            gap_from_prev = cur_min - minutes_of(prev_min)
        except (ValueError, IndexError):
            gap_from_prev = None

    record = {
        "task": "prebell",
        "date": day_str,
        "minute": minute,
        "planned_slot_5m": "%s:%02d" % (dt.strftime("%H"), (dt.minute // 5) * 5),
        "planned_slot_note": "按实际时刻向下对齐到 5 分钟格的近似值；GitHub 不暴露精确计划时刻",
        "actual_minute": minute,
        "offset_in_slot_min": dt.minute % 5,
        "offset_note": "相对 5 分钟格的偏移，不是 cron 排队延迟",
        "gap_from_prev_min": gap_from_prev,
        "gap_note": "与上一轮真实日志的分钟差；大于 5 分钟说明中间有轮次被排队或丢弃",
        "weekday": weekday,
        "week_index": week_no,
        "week_index_estimated": not bool(t["anchor"].get("verified")),
        "in_term": in_term,
        "phase": phase,
        "target_period": period["id"] if period else None,
        "course_hit": [c.get("course_id") for _, c in hits],
        "conflicts": conflicts,
        "parse_unknown": unknown,
        "reason": reason,
        "push": push_result,
        "channel_state": channel.get("status", "unknown"),
        "daily_push_count": int(day_state.get("count", 0)),
        "ics_events": n_ics,
        "timetable_proofread": bool(t["meta"].get("proofread")),
    }

    if not dry:
        append_round(record)
        summary = write_daily_summary(day_str)
        record_out = {"date": day_str, "minute": minute, "phase": phase, "reason": reason,
                      "push": push_result, "hash": record["hash"],
                      "merkle_root": summary["merkle_root"]}
    else:
        record_out = dict(record)
        record_out["hash"] = ""
        record_out["merkle_root"] = ""
        record_out["dry_run"] = True
        record_out["note"] = "本机预览：未推送、未写 process_logs/state/public"
    print(canonical(record_out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
