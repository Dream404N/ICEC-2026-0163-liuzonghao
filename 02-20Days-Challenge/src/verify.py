"""一键验真：任何人 clone 仓库后运行即可。

    python 02-20Days-Challenge/src/verify.py

检查四件事：
  1. 每一天的哈希链是否连续，改过哪一行会精确报出来；
  2. 每日 summary 里的 Merkle root 是否等于当天所有记录重算的结果；
  3. 哪一天少跑了轮次（只报缺口，不补写）；
  4. 5 分钟轮询的排队情况：格内偏移、与上一轮间隔超过 5 分钟的轮次数。

期望轮次按日期分段，因为 11-17 前后是两套调度：
  - 11-10 ~ 11-16：旧「校园节点雷达」，每 3 小时一轮 = 8 轮/天；
  - 11-17 起：PreBell，工作日 4 个课前窗口共约 12 轮、周末心跳 1 轮。
这些日志由不同任务产生，但共用同一条哈希链；11-10~11-16 不计入 PreBell
自身的「连续 7 天」窗口。
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from chain import LOGDIR, entry_hash, last_hash, load_day, merkle_root, ZERO  # noqa: E402

SWITCH_DATE = "2026-11-17"
RADAR_ROUNDS = 8
PREBELL_WEEKDAY_ROUNDS = 12
PREBELL_WEEKEND_ROUNDS = 1


def expected_rounds(day):
    if day < SWITCH_DATE:
        return RADAR_ROUNDS
    try:
        wd = date.fromisoformat(day).weekday()  # 0=周一
    except ValueError:
        return PREBELL_WEEKDAY_ROUNDS
    return PREBELL_WEEKEND_ROUNDS if wd >= 5 else PREBELL_WEEKDAY_ROUNDS


def main() -> int:
    if not LOGDIR.exists():
        print("尚未产生任何日志：process_logs/ 不存在。")
        return 1
    days = sorted(p.stem for p in LOGDIR.glob("????-??-??.jsonl"))
    if not days:
        print("尚未产生任何日志。")
        return 1

    problems = []
    total = 0
    print("PreBell · 日志验真（含 11-17 前的雷达历史链）")
    print("-" * 76)
    for day in days:
        rows = load_day(day)
        expected_prev = ZERO
        broken = None
        hashes = []
        for idx, row in enumerate(rows, 1):
            if row.get("__corrupt__") or "hash" not in row:
                broken = f"第 {idx} 条无法解析"
                break
            if row.get("prev_hash") != expected_prev:
                broken = f"第 {idx} 条 prev_hash 与上一轮不接"
                break
            recomputed = entry_hash(row, expected_prev)
            if recomputed != row["hash"]:
                broken = f"第 {idx} 条内容被改动（hash 不符）"
                break
            expected_prev = row["hash"]
            hashes.append(row["hash"])
        total += len(rows)

        spath = LOGDIR / (day + ".summary.json")
        merkle_note = "无当日汇总"
        if spath.exists():
            s = json.loads(spath.read_text(encoding="utf-8"))
            real = merkle_root(hashes)
            if s.get("merkle_root") == real:
                merkle_note = "Merkle 一致 " + real[:12]
            else:
                merkle_note = "Merkle 不一致"
                problems.append(f"{day}: summary 的 Merkle root 与实际记录对不上")

        exp = expected_rounds(day)
        gap = exp - len(rows)
        gap_note = f"缺 {gap} 轮" if gap > 0 else "轮次齐"

        offsets = [r.get("offset_in_slot_min") for r in rows
                   if isinstance(r.get("offset_in_slot_min"), int)]
        gaps = [r.get("gap_from_prev_min") for r in rows
                if isinstance(r.get("gap_from_prev_min"), int)]
        dropped = sum(1 for g in gaps if g > 5)
        sched_note = ""
        if offsets or gaps:
            sched_note = " 偏移max=%s 漏轮=%d" % (max(offsets) if offsets else "-", dropped)

        if broken:
            problems.append(f"{day}: 哈希链断在 {broken}")
        print(f"{day}  {len(rows):>3}/{exp:<3} 轮  {gap_note:<9} {merkle_note:<24} "
              f"{broken or '链完整'}{sched_note}")

    print("-" * 76)
    print(f"共 {len(days)} 天 / {total} 轮记录")
    print("说明：11-17 前的 8 轮/天属旧雷达任务，不计入 PreBell 的连续 7 天窗口；"
          "偏移与漏轮只作如实记录，不补写、不判失败。")
    if problems:
        print("验真未通过：")
        for p in problems:
            print("  - " + p)
        return 1
    print("验真通过：没有发现补写、删改或断链。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
