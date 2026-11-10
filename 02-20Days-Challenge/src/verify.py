"""一键验真：任何人 clone 仓库后运行即可。

    python 02-20Days-Challenge/src/verify.py

检查三件事：
  1. 每一天的哈希链是否连续，改过哪一行会精确报出来；
  2. 每日 summary 里的 Merkle root 是否等于当天所有记录重算的结果；
  3. 哪一天少跑了轮次（按 30 分钟一轮，允许 cron 排队延迟，只报缺口不补写）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from chain import LOGDIR, entry_hash, last_hash, load_day, merkle_root, ZERO  # noqa: E402

EXPECTED_ROUNDS_PER_DAY = 48


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
    print("校园节点雷达 · 日志验真")
    print("-" * 58)
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

        gap = EXPECTED_ROUNDS_PER_DAY - len(rows)
        gap_note = f"缺 {gap} 轮" if gap > 0 else "轮次齐"
        if broken:
            problems.append(f"{day}: 哈希链断在 {broken}")
        print(f"{day}  {len(rows):>3} 轮   {gap_note:<9} {merkle_note:<24} {broken or '链完整'}")

    print("-" * 58)
    print(f"共 {len(days)} 天 / {total} 轮记录")
    if problems:
        print("验真未通过：")
        for p in problems:
            print("  - " + p)
        return 1
    print("验真通过：没有发现补写、删改或断链。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
