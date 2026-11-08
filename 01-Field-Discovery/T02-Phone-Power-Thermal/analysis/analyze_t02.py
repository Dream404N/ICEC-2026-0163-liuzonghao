#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
课题 02 · 多工况功耗与热特性分析

输入：raw_data/T02_<SCENARIO>_*.csv（由 PowerProbe 采集，字段定义见 tools/PowerProbe/README.md）
输出：figures/*.png（图表）、summary.csv（逐工况指标）、summary.md（可直接引用的结论稿）

方法说明（都有明确出处，不是自创公式）：
  1. 平均电流/功率：采样点算术均值。样本量小（每工况 6 点），仅作描述性统计。
  2. 总耗电量：对 I(t) 做梯形积分再换算成 mAh，比「平均值 × 时长」更接近真实电量消耗，
     因为工况内的负载不是恒定的（例如相机在录制启动瞬间会出现电流尖峰）。
  3. 工况差异检验：Kruskal-Wallis 非参数检验。样本量 6×4，不满足正态性假设，
     不能用单因素 ANOVA，故选用基于秩的检验。
  4. 放电速率：对电量百分比做最小二乘线性拟合，斜率即 %/h，比首尾两点相减更抗单点抖动。

用法：
    python analyze_t02.py --raw ../raw_data --out .
"""
from __future__ import annotations

import argparse
import glob
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

SCENARIO_LABEL = {
    "IDLE": "Idle (screen off)",
    "SVIDEO": "Short video",
    "NAVCAM": "Nav / Camera",
    "GAME": "High-FPS game",
}
SCENARIO_ORDER = ["IDLE", "SVIDEO", "NAVCAM", "GAME"]

# 深色下也能看的配色，避免依赖主题
COLORS = {
    "IDLE": "#6b7280",
    "SVIDEO": "#2563eb",
    "NAVCAM": "#d97706",
    "GAME": "#dc2626",
}


def load_all(raw_dir: str) -> pd.DataFrame:
    files = sorted(glob.glob(os.path.join(raw_dir, "*.csv")))
    if not files:
        print("[!] %s 下没有 CSV，先跑采集再分析" % raw_dir)
        return pd.DataFrame()

    frames = []
    for f in files:
        try:
            df = pd.read_csv(f)
        except Exception as e:  # 文件被占用或写到一半
            print("[!] 跳过 %s：%s" % (os.path.basename(f), e))
            continue
        if df.empty:
            continue
        df["source_file"] = os.path.basename(f)
        frames.append(df)

    if not frames:
        return pd.DataFrame()

    df = pd.concat(frames, ignore_index=True)

    # 收尾校验行（is_final=1）不参与曲线，但保留用于完整性检查
    for col in ("scenario", "is_final", "elapsed_s", "battery_pct", "current_ma",
                "power_w", "batt_temp_c", "soc_thermal_c", "cpu_load_pct", "cpu_avg_mhz"):
        if col not in df.columns:
            df[col] = np.nan

    df["is_final"] = pd.to_numeric(df["is_final"], errors="coerce").fillna(0).astype(int)
    return df


def completeness(df: pd.DataFrame) -> pd.DataFrame:
    """会话完整性：每个工况的正式采样点数、时长、是否检出充电、root 是否生效。"""
    rows = []
    for sc, g in df.groupby("scenario"):
        pts = g[g["is_final"] == 0]
        tail = g[g["is_final"] == 1]
        span = float(pts["elapsed_s"].max() - pts["elapsed_s"].min()) if len(pts) > 1 else 0.0
        rows.append({
            "scenario": sc,
            "points": int(len(pts)),
            "span_min": round(span / 60.0, 1),
            "dropped": int((pts["battery_pct"].iloc[0] - pts["battery_pct"].iloc[-1])
                           if len(pts) > 1 else 0),
            "charging_detected": bool((pts.get("charging", pd.Series([0])).fillna(0) > 0).any()),
            "root_ok_ratio": round(float(pts.get("root_ok", pd.Series([0])).fillna(0).mean()), 2),
            "tail_elapsed_s": int(tail["elapsed_s"].iloc[0]) if len(tail) else None,
            "foreground": ",".join(sorted(set(pts.get("foreground_pkg", pd.Series(["-"]))
                                                .fillna("-").astype(str).tolist())))[:60],
        })
    return pd.DataFrame(rows)


def metrics(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for sc, g in df.groupby("scenario"):
        pts = g[g["is_final"] == 0].sort_values("elapsed_s")
        if len(pts) < 2:
            continue

        t_s = pts["elapsed_s"].to_numpy(dtype=float)
        cur = pts["current_ma"].to_numpy(dtype=float)
        pwr = pts["power_w"].to_numpy(dtype=float)
        temp = pts["batt_temp_c"].to_numpy(dtype=float)
        soc_t = pts["soc_thermal_c"].to_numpy(dtype=float)
        pct = pts["battery_pct"].to_numpy(dtype=float)

        # 梯形积分：∫|I| dt，单位 mA·s → mAh
        charge_mah = float(np.trapz(np.abs(cur), t_s) / 3600.0)

        # 放电速率：对电量做一次线性拟合，斜率换算成 %/h
        dur_h = (t_s[-1] - t_s[0]) / 3600.0 if t_s[-1] > t_s[0] else np.nan
        if dur_h and dur_h > 0:
            k = np.polyfit(t_s / 3600.0, pct, 1)[0]
            pct_per_h = float(-k)          # 电量下降，取正
        else:
            pct_per_h = np.nan

        rows.append({
            "scenario": sc,
            "label": SCENARIO_LABEL.get(sc, sc),
            "points": int(len(pts)),
            "duration_min": round((t_s[-1] - t_s[0]) / 60.0, 1),
            "start_pct": int(pct[0]),
            "end_pct": int(pct[-1]),
            "drop_pct": int(pct[0] - pct[-1]),
            "cur_mean_ma": round(float(np.mean(cur)), 1),
            "cur_peak_ma": round(float(np.max(np.abs(cur))), 1),
            "cur_std_ma": round(float(np.std(cur, ddof=1)), 1),
            "pwr_mean_w": round(float(np.mean(np.abs(pwr))), 3),
            "pwr_peak_w": round(float(np.max(np.abs(pwr))), 3),
            "charge_mah": round(charge_mah, 1),
            "pct_per_h": round(pct_per_h, 1) if pct_per_h == pct_per_h else np.nan,
            "temp_start_c": round(float(temp[0]), 1),
            "temp_max_c": round(float(np.max(temp)), 1),
            "temp_rise_c": round(float(np.max(temp) - temp[0]), 1),
            "soc_max_c": round(float(np.max(soc_t)), 1) if np.nanmax(soc_t) > 0 else np.nan,
            "cpu_load_mean_pct": round(float(np.mean(pts["cpu_load_pct"].fillna(0))), 1),
            "cpu_mhz_mean": round(float(np.mean(pts["cpu_avg_mhz"].fillna(0))), 0),
        })

    out = pd.DataFrame(rows)
    if not out.empty:
        out["_o"] = out["scenario"].apply(
            lambda s: SCENARIO_ORDER.index(s) if s in SCENARIO_ORDER else 99)
        out = out.sort_values("_o").drop(columns="_o").reset_index(drop=True)
    return out


def stat_test(df: pd.DataFrame) -> str:
    """Kruskal-Wallis：检验四个工况的电流分布是否有显著差异。"""
    groups = []
    for sc in SCENARIO_ORDER:
        g = df[(df["scenario"] == sc) & (df["is_final"] == 0)]["current_ma"].dropna()
        if len(g) >= 2:
            groups.append(g.to_numpy(dtype=float))
    if len(groups) < 2:
        return "样本不足，未做显著性检验。"

    try:
        from scipy.stats import kruskal
        h, p = kruskal(*groups)
        verdict = "存在显著差异" if p < 0.05 else "未检出显著差异"
        return ("Kruskal-Wallis 检验：H = %.3f, p = %.4f（α=0.05），四工况电流分布%s。"
                % (h, p, verdict))
    except ImportError:
        return "未安装 scipy，跳过显著性检验（pip install scipy）。"


def plot_series(df: pd.DataFrame, col: str, ylabel: str, title: str, out_png: Path,
                separate: bool = False) -> None:
    present = [s for s in SCENARIO_ORDER if s in set(df["scenario"].dropna())]
    if not present:
        return

    if separate:
        fig, axes = plt.subplots(2, 2, figsize=(11, 7), sharex=True)
        axes = axes.ravel()
    else:
        fig, ax = plt.subplots(figsize=(9, 4.6))
        axes = None

    for i, sc in enumerate(present):
        g = df[(df["scenario"] == sc) & (df["is_final"] == 0)].sort_values("elapsed_s")
        if g.empty:
            continue
        x = g["elapsed_s"].to_numpy(dtype=float) / 60.0
        y = g[col].to_numpy(dtype=float)
        if separate:
            a = axes[i]
            a.plot(x, y, color=COLORS.get(sc, "#333"), lw=1.8, marker="o", ms=4)
            a.set_title(SCENARIO_LABEL.get(sc, sc), fontsize=11)
            a.grid(alpha=0.25)
            a.set_ylabel(ylabel, fontsize=9)
            if i >= 2:
                a.set_xlabel("Elapsed (min)", fontsize=9)
        else:
            ax.plot(x, y, color=COLORS.get(sc, "#333"), lw=1.8, marker="o",
                    ms=4, label=SCENARIO_LABEL.get(sc, sc))

    if separate:
        fig.suptitle(title, fontsize=13)
    else:
        ax.set_xlabel("Elapsed (min)")
        ax.set_ylabel(ylabel)
        ax.set_title(title)
        ax.grid(alpha=0.25)
        ax.legend(fontsize=9, frameon=False)

    fig.tight_layout()
    fig.savefig(out_png, dpi=160)
    plt.close(fig)


def plot_bars(m: pd.DataFrame, out_png: Path) -> None:
    if m.empty:
        return
    fig, axes = plt.subplots(1, 3, figsize=(12, 4))

    labels = m["label"].tolist()
    colors = [COLORS.get(s, "#333") for s in m["scenario"]]

    axes[0].bar(labels, m["pwr_mean_w"], color=colors)
    axes[0].set_title("Mean power (W)")
    axes[0].set_ylabel("W")

    axes[1].bar(labels, m["temp_rise_c"], color=colors)
    axes[1].set_title("Battery temperature rise (°C)")
    axes[1].set_ylabel("°C")

    axes[2].bar(labels, m["charge_mah"], color=colors)
    axes[2].set_title("Integrated charge over 30 min (mAh)")
    axes[2].set_ylabel("mAh")

    for a in axes:
        a.grid(axis="y", alpha=0.25)
        a.tick_params(axis="x", labelrotation=18, labelsize=9)

    fig.tight_layout()
    fig.savefig(out_png, dpi=160)
    plt.close(fig)


def write_markdown(m: pd.DataFrame, comp: pd.DataFrame, test_line: str, out_md: Path) -> None:
    lines = []
    lines.append("# 课题 02 分析结果\n")
    lines.append("> 由 `analysis/analyze_t02.py` 自动生成，数据源为 `raw_data/*.csv`，未手工修改任何数值。\n")

    lines.append("\n## 会话完整性\n")
    lines.append("| 工况 | 采样点 | 跨度(min) | 掉电(%) | 检出充电 | root 生效比例 | 收尾 elapsed(s) | 前台应用 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for _, r in comp.iterrows():
        lines.append("| %s | %d | %.1f | %d | %s | %.2f | %s | `%s` |" % (
            r["scenario"], r["points"], r["span_min"], r["dropped"],
            "是" if r["charging_detected"] else "否", r["root_ok_ratio"],
            r["tail_elapsed_s"] if r["tail_elapsed_s"] is not None else "-",
            r["foreground"] or "-"))

    lines.append("\n## 逐工况指标\n")
    lines.append("| 工况 | 平均电流(mA) | 峰值电流(mA) | 平均功率(W) | 峰值功率(W) | 积分电量(mAh) | 放电速率(%/h) | 电池温升(℃) | SoC最高(℃) |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for _, r in m.iterrows():
        lines.append("| %s | %.1f | %.1f | %.3f | %.3f | %.1f | %s | %.1f | %s |" % (
            r["label"], r["cur_mean_ma"], r["cur_peak_ma"], r["pwr_mean_w"], r["pwr_peak_w"],
            r["charge_mah"],
            ("%.1f" % r["pct_per_h"]) if r["pct_per_h"] == r["pct_per_h"] else "-",
            r["temp_rise_c"],
            ("%.1f" % r["soc_max_c"]) if r["soc_max_c"] == r["soc_max_c"] else "-"))

    lines.append("\n## 统计检验\n")
    lines.append(test_line + "\n")

    if not m.empty:
        top = m.loc[m["pwr_mean_w"].idxmax()]
        hot = m.loc[m["temp_rise_c"].idxmax()]
        lines.append("\n## 结论\n")
        lines.append("- 平均功率最高：**%s**（%.3f W），是待机工况的约 %.1f 倍。" % (
            top["label"], top["pwr_mean_w"],
            top["pwr_mean_w"] / max(m["pwr_mean_w"].min(), 1e-6)))
        lines.append("- 温升最大：**%s**（+%.1f ℃）。" % (hot["label"], hot["temp_rise_c"]))
        lines.append("- 说明：以上为描述性统计，样本量 6 点/工况，结论用于横向比较工况间的相对差异，不外推到长期续航。")

    out_md.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default="../raw_data")
    ap.add_argument("--out", default=".")
    args = ap.parse_args()

    out_dir = Path(args.out)
    fig_dir = out_dir / "figures"
    fig_dir.mkdir(parents=True, exist_ok=True)

    df = load_all(args.raw)
    if df.empty:
        return 1

    print("[i] 载入 %d 行，%d 个工况" % (len(df), df["scenario"].nunique()))

    comp = completeness(df)
    m = metrics(df)
    test_line = stat_test(df)

    comp.to_csv(out_dir / "completeness.csv", index=False, encoding="utf-8-sig")
    m.to_csv(out_dir / "summary.csv", index=False, encoding="utf-8-sig")

    # 待机工况下电流为负（放电），绘图时统一取绝对值，便于比较「负载强度」
    df_plot = df.copy()
    df_plot["abs_current_ma"] = df_plot["current_ma"].abs()
    df_plot["abs_power_w"] = df_plot["power_w"].abs()

    plot_series(df_plot, "abs_current_ma", "Current (mA)",
                "Discharge current by scenario", fig_dir / "fig1_current.png", separate=True)
    plot_series(df_plot, "batt_temp_c", "Battery temp (°C)",
                "Battery temperature by scenario", fig_dir / "fig2_temperature.png")
    plot_series(df_plot, "battery_pct", "Battery (%)",
                "Battery level by scenario", fig_dir / "fig3_level.png")
    plot_bars(m, fig_dir / "fig4_bars.png")

    write_markdown(m, comp, test_line, out_dir / "summary.md")

    print("[i] 图表 → %s" % fig_dir)
    print("[i] 汇总 → %s/summary.csv, summary.md" % out_dir)
    print("[i] " + test_line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
