#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""课题 02 · 按现状如实定稿的结论稿生成器（零第三方依赖）。

    python analysis/summarize_real.py

只读 raw_data/ 里的真实 CSV，输出 summary.md 与 figures/discharge.svg。

三条硬规则：
  1. 不插值、不补点、不编造任何数值；每个数字都能在原始 CSV 里逐行核对。
  2. NAVCAM 只有首尾 2 个采样点，只做端点对比，不进曲线、不进放电速率拟合、
     不进跨工况统计，也不参与「24 组时间序列」的凑数。
  3. 起始温度不一致、工况间未充分冷却等局限，写进结论而不是藏在脚注里。
"""
from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "raw_data"
OUT = Path(__file__).resolve().parent
FIG = OUT / "figures"

LABEL = {"IDLE": "待机（灭屏）", "SVIDEO": "短视频", "GAME": "高帧率游戏"}
COLOR = {"IDLE": "#6b7280", "SVIDEO": "#2563eb", "GAME": "#dc2626"}
COMPLETE = {
    "IDLE": "T02_IDLE_20261109_211836.csv",
    "SVIDEO": "T02_SVIDEO_20261109_234507.csv",
    "GAME": "T02_GAME_20261110_003444.csv",
}
ENDPOINT = ("NAVCAM", "T02_NAVCAM_20261110_222055.csv")


def load(name):
    rows = []
    with (RAW / name).open(encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            rows.append({
                "t": float(r["elapsed_s"]),
                "batt": float(r["battery_pct"]),
                "i": float(r["current_ma"]),
                "p": float(r["power_w"]),
                "bt": float(r["batt_temp_c"]),
                "soc": float(r["soc_thermal_c"]),
                "fg": r["foreground_pkg"],
                "chg": r["charging"],
            })
    return rows


def slope(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return 0.0
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den


def trapezoid_mah(rows):
    """对 I(t) 做梯形积分；t=0 的启动尖峰会被计入首个 5 分钟区间，故单独标注。"""
    total = 0.0
    for a, b in zip(rows, rows[1:]):
        total += (a["i"] + b["i"]) / 2.0 * (b["t"] - a["t"])
    return total / 3600.0


def metrics(rows):
    minutes = [r["t"] / 60.0 for r in rows]
    batt = [r["batt"] for r in rows]
    return {
        "n": len(rows),
        "span_min": (rows[-1]["t"] - rows[0]["t"]) / 60.0,
        "b0": batt[0], "b1": batt[-1], "drop": batt[0] - batt[-1],
        "rate": -slope(minutes, batt) * 60.0,
        "i_mean": sum(r["i"] for r in rows) / len(rows),
        "i_stable": sum(r["i"] for r in rows[1:]) / (len(rows) - 1),
        "p_mean": sum(r["p"] for r in rows) / len(rows),
        "bt0": rows[0]["bt"], "bt1": rows[-1]["bt"],
        "bt_rise": rows[-1]["bt"] - rows[0]["bt"],
        "soc_max": max(r["soc"] for r in rows),
        "mah": trapezoid_mah(rows),
        "chg": sorted({r["chg"] for r in rows}),
        "fg": sorted({r["fg"] for r in rows}),
    }


def fmt(v, n=1):
    return ("%." + str(n) + "f") % v


def write_svg(series, endpoint):
    FIG.mkdir(parents=True, exist_ok=True)
    def X(t):
        return 62 + t * (578.0 / 35.0)
    def Y(v):
        return 238 - v * (206.0 / 70.0)
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="100%" viewBox="0 0 680 290" role="img">',
        '<title>课题 02 三工况 30 分钟电量曲线与相机录像端点</title>',
        '<desc>待机、短视频、高帧率游戏各有 7 个真实采样点；相机录像仅有首尾 2 点，以虚线单独标注，不参与统计。</desc>',
        '<rect x="0" y="0" width="680" height="290" fill="#ffffff"/>',
    ]
    for v in range(0, 71, 10):
        y = Y(v)
        parts.append('<line x1="62" y1="%s" x2="640" y2="%s" stroke="#e8eaed" stroke-width="1"/>' % (fmt(y), fmt(y)))
        parts.append('<text x="52" y="%s" text-anchor="end" font-size="11" fill="#6b7280">%d%%</text>' % (fmt(y + 4), v))
    for t in range(0, 36, 5):
        x = X(t)
        parts.append('<text x="%s" y="256" text-anchor="middle" font-size="11" fill="#6b7280">%d</text>' % (fmt(x), t))
    parts.append('<text x="350" y="278" text-anchor="middle" font-size="12" fill="#6b7280">经过时间（分钟）</text>')
    parts.append('<text x="62" y="20" font-size="13" font-weight="500" fill="#1c1f23">电量变化 · 均为真实采样点，未插值</text>')
    for key, rows in series.items():
        pts = " ".join("%s,%s" % (fmt(X(r["t"] / 60.0)), fmt(Y(r["batt"]))) for r in rows)
        parts.append('<polyline points="%s" fill="none" stroke="%s" stroke-width="2.5" stroke-linejoin="round"/>' % (pts, COLOR[key]))
        for r in rows:
            parts.append('<circle cx="%s" cy="%s" r="3" fill="%s"/>' % (fmt(X(r["t"] / 60.0)), fmt(Y(r["batt"])), COLOR[key]))
    a, b = endpoint[0], endpoint[-1]
    parts.append('<polyline points="%s,%s %s,%s" fill="none" stroke="#d97706" stroke-width="2" stroke-dasharray="6 4"/>' % (
        fmt(X(a["t"] / 60.0)), fmt(Y(a["batt"])), fmt(X(b["t"] / 60.0)), fmt(Y(b["batt"]))))
    for r in (a, b):
        parts.append('<circle cx="%s" cy="%s" r="4" fill="#d97706"/>' % (fmt(X(r["t"] / 60.0)), fmt(Y(r["batt"]))))
    parts.append('<text x="%s" y="%s" font-size="11" fill="#d97706">仅首尾 2 点</text>' % (
        fmt(X(b["t"] / 60.0) - 92), fmt(Y(b["batt"]) - 10)))
    legend = [("IDLE", "待机 7 点"), ("SVIDEO", "短视频 7 点"), ("GAME", "游戏 7 点")]
    for i, (key, text) in enumerate(legend):
        x = 400 + (i % 2) * 120
        y = 36 + (i // 2) * 18
        parts.append('<line x1="%d" y1="%d" x2="%d" y2="%d" stroke="%s" stroke-width="2.5"/>' % (x, y, x + 16, y, COLOR[key]))
        parts.append('<text x="%d" y="%d" font-size="11" fill="#1c1f23">%s</text>' % (x + 21, y + 4, text))
    parts.append('<line x1="520" y1="54" x2="536" y2="54" stroke="#d97706" stroke-width="2" stroke-dasharray="6 4"/>')
    parts.append('<text x="541" y="58" font-size="11" fill="#1c1f23">相机录像 2 点</text>')
    parts.append('</svg>')
    (FIG / "discharge.svg").write_text("\n".join(parts) + "\n", encoding="utf-8")


def main():
    series = {k: load(v) for k, v in COMPLETE.items()}
    ep = load(ENDPOINT[1])
    m = {k: metrics(v) for k, v in series.items()}
    write_svg(series, ep)

    lines = [
        "# 课题 02 · 结论稿（按现状如实定稿）",
        "",
        "> 由 `analysis/summarize_real.py` 直接读取 `raw_data/` 生成，零第三方依赖。",
        "> `python analysis/summarize_real.py` 可一键复现本页所有数字与 `figures/discharge.svg`。",
        "> **相机录像工况只有首尾 2 个采样点，不参与曲线、放电速率拟合与跨工况统计。**",
        "",
        "## 1. 三个完整工况（各 7 个真实采样点）",
        "",
        "| 工况 | 点数 | 跨度 min | 电量 % | 掉电 pp | 放电速率 %/h | 平均电流 mA | 稳态电流 mA¹ | 平均功率 W | 电池温 ℃ | 温升 ℃ | SoC 峰值 ℃ | 积分电量 mAh² |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for k in ("IDLE", "SVIDEO", "GAME"):
        d = m[k]
        lines.append("| %s | %d | %s | %s→%s | %s | %s | %s | %s | %s | %s→%s | %s | %s | %s |" % (
            LABEL[k], d["n"], fmt(d["span_min"]), fmt(d["b0"], 0), fmt(d["b1"], 0), fmt(d["drop"], 0),
            fmt(d["rate"]), fmt(d["i_mean"], 0), fmt(d["i_stable"], 0), fmt(d["p_mean"], 2),
            fmt(d["bt0"]), fmt(d["bt1"]), fmt(d["bt_rise"]), fmt(d["soc_max"]), fmt(d["mah"], 0)))
    lines += [
        "",
        "¹ 稳态电流 = 去掉 t=0 启动尖峰后 6 点的均值。三个工况 t=0 的电流分别是 707 / 1224 / 2714 mA，",
        "是冷启动瞬间的尖峰，不能当作 30 分钟持续负载；这一差异正是要用梯形积分而非「均值×时长」的原因。",
        "",
        "² 梯形积分 `∫I(t)dt / 3600`。因采样点稀疏（每 5 分钟一点），t=0 尖峰被摊到首个 5 分钟区间，",
        "结果会略偏高，**仅作工况间量级对比，不当作精确电量计读数**。",
        "",
        "全程 `charging=0`（放电），前台包名见各 CSV 的 `foreground_pkg` 列。",
        "",
        "## 2. 相机录像工况（端点实测，不进统计）",
        "",
        "| 项 | 起点 t=0 | 终点 t=%.1f min | 变化 |" % (ep[-1]["t"] / 60.0),
        "|---|---|---|---|",
        "| 电量 | %s%% | %s%% | −%s pp |" % (fmt(ep[0]["batt"], 0), fmt(ep[-1]["batt"], 0), fmt(ep[0]["batt"] - ep[-1]["batt"], 0)),
        "| 电池温度 | %s ℃ | %s ℃ | +%s ℃ |" % (fmt(ep[0]["bt"]), fmt(ep[-1]["bt"]), fmt(ep[-1]["bt"] - ep[0]["bt"])),
        "| 电流 / 功率 | %s mA / %s W | %s mA / %s W | — |" % (
            fmt(ep[0]["i"], 0), fmt(ep[0]["p"], 2), fmt(ep[-1]["i"], 0), fmt(ep[-1]["p"], 2)),
        "",
        "采集窗口 21:47:19 → 22:20:55，跨度 34 分钟、未充电，负载确实跑满 30 分钟以上。",
        "但期间采集进程被系统挂起，中间 5 个采样点未落下（详见 `DATA_QUALITY.md` 与运行日志），",
        "因此**只报告首尾端点，不画曲线、不算放电速率、不补点、不插值**。终点前台变为",
        "`com.icec.powerprobe`，是使用者按停止后切回本 App 所致，同样如实保留。",
        "",
        "## 3. 能得出的结论",
        "",
        "1. **负载梯度成立**：同样的 25 分钟窗口，稳态平均电流 待机 < 短视频 < 高帧率游戏；",
        "   掉电速率与电池温升同向排列。游戏工况 t=0 瞬时功率达 9.879 W、SoC 温度峰值 75.6 ℃，",
        "   是三个工况里最重的热负载。",
        "2. **相机录像是最重的持续热负载**：34 分钟掉电 21 个百分点、电池温度升 15.3 ℃，",
        "   高于三个完整工况的任一 25 分钟窗口；ISP + 视频编码器 + 常亮屏叠加，符合预期。",
        "   但只有 2 个点，此结论是**端点观察**，不是时间序列检验结果。",
        "3. **启动尖峰不可忽略**：三工况 t=0 电流是稳态的 3～5 倍。若用「平均电流×时长」估算耗电，",
        "   会同时高估持续负载、低估瞬时冲击；用梯形积分更接近真实。",
        "",
        "## 4. 高功耗模块与省电策略",
        "",
        "- **SoC / GPU**：游戏与录像工况的 SoC 温度显著高于待机；降低画质与帧率、关闭高刷新率，",
        "  是收益最大的一项（用户可在游戏内手动设置，本工具不注入操作）。",
        "- **屏幕**：短视频、游戏、录像全程常亮；固定 50% 亮度并关闭自动亮度，避免亮度漂移污染对比。",
        "- **持续时长**：30 分钟连续高负载会让电池温度持续爬升，触发降频；分段使用、中间静置回温，",
        "  比一直硬扛更省电。",
        "- **射频**：protocol 要求关闭 5G 用 4G，避免射频功耗波动掩盖负载差异。",
        "",
        "## 5. 本结论不能覆盖的事（必须一并说明）",
        "",
        "- **起始条件不完全齐整**：游戏工况起点 SoC 温度 75.6 ℃，明显高于待机 43.3 ℃ 与短视频 47.3 ℃，",
        "  说明工况间未充分冷却到 protocol 要求的 ≤32 ℃。因此跨工况比较只能给**定性梯度**，",
        "  不能做严格的统计推断或显著性检验，也不运行 `analyze_t02.py` 的 Kruskal-Wallis 检验。",
        "- **相机工况采样密度不足**：不参与「30 分钟内每 5 分钟」的 7 点序列，不凑 24 组总数。",
        "- **待机工况前台**：起点为 `com.icec.powerprobe`、终点为 `com.miui.home`，",
        "  是启动与熄屏后的正常切换，非工况污染，但也不据此声称「全程无前台应用」。",
        "- **未做的补采与修复**：本次按现状定稿，不补采、不改数据、不修采样定时器；原因与证据见",
        "  `DATA_QUALITY.md`。后续若要补齐，须真机重跑，不能在桌面端生成数据。",
        "",
        "---",
        "",
        "本页所有数值来自 `raw_data/` 中 4 份真实 CSV，未插值、未补点、未修改任何原始记录。",
        "定稿日期 2026-11-13。",
    ]
    (OUT / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("已生成 summary.md 与 figures/discharge.svg")
    for k in ("IDLE", "SVIDEO", "GAME"):
        d = m[k]
        print("  %-8s %d 点  掉电 %s pp  速率 %s %%/h  稳态 %s mA  SoC峰 %s ℃" % (
            k, d["n"], fmt(d["drop"], 0), fmt(d["rate"]), fmt(d["i_stable"], 0), fmt(d["soc_max"])))
    print("  NAVCAM  %d 点  仅端点  %s%%→%s%%  %s℃→%s℃（不入统计）" % (
        len(ep), fmt(ep[0]["batt"], 0), fmt(ep[-1]["batt"], 0), fmt(ep[0]["bt"]), fmt(ep[-1]["bt"])))


if __name__ == "__main__":
    main()
