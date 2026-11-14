"""整学期一次性展开：只给真正有课的那一天那一大节排提醒。

三份产物同源，改课表重跑一次即可全部更新：
  schedule.json      机器用（run.py 查表）
  public/index.html  人用（双击就能看今天/本周课表）
  public/prebell.ics 手机用（导入日历后由手机本地提醒，完全不依赖服务器）

周次从 timetable.json 的 weeks_raw 现场解析，解析不了的片段直接报错停下，
绝不悄悄漏掉一周——漏一周就是漏一节课。
"""
import argparse
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prebell import model

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parents[1]
PUBLIC = PROJECT_ROOT / "public"


def load_json(name):
    return json.loads((HERE / name).read_text(encoding="utf-8"))


def build(timetable=None, config=None):
    t = timetable or load_json("timetable.json")
    cfg = config or load_json("config.example.json")
    periods = {p["id"]: p for p in t["periods"]}
    anchor = t["anchor"]["first_monday"]
    term_weeks = int(t["meta"]["term_weeks"])

    cells = []
    for cell in t["cells"]:
        courses = []
        for c in cell["courses"]:
            courses.append(dict(
                c,
                weeks=model.parse_weeks(c.get("weeks_raw")),
                form=c.get("form") or model.parse_form(c.get("weeks_raw")),
            ))
        cells.append(dict(cell, courses=courses))

    by_key = {}
    day = date.fromisoformat(cfg["plan_from"])
    end = date.fromisoformat(cfg["plan_to"])
    while day <= end:
        w = model.week_index(day, anchor)
        dow = day.isoweekday()
        if 1 <= w <= term_weeks and dow <= 5:
            for cell in cells:
                if cell["weekday"] != dow:
                    continue
                hits = [c for c in cell["courses"] if w in c["weeks"]]
                if not hits:
                    continue
                pid = cell["period"]
                p = periods[pid]
                day_str = day.isoformat()
                key = model.make_key(day_str, pid)
                if key not in by_key:
                    class_end = p["end"]
                    if any("第1节-第4节" in (c.get("span") or "") for c in hits):
                        class_end = periods["P2"]["end"]
                    by_key[key] = {
                        "key": key,
                        "date": day_str,
                        "week": w,
                        "weekday": dow,
                        "period": pid,
                        "period_label": p["label"],
                        "class_start": p["start"],
                        "class_end": class_end,
                        "remind_at": p["remind_at"],
                        "fire_utc": model.utc_datetime(day_str, p["remind_at"]).strftime("%H:%M"),
                        "courses": [],
                        "span_note": next((c["span"] for c in hits if c.get("span")), None),
                    }
                for c in hits:
                    by_key[key]["courses"].append({
                        "name": c.get("name"),
                        "room": c.get("room"),
                        "form": c.get("form"),
                        "weeks_raw": c.get("weeks_raw"),
                    })
        day += timedelta(days=1)

    entries = sorted(by_key.values(), key=lambda e: (e["date"], e["class_start"]))
    return {
        "generated_at": datetime.now(model.CST).isoformat(timespec="seconds"),
        "plan_from": cfg["plan_from"],
        "plan_to": cfg["plan_to"],
        "anchor": t["anchor"],
        "anchor_verified": bool(t["anchor"].get("verified")),
        "proofread": bool(t["meta"].get("proofread")),
        "minutes_before": cfg["minutes_before"],
        "periods": t["periods"],
        "total_entries": len(entries),
        "entries": entries,
        "limits_note": "第 1 周周一为估算值；不支持单双周与调休。课程名/周次/教室来自截图逐格转录，教师姓名不参与展示。",
    }


def esc_ics(text):
    s = str(text or "").replace("\\", "\\\\").replace(";", "\\;")
    return s.replace(",", "\\,").replace("\r", "").replace("\n", "\\n")


def fold_ics(line):
    """RFC 5545 按 UTF-8 字节折行，不切断中文字符。"""
    out, cur, n = [], "", 0
    for ch in line:
        k = len(ch.encode("utf-8"))
        if n + k > 73:
            out.append(cur)
            cur, n = " " + ch, 1 + k
        else:
            cur, n = cur + ch, n + k
    out.append(cur)
    return "\r\n".join(out)


