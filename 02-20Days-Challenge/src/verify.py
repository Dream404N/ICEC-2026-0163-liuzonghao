"""一键验真：任何人 clone 仓库后运行即可。

    python 02-20Days-Challenge/src/verify.py

检查四件事：
  1. 每一天的哈希链是否连续，改过哪一行会精确报出来；
  2. 每日 summary 里的 Merkle root 是否等于当天所有记录重算的结果；
  3. 该响的闹钟有没有响：11-17 起，期望值不再写死，而是从
     src/schedule.json（由 resolve.py 从课表整学期算出的表）按日期取，
     缺哪一节、多出哪一节都点名；
  4. 迟到情况：actual - planned 的分布，超过阈值的次数。

期望轮次按日期分段，因为 11-17 前后是两套调度：
  - 11-10 ~ 11-16：旧「校园节点雷达」，每 3 小时一轮 = 8 轮/天；
  - 11-17 起：PreBell，由 cron-job.org 按课表定点触发，一天 1-3 条。
这些日志由不同任务产生，但共用同一条哈希链；11-10~11-16 不计入 PreBell
自身的窗口。本脚本只报缺口，绝不补写。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from chain import LOGDIR, entry_hash, load_day, merkle_root, ZERO  # noqa: E402

SWITCH_DATE = "2026-11-17"
RADAR_ROUNDS = 8
SCHEDULE = HERE / "schedule.json"


def load_schedule_by_date():
    """{日期: [slot_id, ...]}；表不存在返回 None。"""
    if not SCHEDULE.exists():
        return None
    try:
        payload = json.loads(SCHEDULE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    out = {}
    for slot in payload.get("push_slots", []):
        out.setdefault(slot["date"], []).append(slot["id"])
    return out


def main() -> int:
    if not LOGDIR.exists():
        print("尚未产生任何日志：process_logs/ 不存在。")
        return 1
    days = sorted(p.stem for p in LOGDIR.glob("????-??-??.jsonl"))
    if not days:
        print("尚未产生任何日志。")
        return 1

    by_date = load_schedule_by_date()
    problems = []
    total = 0
    print("PreBell · 日志验真（含 11-17 前的雷达历史链）")
    print("-" * 88)

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
                merkle_note = "Merkle 一致 " + real[:10]
            else:
                merkle_note = "Merkle 不一致"
                problems.append(f"{day}: summary 的 Merkle root 与实际记录对不上")

        if day < SWITCH_DATE:
            # 旧雷达，只核对轮数
            gap = RADAR_ROUNDS - len(rows)
            note = f"缺 {gap} 轮" if gap > 0 else "轮次齐"
            if gap > 0:
                note += "（旧雷达，不计入 PreBell）"
            counter = f"{len(rows):>3}/{RADAR_ROUNDS:<3}"
        elif by_date is None:
            note = "schedule.json 缺失，无法判期望"
            problems.append(f"{day}: src/schedule.json 不存在，跑一次 resolve.py")
            counter = f"{len(rows):>3}/?  "
        else:
            want = set(by_date.get(day, []))
            got = {r.get("schedule_slot") for r in rows if r.get("schedule_slot")}
            missing = sorted(want - got)
            extra = sorted(got - want)
            if not want:
                # 这天本来就不上课：闹钟不该响，响了也只该是 no_class 一类的记录
                note = "本日无课" if len(rows) == 0 else "本日无课但有 %d 条记录" % len(rows)
            elif missing:
                note = "缺 " + "、".join(m.replace(day + "-", "") for m in missing)
                problems.append(f"{day}: 该响没响 {', '.join(missing)}")
            else:
                note = "齐"
            if extra:
                note += " | 多 " + "、".join(e.replace(day + "-", "") for e in extra)
                problems.append(f"{day}: 推送了课表里没有的 {', '.join(extra)}")
            counter = f"{len(got & want):>3}/{len(want):<3}"

        lates = [r.get("late_by_min") for r in rows if isinstance(r.get("late_by_min"), int)]
        late_note = ""
        if lates:
            over = sum(1 for x in lates if x > 15)
            late_note = " 迟到max=%d分%s" % (max(lates), "（超阈值%d次）" % over if over else "")

        if broken:
            problems.append(f"{day}: 哈希链断在 {broken}")
        print(f"{day} {counter}条 {note:<24} {merkle_note:<24} {broken or '链完整'}{late_note}")

    print("-" * 88)
    print(f"共 {len(days)} 天 / {total} 条记录")
    print("说明：11-17 前是旧雷达的 8 轮/天，不计入 PreBell；"
          "11-17 起期望值由课表推导，缺哪一节直接点名。缺口只报不补。")
    if by_date is None:
        print("提示：src/schedule.json 不存在，PreBell 用不了，先跑 python src/resolve.py")
    if problems:
        print("验真未通过：")
        for p in problems:
            print("  - " + p)
        return 1
    print("验真通过：没有发现补写、删改、断链或漏响。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