def render_ics(data):
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0",
        "PRODID:-//PreBell//Course Schedule//CN",
        "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
        "X-WR-CALNAME:课表 2026-2027 第1学期",
        "X-WR-TIMEZONE:Asia/Shanghai",
    ]
    stamp = datetime.now(model.UTC).strftime("%Y%m%dT%H%M%SZ")
    for e in data["entries"]:
        d = e["date"].replace("-", "")
        start = e["class_start"].replace(":", "") + "00"
        end = e["class_end"].replace(":", "") + "00"
        names = " / ".join(c["name"] for c in e["courses"] if c.get("name"))
        rooms = " / ".join(sorted({c["room"] for c in e["courses"] if c.get("room")}))
        desc = "第%d周 · %s · %s" % (
            e["week"], e["period_label"],
            "; ".join(c.get("weeks_raw") or "" for c in e["courses"]))
        lines += [
            "BEGIN:VEVENT",
            "UID:prebell-%s@icec" % e["key"],
            "DTSTAMP:%s" % stamp,
            "DTSTART:%sT%s" % (d, start),
            "DTEND:%sT%s" % (d, end),
            "SUMMARY:%s" % esc_ics(names or "课程"),
            "LOCATION:%s" % esc_ics(rooms),
            "DESCRIPTION:%s" % esc_ics(desc),
            "BEGIN:VALARM", "TRIGGER:-PT%dM" % int(data["minutes_before"]),
            "ACTION:DISPLAY", "DESCRIPTION:预备铃：该去上课了", "END:VALARM",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold_ics(x) for x in lines) + "\r\n"


HTML_HEAD = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>预备铃 · 我的课表</title>
<style>
*{box-sizing:border-box}
body{margin:0;background:#f6f7f9;color:#1f2328;font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",sans-serif}
.wrap{max-width:1000px;margin:0 auto;padding:24px 18px 60px}
header{display:flex;align-items:baseline;justify-content:space-between;flex-wrap:wrap;gap:8px;margin-bottom:18px}
h1{font-size:22px;margin:0;font-weight:650;letter-spacing:.5px}
.sub{color:#6b7280;font-size:13px}
.card{background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:18px 20px;margin-bottom:16px}
.card h2{font-size:15px;margin:0 0 14px;font-weight:600;color:#374151}
.today{background:#fff;border:1px solid #dbe3f0;border-left:4px solid #2f6feb}
.big{font-size:17px;font-weight:600;margin-bottom:4px}
.badge{display:inline-block;background:#eef4ff;color:#2f6feb;border-radius:5px;padding:1px 8px;font-size:12px;margin-right:8px}
.empty{color:#8b949e;padding:22px 0;text-align:center}
.ev{display:flex;gap:14px;padding:11px 0;border-top:1px solid #eef0f3}
.ev:first-of-type{border-top:0}
.ev .t{width:62px;flex:none;font-weight:600;color:#2f6feb;font-variant-numeric:tabular-nums}
.ev .n{flex:1}
.ev .r{color:#6b7280;font-size:13px;margin-top:2px}
.nav{display:flex;align-items:center;gap:10px;margin-bottom:12px;flex-wrap:wrap}
button{font:inherit;border:1px solid #d0d7de;background:#fff;border-radius:7px;padding:5px 12px;cursor:pointer;color:#24292f}
button:hover{background:#f3f4f6}
.weeklabel{font-weight:600;min-width:130px;text-align:center}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{border:1px solid #e5e7eb;padding:8px 7px;vertical-align:top;text-align:left}
th{background:#fafbfc;font-weight:600;color:#374151}
td.t{width:74px;color:#6b7280;font-size:12px;background:#fafbfc}
.cell{font-weight:500;margin-bottom:2px}
.room{color:#6b7280;font-size:12px}
.none{color:#c9ced6}
.ics{display:inline-block;background:#2f6feb;color:#fff;text-decoration:none;padding:9px 16px;border-radius:8px;font-size:14px;margin-top:6px}
.ics:hover{background:#2559c4}
.warn{background:#fff8e6;border:1px solid #f0dca8;color:#7a5b12;border-radius:9px;padding:12px 15px;font-size:13px;margin-bottom:16px}
footer{color:#8b949e;font-size:12px;margin-top:24px;line-height:1.8}
code{background:#f0f2f5;padding:1px 5px;border-radius:4px;font-size:12px}
@media(max-width:640px){table{font-size:12px}th,td{padding:6px 4px}td.t{width:56px}.wrap{padding:16px 10px 40px}}
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>预备铃 · 我的课表</h1>
  <div class="sub">2026-2027 学年 1 学期 · 2026 智能机器人技术 C3</div>
</header>
"""


HTML_TAIL = """
<div class="card">
  <h2>不装 App，也能准时提醒</h2>
  <div>把整学期课表导入手机自带日历，由手机本地在课前 20 分钟提醒。<b>不需要网络、不需要 GitHub、不需要微信</b>，这是最可靠的一层。</div>
  <a class="ics" href="prebell.ics" download="课表.ics">下载课表 .ics 导入手机日历</a>
  <div class="sub" style="margin-top:10px">微信服务号会在每个上课大节前 20 分钟另推一条「下一节 + 今天全部课程」，作为增强；GitHub 定时任务偶尔排队会晚到，晚到会如实标注。</div>
</div>
<footer>
  课表来自一张截图逐格转录，教师姓名辨读置信度低，故不展示。<br>
  数据来源：<code>src/prebell/timetable.json</code>；本页与 <code>prebell.ics</code> 由 <code>src/prebell/planner.py</code> 一次生成，改课表重跑即可。<br>
  日志与验真：<code>process_logs/</code>、<code>src/prebell/verify.py</code>。全部时间均为北京时间。
</footer>
</div>
<script>
"""


HTML_JS = """
(function(){
  var P = DATA.periods, E = DATA.entries;
  var byDate = {};
  E.forEach(function(e){ (byDate[e.date] = byDate[e.date] || []).push(e); });
  function iso(d){ return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0'); }
  function monday(d){ var x=new Date(d.getFullYear(),d.getMonth(),d.getDate()); x.setDate(x.getDate()-((x.getDay()+6)%7)); return x; }
  function addDays(d,n){ var x=new Date(d); x.setDate(x.getDate()+n); return x; }
  var today = new Date(), cur = monday(today);
  var CN=['周一','周二','周三','周四','周五','周六','周日'];
  var warn = document.getElementById('warn');
  if (!DATA.anchor_verified || !DATA.proofread) {
    warn.innerHTML = '⚠ 课表尚未与教务校历核对：第 1 周按 <b>'+DATA.anchor.first_monday+'</b> 估算。若开学周不对，整张日期表会整体平移——请对照原图确认，确认后把 <code>anchor.verified</code> / <code>meta.proofread</code> 改为 true 并重跑 <code>planner.py</code>。';
  } else { warn.style.display='none'; }

  function renderToday(){
    var key = iso(today), list = (byDate[key]||[]).slice().sort(function(a,b){return a.class_start<b.class_start?-1:1;});
    var w = list.length? list[0].week : Math.floor((today - new Date(DATA.anchor.first_monday+'T00:00:00'))/604800000)+1;
    var d = document.getElementById('todaybox');
    var h = '<div class="big">今天 · '+(today.getMonth()+1)+'月'+today.getDate()+'日 '+CN[(today.getDay()+6)%7]+' · 第 '+w+' 周</div>';
    if (!list.length) h += '<div class="empty">今天没课，好好休息。</div>';
    else list.forEach(function(e){
      e.courses.forEach(function(c,i){
        h += '<div class="ev"><div class="t">'+(i===0?e.class_start:'')+'</div><div class="n"><span class="badge">'+e.period_label+'</span>'+(c.name||'课程待核对')+
             '<div class="r">'+(c.room||'教室待核对')+(c.form?' · '+c.form:'')+' · '+e.class_start+'–'+e.class_end+'</div></div></div>';
      });
    });
    d.innerHTML = h;
  }

  function renderWeek(){
    var label = document.getElementById('weeklabel');
    label.textContent = (cur.getMonth()+1)+'/'+cur.getDate()+' – '+(addDays(cur,4).getMonth()+1)+'/'+addDays(cur,4).getDate();
    var h = '<table><tr><th>时间</th>';
    for (var i=0;i<5;i++){ var d=addDays(cur,i); h += '<th>'+CN[i]+'<br><span style="font-weight:400;color:#8b949e">'+(d.getMonth()+1)+'/'+d.getDate()+'</span></th>'; }
    h += '</tr>';
    P.forEach(function(p){
      h += '<tr><td class="t">'+p.start+'<br>'+p.end+'</td>';
      for (var i=0;i<5;i++){
        var key=iso(addDays(cur,i));
        var e=(byDate[key]||[]).filter(function(x){return x.period===p.id;})[0];
        if(!e){ h += '<td><span class="none">—</span></td>'; continue; }
        h += '<td>';
        e.courses.forEach(function(c){
          h += '<div class="cell">'+(c.name||'课程待核对')+'</div><div class="room">'+(c.room||'')+'</div>';
        });
        h += '</td>';
      }
      h += '</tr>';
    });
    document.getElementById('weektable').innerHTML = h+'</table>';
  }

  document.getElementById('prev').onclick=function(){cur=addDays(cur,-7);renderWeek();};
  document.getElementById('next').onclick=function(){cur=addDays(cur,7);renderWeek();};
  document.getElementById('now').onclick=function(){cur=monday(new Date());renderWeek();};
  renderToday(); renderWeek();
})();
"""


def render_html(data):
    payload = {
        "periods": data["periods"],
        "entries": data["entries"],
        "anchor": data["anchor"],
        "anchor_verified": data["anchor_verified"],
        "proofread": data["proofread"],
    }
    js = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    body = (
        '<div class="warn" id="warn"></div>\n'
        '<div class="card today"><h2>今天</h2><div id="todaybox"></div></div>\n'
        '<div class="card"><h2>本周课表</h2>'
        '<div class="nav"><button id="prev">← 上一周</button>'
        '<span class="weeklabel" id="weeklabel"></span>'
        '<button id="next">下一周 →</button><button id="now">回到本周</button></div>'
        '<div id="weektable"></div></div>\n'
    )
    return (HTML_HEAD + body + HTML_TAIL
            + "const DATA = " + js + ";\n" + HTML_JS + "</script>\n</body>\n</html>\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description="按周次展开课表，生成推送表 / 网页 / 日历")
    ap.add_argument("--check", action="store_true", help="只校验不写文件")
    ap.add_argument("--no-public", action="store_true", help="不生成网页与 ics")
    args = ap.parse_args(argv)

    data = build()
    keys = [e["key"] for e in data["entries"]]
    assert len(keys) == len(set(keys)), "唯一键重复"
    assert all(e["courses"] for e in data["entries"]), "存在没有课程的提醒（空壳）"
    assert all(c.get("name") for e in data["entries"] for c in e["courses"]), "存在空课程名"
    for e in data["entries"]:
        if not (1 <= e["week"] <= 18):
            raise AssertionError("周次越界: %s" % e["key"])

    if args.check:
        print("校验通过：%d 条真实有课提醒，覆盖 %s ~ %s"
              % (data["total_entries"], data["plan_from"], data["plan_to"]))
        return 0

    (HERE / "schedule.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not args.no_public:
        PUBLIC.mkdir(parents=True, exist_ok=True)
        (PUBLIC / "index.html").write_text(render_html(data), encoding="utf-8")
        (PUBLIC / "prebell.ics").write_text(render_ics(data), encoding="utf-8", newline="")
    print("已生成 %d 条真实提醒" % data["total_entries"])
    print("  schedule.json / public/index.html / public/prebell.ics")
    return 0


if __name__ == "__main__":
    sys.exit(main())
