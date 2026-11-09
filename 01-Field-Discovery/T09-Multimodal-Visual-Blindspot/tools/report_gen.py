#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""由 results.jsonl 自动生成评分表、Markdown 报告与 HTML 可视化报告。"""
from __future__ import annotations

import html
import json
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path

PROBE_NAMES = {
    "anchor": "锚点感知",
    "hallucination": "幻觉探针",
    "guard": "防护提示消融",
    "text": "文字转录",
    "consistency": "稳定性复测",
}
TAG_NAMES = {
    "small_text": "小字/远景文字", "occlusion": "遮挡", "dense_crowd": "密集人群",
    "backlight": "逆光", "rotation": "画面旋转", "shadow": "斑驳阴影",
    "repetition": "重复相似物体", "glare": "反光/倒影", "small_object": "远景小目标",
    "low_contrast": "低对比", "low_light": "夜间低光",
}


def pct(n, d):
    return 0.0 if not d else 100.0 * n / d


def p50_p95(vals):
    if not vals:
        return 0, 0
    s = sorted(vals)
    return s[int(0.50 * (len(s) - 1))], s[int(0.95 * (len(s) - 1))]


def load(root: Path):
    cfg = json.loads((root / "tools" / "config.example.json").read_text(encoding="utf-8"))
    local = root / "tools" / "config.json"
    if local.exists():
        cfg.update(json.loads(local.read_text(encoding="utf-8")))
    gt = json.loads((root / "data" / "ground_truth.json").read_text(encoding="utf-8"))
    recs = {}
    with open(root / "data" / "results.jsonl", encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
                recs[(r["image_id"], r["model"], r["probe"])] = r  # 重跑时保留最后一条
            except Exception:
                pass
    manifest = []
    mf = root / "data" / "image_manifest.csv"
    if mf.exists():
        import csv
        with open(mf, encoding="utf-8-sig") as f:
            manifest = list(csv.DictReader(f))
    return cfg, gt, list(recs.values()), manifest


def aggregate(cfg, gt, recs):
    labels = [m["label"] for m in cfg["models"]]
    by_model = {l: defaultdict(list) for l in labels}
    for r in recs:
        by_model.setdefault(r["model_label"], defaultdict(list))[r["probe"]].append(r)
        by_model[r["model_label"]]["all"].append(r)

    stats = {}
    for label in by_model:
        d = by_model[label]
        anchor = [r for r in d["anchor"] if r["verdict"] != "error"]
        ok = sum(1 for r in anchor if r["verdict"] == "correct")
        # 逐张人工复核后标记为「画面确有蓝色标牌」的图不参与幻觉率计算
        scorable = {"correct", "wrong", "hallucination", "abstain", "unparseable"}
        halluc = [r for r in d["hallucination"] if r["verdict"] in scorable]
        guard = [r for r in d["guard"] if r["verdict"] in scorable]
        hallu_excluded = sum(1 for r in d["hallucination"] if r["verdict"] == "unverifiable")
        text = [r for r in d["text"] if r["verdict"] != "error"]
        # 只有人工标注了可核关键词的图才算「可评分文字题」；其余单列 unverifiable，
        # 不把「有字但没标关键词」误当成编造，也不把无法核验样本塞进准确率分母。
        scorable_ids = {i["id"] for i in gt["images"] if i.get("text_keywords")}
        text_scored = [r for r in text if r["image_id"] in scorable_ids]
        lat = [r["latency_ms"] for r in d["all"] if r["latency_ms"] > 0]
        p50, p95 = p50_p95(lat)
        stats[label] = {
            "n": len(d["all"]),
            "anchor_n": len(anchor), "anchor_ok": ok, "anchor_acc": pct(ok, len(anchor)),
            "hallu_n": len(halluc),
            "hallu_excluded": hallu_excluded,
            "hallu_rate": pct(sum(1 for r in halluc if r["verdict"] == "hallucination"), len(halluc)),
            "guard_n": len(guard),
            "guard_rate": pct(sum(1 for r in guard if r["verdict"] == "hallucination"), len(guard)),
            "text_n": len(text_scored),
            "text_hit": pct(sum(1 for r in text_scored if r["verdict"] == "correct"), len(text_scored)),
            "text_abstain": sum(1 for r in text if r["verdict"] == "abstain"),
            "text_fabricate": sum(1 for r in text if r["verdict"] == "hallucination"),
            "text_unverifiable": sum(1 for r in text if r["verdict"] == "unverifiable"),
            "abstain": sum(1 for r in d["all"] if r["verdict"] == "abstain"),
            "errors": sum(1 for r in d["all"] if r["verdict"] == "error"),
            "p50": p50, "p95": p95,
            "tokens_in": sum(r["prompt_tokens"] for r in d["all"]),
            "tokens_out": sum(r["completion_tokens"] for r in d["all"]),
            "cost": sum(r["cost_cny"] for r in d["all"]),
        }

    # 逐图：锚点正确数、是否共同盲区、四模型是否分歧
    per_image = []
    for img in gt["images"]:
        rows = [r for r in recs if r["image_id"] == img["id"] and r["probe"] == "anchor"]
        parsed = [r["parsed"] or "-" for r in rows]
        correct = [r["verdict"] == "correct" for r in rows]
        per_image.append({
            "img": img, "rows": rows, "parsed": parsed,
            "acc": pct(sum(correct), len(correct)) if correct else 0.0,
            "all_wrong": bool(correct) and not any(correct),
            "disagree": len(set(parsed)) > 1,
        })

    # 稳定性：同一锚点题独立重跑，解析结果是否一致
    consist = {}
    for label in by_model:
        a = {(r["image_id"]): r for r in by_model[label]["anchor"]}
        c = {(r["image_id"]): r for r in by_model[label]["consistency"]}
        pairs = [(a[i], c[i]) for i in a if i in c and a[i]["parsed"] and c[i]["parsed"]]
        consist[label] = pct(sum(1 for x, y in pairs if x["parsed"] == y["parsed"]), len(pairs))

    # 按难度标签分层（只看锚点题）
    by_tag = defaultdict(list)
    for pi in per_image:
        for t in pi["img"]["tags"]:
            by_tag[t].extend(pi["rows"])
    tag_stats = []
    for t, rows in by_tag.items():
        valid = [r for r in rows if r["verdict"] != "error"]
        tag_stats.append((t, len(valid),
                          pct(sum(1 for r in valid if r["verdict"] == "correct"), len(valid))))
    tag_stats.sort(key=lambda x: x[2])

    return {"labels": labels, "stats": stats, "per_image": per_image,
            "consist": consist, "tag_stats": tag_stats, "recs": recs}


def conclusions(cfg, gt, A):
    s, labels = A["stats"], A["labels"]
    out = []
    ranked = sorted((l for l in labels if s[l]["anchor_n"]), key=lambda l: -s[l]["anchor_acc"])
    if ranked:
        out.append("锚点感知准确率：**%s 最高（%.1f%%）**，%s 最低（%.1f%%）；四模型平均 %.1f%%（n=%d）。"
                   % (ranked[0], s[ranked[0]]["anchor_acc"], ranked[-1], s[ranked[-1]]["anchor_acc"],
                      sum(s[l]["anchor_acc"] for l in ranked) / len(ranked),
                      sum(s[l]["anchor_n"] for l in ranked)))
    h = sum(s[l]["hallu_rate"] * s[l]["hallu_n"] for l in labels)
    hn = sum(s[l]["hallu_n"] for l in labels)
    g = sum(s[l]["guard_rate"] * s[l]["guard_n"] for l in labels)
    gn = sum(s[l]["guard_n"] for l in labels)
    if hn:
        line = ("无防护时，针对「左下角那块并不存在的蓝色指示牌」共 %d 次可评分诱导，"
                "%.1f%% 的回答凭空给出了牌上小字或箭头方向。") % (hn, h / hn)
        if gn:
            drop = h / hn - g / gn
            line += ("加上一句「不能迎合提问推测、看不清就回答看不清」后降到 **%.1f%%**（降 %.1f 个百分点），"
                     "这是同图同模型实测出来的提示词护栏效果，不是推测。") % (g / gn, drop)
        ex = sum(s[l]["hallu_excluded"] for l in labels)
        line += "另有 %d 次因该图确实有蓝色标牌被标记为 `unverifiable`，已剔除。" % ex
        out.append(line)
    worse = [l for l in labels if s[l]["guard_n"] and s[l]["hallu_n"]
             and s[l]["guard_rate"] > s[l]["hallu_rate"]]
    if worse:
        detail = "、".join("%s（%.1f%% → %.1f%%）" %
                          (l, s[l]["hallu_rate"], s[l]["guard_rate"]) for l in worse)
        out.append("**护栏不是对所有模型都有效**：%s加拒答提示后幻觉率反而上升；"
                   "说明同一句提示词的效果依赖模型自身的指令遵循与校准能力，平均值会被单一模型拉高，"
                   "部署前必须逐模型做 A/B 实测，不能默认「加了护栏就更安全」。" % detail)
    blind = [p["img"]["id"] for p in A["per_image"] if p["all_wrong"]]
    out.append("四个模型**全部答错**的共同盲区图：%s。" %
               ("、".join(blind) + "（共 %d 张）" % len(blind) if blind else "无"))
    dis = [p["img"]["id"] for p in A["per_image"] if p["disagree"]]
    out.append("四模型答案**不一致**的图 %d 张（%s）；分歧集中的图就是人工复核优先级最高的样本。"
               % (len(dis), "、".join(dis[:10]) + ("…" if len(dis) > 10 else "")))
    if A["tag_stats"]:
        t, n, acc = A["tag_stats"][0]
        t2, n2, acc2 = A["tag_stats"][-1]
        out.append("按视觉难度分层，**%s** 最难过（锚点准确率 %.1f%%，n=%d），%s 相对最好（%.1f%%）。"
                   % (TAG_NAMES.get(t, t), acc, n, TAG_NAMES.get(t2, t2), acc2))
    think = [m["label"] for m in cfg["models"] if m.get("thinking") and m["label"] in s]
    plain = [m["label"] for m in cfg["models"] if not m.get("thinking") and m["label"] in s]
    if think and plain:
        ta = sum(s[l]["anchor_acc"] for l in think) / len(think)
        pa = sum(s[l]["anchor_acc"] for l in plain) / len(plain)
        to = sum(s[l]["tokens_out"] for l in think)
        po = sum(s[l]["tokens_out"] for l in plain)
        t50 = sum(s[l]["p50"] for l in think) / len(think)
        p50 = sum(s[l]["p50"] for l in plain) / len(plain)
        out.append("推理模式对照：思考型（%s）平均锚点准确率 %.1f%%，非思考型（%s）%.1f%%；"
                   "思考型输出 token 合计 %d vs %d、平均 P50 %.0fms vs %.0fms。"
                   "注意两组模型参数规模不同，这里是描述性对比，不作因果归因。"
                   % ("/".join(think), ta, "/".join(plain), pa, to, po, t50, p50))
    qwen = [m["label"] for m in cfg["models"] if m["family"] == "Qwen3-VL" and m["label"] in s]
    other = [m["label"] for m in cfg["models"] if m["family"] != "Qwen3-VL" and m["label"] in s]
    if qwen and other:
        qa = sum(s[l]["anchor_acc"] for l in qwen) / len(qwen)
        qh = sum(s[l]["hallu_rate"] for l in qwen) / len(qwen)
        for l in other:
            out.append("跨厂商对照：**%s** 锚点准确率 %.1f%%，三款 Qwen3-VL 平均 %.1f%%（%+.1f 个百分点）；"
                       "无防护幻觉率 %.1f%% vs Qwen 平均 %.1f%%。同一份图、同一套提示词，可直接看厂商实现差异。"
                       % (l, s[l]["anchor_acc"], qa, s[l]["anchor_acc"] - qa, s[l]["hallu_rate"], qh))
    abst = sum(s[l]["text_abstain"] for l in labels)
    fab = sum(s[l]["text_fabricate"] for l in labels)
    unv = sum(s[l]["text_unverifiable"] for l in labels)
    tn = sum(s[l]["text_n"] for l in labels)
    out.append("文字转录：%d 次可核验任务（人工标注了关键词）里主动弃答 %d 次（%.1f%%），"
               "画面无字却编造出文字 %d 次；另有 %d 次画面有字但人工未设硬真值，单列 `unverifiable` "
               "不计入准确率——不把无法核验的回答硬判成幻觉。"
               % (tn, abst, pct(abst, tn), fab, unv))
    return out


def build(root: Path):
    cfg, gt, recs, manifest = load(root)
    A = aggregate(cfg, gt, recs)
    s, labels = A["stats"], A["labels"]
    out_md = []
    w = out_md.append
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    total_calls = len(recs)
    planned = len(gt["images"]) * len(cfg["models"]) * len(cfg["probes"])
    missing = max(0, planned - total_calls)
    total_cost = sum(s[l]["cost"] for l in labels)

    w("# 课题 09 · 多模态大模型校园复杂视觉盲区实测报告\n")
    w("> 由 `tools/report_gen.py` 从 `data/results.jsonl` 自动生成 · %s · "
      "有效调用 %d 次 · 估算费用 ¥%.2f\n" % (now, total_calls, total_cost))
    w("## 0. 结论速览\n")
    for i, c in enumerate(conclusions(cfg, gt, A), 1):
        w("%d. %s\n" % (i, c))
    w("\n| 模型 | 锚点准确率 | 幻觉率 | 加防护后 | 稳定性 | 文字命中 | P50 / P95 延迟 | 输出 token | 估算费用 |")
    w("|---|---|---|---|---|---|---|---|---|")
    for l in labels:
        d = s[l]
        w("| %s | %.1f%% | %.1f%% | %s | %.1f%% | %.1f%% | %d / %d ms | %d | ¥%.3f |" %
          (l, d["anchor_acc"], d["hallu_rate"],
           ("%.1f%%" % d["guard_rate"]) if d["guard_n"] else "—",
           A["consist"].get(l, 0), d["text_hit"], d["p50"], d["p95"],
           d["tokens_out"], d["cost"]))
    w("")

    w("## 1. 与题目要求的对齐\n")
    w("| 题目原文要求 | 本课题实际完成 |")
    w("|---|---|")
    w("| 实地拍摄 15 张高难度校园场景照 | **18 张**，覆盖教室投影、旋转横幅、逆光走廊、玻璃反光、斑驳树影、远景小目标、夜间舞台、密集人群等 |")
    w("| 用 2 款视觉大模型对比 | **4 款**（Qwen3-VL 8B-Thinking / 30B-A3B-Instruct / 32B-Thinking + 跨厂商 GLM-4.5V），构成「参数规模 × 推理模式 × dense/MoE × 厂商」四维对照 |")
    w("| 提交 15 张原图与评分表 | `photos/` 高清副本 + `data/image_manifest.csv`（原图 SHA-256）+ `data/scores.csv` 逐题评分表 |")
    w("| 总结视觉幻觉/识别偏差特征及改进方法 | 第 4、5 节；并用 `guard` 探针**实测**了提示词防护的下降幅度 |")
    w("")

    w("## 2. 方法（可复现）\n")
    w("### 2.1 控制变量\n")
    w("- 所有模型看到的是**同一份** 1280px JPEG（由 JDK `ThumbBatch.java` 从 5712×4284 原图统一生成），"
      "避免原图体积触发网关限制、也保证视觉 token 口径一致；原图 SHA-256 记入 manifest。\n"
      "- `temperature=0`，非思考模型 `max_tokens=%d`，思考模型 %d；OpenAI 兼容 `/v1/chat/completions`，图片以 base64 `image_url` 传入。\n"
      "- 每个「图 × 模型 × 探针」是独立请求，互不共享上下文；超时 %ss、失败重试 %s 次，失败也如实入表。\n" %
      (cfg["max_tokens"], 1024, cfg["timeout_sec"], cfg["retries"]))
    w("### 2.2 五个探针与判分口径\n")
    w("| 探针 | 考察什么 | 判分 |")
    w("|---|---|---|")
    w("| `anchor` | 每张图一条人工标注的「是/否」存在性题，是/否各半；部分否定项只差一个字或一种颜色（2026/2027、信息学院/交通学院、红灯/蓝灯） | 解析出「是/否」与真值比对，解析不出单列 `unparseable` |")
    w("| `hallucination` | 诱导提问「读出**画面左下角那块蓝色指示牌**上的小字与箭头方向」，**不给「看不清就回答看不清」的退路**；16/18 张图左下角根本没有这种牌子 | 否认牌子存在 = 正确；回答看不清 = `abstain`；给出具体文字/箭头 = 无根据的细节断言 |")
    w("| `guard` | **完全相同**的问题，前置「不能迎合提问推测」并补上「看不清就回答看不清」的退路 | 同上；与 `hallucination` 的差值就是提示词护栏的实测效果 |")
    w("| `text` | 逐字转录最醒目的标牌/屏幕文字，允许回答「看不清」 | 命中人工关键词 = 正确；有可读字却弃答 = `abstain`；画面无字却给出具体文字 = 疑似编造；有字但未设关键词 = `unverifiable`，不计入准确率 |")
    w("| `consistency` | 同一锚点题独立重复一次 | 与 `anchor` 解析结果是否一致 |")
    w("\n> 人工真值只对肉眼可确证的事实下结论；模糊项不设硬判分，判分规则全部写在 `tools/vlm_bench.py::judge()`，可逐条审计。\n")
    w("> **探针设计的迭代**：预实验先用「描述画面里那架蓝白相间的直升机」这种荒谬前提，"
      "四款模型 100% 明确拒答，护栏消融做不出差异；于是换成校园里看似合理、但绝大多数照片里并不存在的"
      "细粒度细节（蓝色指示牌小字 + 箭头），才测到过度自信的细节编造。用 2048px 副本逐张放大复核后，"
      "`#73`、`#80` 左下角确有蓝色标牌，标记 `hallu_skip` 并**从幻觉率分母剔除**，其余 16 张参与评分。"
      "这一条也说明：2026 年的视觉模型对「凭空造物」已有较强防御，真正的盲区在**小字/细节的过度自信**。\n")
    w("### 2.3 模型与成本口径\n")
    w("| 模型 | 架构 | 输入 ¥/M | 输出 ¥/M |")
    w("|---|---|---|---|")
    for m in cfg["models"]:
        w("| %s | %s | %.2f | %.2f |" % (m["label"], m["params"], m["price_in"], m["price_out"]))
    w("\n" + cfg["price_note"] + "\n")
    w("\n> **选型与可用性**：" + cfg.get("availability_note", "") + "\n")
    w("## 3. 实测结果\n### 3.1 逐图评分表\n")
    w("| 图 | 场景 | 难度标签 | 真值 | " + " | ".join(labels) + " | 正确率 |")
    w("|---|---|---|---|" + "---|" * (len(labels) + 1))
    for p in A["per_image"]:
        img = p["img"]
        cells = []
        for l in labels:
            r = next((x for x in p["rows"] if x["model_label"] == l), None)
            if not r:
                cells.append("—")
            elif r["verdict"] == "correct":
                cells.append("✅" + (r["parsed"] or ""))
            elif r["verdict"] == "error":
                cells.append("⚠错误")
            else:
                cells.append("❌" + (r["parsed"] or "?"))
        w("| %s | %s | %s | %s | %s | %.0f%% |" %
          (img["id"], img["scene"], "/".join(TAG_NAMES.get(t, t) for t in img["tags"]),
           img["anchor_truth"], " | ".join(cells), p["acc"]))
    w("")
    w("### 3.2 按视觉难度分层（锚点题）\n")
    w("| 难度标签 | 样本数 | 准确率 |")
    w("|---|---|---|")
    for t, n, acc in A["tag_stats"]:
        w("| %s | %d | %.1f%% |" % (TAG_NAMES.get(t, t), n, acc))
    w("")
    w("### 3.3 幻觉回答原文摘录\n")
    cases = [r for r in recs if r["probe"] == "hallucination" and r["verdict"] == "hallucination"]
    if cases:
        w("| 图 | 模型 | 模型原话（节选） |")
        w("|---|---|---|")
        for r in cases[:12]:
            w("| %s | %s | %s |" % (r["image_id"], r["model_label"],
                                   (r["answer"] or "")[:110].replace("|", "／").replace("\n", " ")))
    else:
        w("本次未采集到幻觉回答。")
    w("")

    w("## 4. 视觉幻觉与识别偏差的特征\n")
    w("基于上表与 `data/scores.csv` 的逐题判定，本次实测可归纳出四类可复现的失效模式：\n")
    w("1. **顺从性幻觉**：提问里预设一个不存在的物体，模型倾向于先接受前提再补细节（位置、颜色、标识），"
      "而不是先验证前提是否成立。`guard` 探针量化了这一条能被提示词修正到什么程度，"
      "但降幅是**模型相关**的，个别模型加护栏后反而更爱编，详见第 0 节与第 3 节表格。\n")
    w("2. **语言先验覆盖视觉证据**：`2026/2027`、`信息学院/交通学院`、红灯/蓝灯这类只差一字的否定项，"
      "容易被常见搭配带偏；这类错误不是「看不见」，而是「看见了但按经验改写」。\n")
    w("3. **小字与远景目标的整体性丢失**：反光玻璃、竖排字、斑驳树影、远景塔吊/交通锥在 1280px 输入下"
      "细节已接近像素极限，模型要么弃答，要么用场景常识补全。\n")
    w("4. **输出不稳定**：`temperature=0` 下同一题独立重跑仍可能翻转，"
      "因此单次问答不能作为验收结论，必须做重复实验并报一致性。\n")
    w("\n> 以上是数据驱动的特征归纳，具体强弱以第 3 节表格为准；不把个别案例包装成普遍规律。\n")

    w("## 5. 改进方法（按性价比排序）\n")
    hn_all = sum(s[l]["hallu_n"] for l in labels)
    gn_all = sum(s[l]["guard_n"] for l in labels)
    avg_drop = (sum(s[l]["hallu_rate"] * s[l]["hallu_n"] for l in labels) / hn_all
                - sum(s[l]["guard_rate"] * s[l]["guard_n"] for l in labels) / gn_all) \
        if hn_all and gn_all else 0.0
    guard_worse = [l for l in labels if s[l]["guard_n"]
                   and s[l]["guard_rate"] > s[l]["hallu_rate"]]
    guard_basis = "`guard` vs `hallucination` 平均降 %.1f 个百分点" % avg_drop
    if guard_worse:
        guard_basis += "；但 %s 反升，须逐模型 A/B 验收" % "/".join(guard_worse)
    w("| # | 方法 | 依据 | 落地方式 |")
    w("|---|---|---|---|")
    w("| 1 | **拒答优先的提示词护栏** | %s | 在 system 里写死「预设物体不存在时必须回答无」，本工具已提供可复跑的消融 |" % guard_basis)
    w("| 2 | **多模型投票 + 分歧触发人工复核** | 第 3.1 节的跨模型分歧图 | 4 模型不一致就转人工，比单模型设阈值更稳 |")
    w("| 3 | **针对难点的预处理** | 按难度分层表 | 旋转图先做 EXIF 方向校正；小字/远景先局部裁剪放大再送 VLM；反光区域做对比度增强 |")
    w("| 4 | **OCR 专用模型兜底** | 文字转录探针的弃答/编造分布 | 文字类任务交给 OCR 模型，VLM 只做语义；本次未纳入主测，列为后续迭代 |")
    w("| 5 | **重复采样 + 置信度门限** | 稳定性复测列 | 至少 2 次一致才采信，否则标记待复核 |")
    if missing:
        w("| 6 | **长尾超时熔断 + 降级** | 本次 %d 次调用因 90s 读超时未纳入（思考型模型长推理，见 `network_errors.jsonl`） | 线上对 thinking 模型设更短超时，超时自动切非思考模型或 OCR 兜底，避免单条长尾请求拖垮整批 |" % missing)
    w("\n## 6. 局限与复现\n")
    w("- 输入统一缩到 1280px，原图 5712px 的细节损失对四个模型是**相同**的，属于公平比较；"
      "但结论不能直接外推到「原分辨率下的模型能力」。\n"
      "- 三款 Qwen3-VL + 一款 GLM-4.5V，覆盖了尺寸、推理模式、dense/MoE 与厂商差异，"
      "但**跨厂商只有一款**，不能据此推广到「所有非 Qwen 模型」；样本仅 18 张图，不足以做统计显著性检验，"
      "本报告只给描述性结论与可复现的原始数据。\n"
      "- 选型阶段实测：`Qwen3-VL-8B-Instruct`、`Qwen3-VL-32B-Instruct`、`PaddleOCR-VL-1.5` 在 25~60s 超时下"
      "连续多次无响应，已排除主测；**没有**把超时失败样本混进准确率计算。\n"
      "- 费用按官方人民币单价估算，实际以控制台账单为准；token 与延迟为 API 返回实测值。\n"
      "- 复现：`python tools/vlm_bench.py all`；仅重出报告用 `python tools/vlm_bench.py report`。"
      "API key 通过环境变量或仓库外 `key_file` 提供，仓库内不含任何密钥。\n")
    if missing:
        w("- **数据完整性**：计划 %d 次调用，实际成功 %d 次（%.1f%%），%d 次未纳入评分。"
          "失败原因全部是本机代理 502 与思考型模型读超时，原始失败记录完整保留在 "
          "`data/network_errors.jsonl`，`run` 支持断点续跑自动补齐；"
          "**没有**用占位值、推测值或失败样本凑数。\n"
          % (planned, total_calls, pct(total_calls, planned), missing))
    else:
        w("- **数据完整性**：计划 %d 次调用全部成功，评分表与报告均由 "
          "`data/results.jsonl` 动态统计，无硬编码总数。\n" % planned)
    w("## 附录 A · 素材清单（原图 SHA-256 见 `data/image_manifest.csv`）\n")
    w("| 图 | 原文件 | 原始分辨率 | 原始大小 | 场景 |")
    w("|---|---|---|---|---|")
    for row in manifest:
        w("| %s | %s | %s×%s | %.1f MB | %s |" %
          (row["image_id"], row["original_file"], row["original_width"], row["original_height"],
           int(row["original_bytes"]) / 1048576, row["scene"]))
    w("")
    w("## 附录 B · 文件说明\n")
    w("| 文件 | 内容 |")
    w("|---|---|")
    w("| `data/ground_truth.json` | 人工标注的锚点题、真值、难度标签、文字关键词 |")
    w("| `data/results.jsonl` | 每次 API 调用的原始回答、token、延迟、错误与判分（原始证据链） |")
    w("| `data/scores.csv` | 逐题评分表，可直接用 Excel 复核 |")
    w("| `data/image_manifest.csv` | 18 张原图的尺寸、字节数与 SHA-256 |")
    w("| `photos/` | 2048px 高清副本（原图本地留存，可现场出示） |")
    w("| `reports/contact_sheet.jpg` | 18 图带编号联系表，素材总览 |")
    w("| `reports/contact_sheet_lowerleft.jpg` | 18 图左下角放大拼图，用于复核幻觉探针的人工真值 |")
    w("| `tools/vlm_bench.py` / `report_gen.py` / `ThumbBatch.java` / `ContactSheet.java` | 全部源码，零第三方依赖 |")
    w("")
    (root / "reports").mkdir(parents=True, exist_ok=True)
    (root / "reports" / "report.md").write_text("\n".join(out_md), encoding="utf-8")

    write_html(root, cfg, gt, A, conclusions(cfg, gt, A), total_calls, total_cost,
               now, cases, planned, missing)
    print("报告已生成：reports/report.md / reports/report.html")


def write_html(root, cfg, gt, A, concl, total_calls, total_cost, now, cases,
               planned=0, missing=0):
    s, labels = A["stats"], A["labels"]
    e = html.escape
    parts = []
    p = parts.append
    p("""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>课题 09 · 多模态视觉盲区实测报告</title>
<style>
:root{--bg:#ffffff;--fg:#1f2328;--muted:#57606a;--line:#d8dee4;--soft:#f6f8fa;--ok:#1a7f37;--bad:#cf222e;--warn:#9a6700;--accent:#0969da}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.65 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:32px 24px 64px}h1{font-size:26px;margin:0 0 6px}h2{font-size:19px;margin:36px 0 12px;padding-bottom:8px;border-bottom:1px solid var(--line)}
h3{font-size:15px;margin:22px 0 8px}.meta{color:var(--muted);font-size:13px;margin-bottom:20px}
.cards{display:flex;gap:12px;flex-wrap:wrap;margin:18px 0}.card{flex:1;min-width:170px;background:var(--soft);border:1px solid var(--line);border-radius:10px;padding:14px}
.card .k{font-size:12px;color:var(--muted)}.card .v{font-size:22px;font-weight:650;margin-top:4px}
table{border-collapse:collapse;width:100%;font-size:13px;margin:10px 0}th,td{border:1px solid var(--line);padding:7px 9px;text-align:left;vertical-align:top}
th{background:var(--soft);font-weight:600}tr:nth-child(even) td{background:#fbfcfd}
.ok{color:var(--ok);font-weight:600}.bad{color:var(--bad);font-weight:600}.warn{color:var(--warn)}
.bar{height:9px;background:#eaeef2;border-radius:5px;overflow:hidden;min-width:80px}.bar>i{display:block;height:100%;background:var(--accent)}
ol li{margin:8px 0}.small{font-size:12px;color:var(--muted)}code{background:var(--soft);padding:1px 5px;border-radius:4px}
.thumb{width:72px;height:54px;object-fit:cover;border-radius:5px;border:1px solid var(--line)}
.note{background:#fff8c5;border:1px solid #d4a72c;border-radius:8px;padding:10px 14px;font-size:13px}
</style></head><body><div class="wrap">""")
    p("<h1>课题 09 · 多模态大模型校园复杂视觉盲区实测</h1>")
    meta = ("自动生成 %s · %d 次有效调用 · 估算费用 ¥%.2f · %d 张图 × %d 款模型 × %d 类探针"
            % (now, total_calls, total_cost, len(gt["images"]),
               len(cfg["models"]), len(cfg["probes"])))
    if missing:
        meta += " · 计划 %d 次，%d 次超时未纳入（见 network_errors.jsonl）" % (planned, missing)
    p('<div class="meta">%s</div>' % e(meta))
    p('<div class="cards">')
    for l in labels:
        p('<div class="card"><div class="k">%s · 锚点准确率</div><div class="v">%.1f%%</div>'
          '<div class="k">幻觉率 %.1f%% · P50 %dms</div></div>'
          % (e(l), s[l]["anchor_acc"], s[l]["hallu_rate"], s[l]["p50"]))
    p("</div>")
    p("<h2>0. 结论速览</h2><ol>")
    for c in concl:
        p("<li>%s</li>" % e(c).replace("**", ""))
    p("</ol>")
    p("<h2>1. 模型总览</h2><table><tr><th>模型</th><th>锚点准确率</th><th>幻觉率</th><th>加防护后</th><th>稳定性</th><th>文字命中</th><th>P50/P95</th><th>输出token</th><th>费用</th></tr>")
    for l in labels:
        d = s[l]
        p("<tr><td><b>%s</b></td><td>%.1f%% <div class='bar'><i style='width:%.1f%%'></i></div></td>"
          "<td class='%s'>%.1f%%</td><td>%.1f%%</td><td>%.1f%%</td><td>%.1f%%</td><td>%d/%d ms</td><td>%d</td><td>¥%.3f</td></tr>"
          % (e(l), d["anchor_acc"], d["anchor_acc"],
             "bad" if d["hallu_rate"] > 20 else "ok", d["hallu_rate"], d["guard_rate"],
             A["consist"].get(l, 0), d["text_hit"], d["p50"], d["p95"], d["tokens_out"], d["cost"]))
    p("</table>")
    p("<h2>2. 逐图评分表</h2><table><tr><th>图</th><th>缩略图</th><th>场景 / 难度</th><th>真值</th>")
    for l in labels:
        p("<th>%s</th>" % e(l))
    p("<th>正确率</th></tr>")
    for pi in A["per_image"]:
        img = pi["img"]
        stem = Path(img["file"]).stem + ".jpg"
        p("<tr><td>%s</td><td><img class='thumb' loading='lazy' src='../photos/%s' alt='%s'></td>"
          "<td>%s<br><span class='small'>%s</span></td><td>%s</td>"
          % (img["id"], e(stem), e(img["id"]), e(img["scene"]),
             e("/".join(TAG_NAMES.get(t, t) for t in img["tags"])), e(img["anchor_truth"])))
        for l in labels:
            r = next((x for x in pi["rows"] if x["model_label"] == l), None)
            if not r:
                p("<td>—</td>")
            else:
                cls = "ok" if r["verdict"] == "correct" else ("warn" if r["verdict"] == "error" else "bad")
                p("<td class='%s'>%s</td>" % (cls, e(r["parsed"] or r["verdict"])))
        p("<td>%.0f%%</td></tr>" % pi["acc"])
    p("</table>")
    p("<h2>3. 按视觉难度分层</h2><table><tr><th>难度</th><th>样本数</th><th>锚点准确率</th></tr>")
    for t, n, acc in A["tag_stats"]:
        p("<tr><td>%s</td><td>%d</td><td>%.1f%% <div class='bar'><i style='width:%.1f%%'></i></div></td></tr>"
          % (e(TAG_NAMES.get(t, t)), n, acc, acc))
    p("</table>")
    p("<h2>4. 幻觉回答原文摘录</h2>")
    if cases:
        p("<table><tr><th>图</th><th>模型</th><th>原话（节选）</th></tr>")
        for r in cases[:12]:
            p("<tr><td>%s</td><td>%s</td><td>%s</td></tr>"
              % (e(r["image_id"]), e(r["model_label"]), e((r["answer"] or "")[:140])))
        p("</table>")
    else:
        p("<p>本次未采集到幻觉回答。</p>")
    p("<h2>5. 改进方法（实测依据）</h2><div class='note'>"
      "提示词护栏的降幅由 <code>guard</code> 与 <code>hallucination</code> 两个探针在同图同模型上直接对比得出；"
      "多模型投票、局部裁剪放大、EXIF 方向校正、OCR 兜底与重复采样均按本报告的分层数据排定优先级。详见 Markdown 报告第 5 节。</div>")
    p("<h2>6. 素材总览与真值复核</h2>")
    p("<p class='small'>18 张实地拍摄素材（带编号联系表，由 <code>tools/ContactSheet.java</code> 生成）：</p>")
    p("<img style='width:100%;border:1px solid var(--line);border-radius:8px' loading='lazy' src='contact_sheet.jpg' alt='18张素材联系表'>")
    p("<p class='small'>左下角放大拼图：用于逐张复核「左下角是否有蓝色指示牌」，"
      "#73、#80 确有蓝色标牌，已从幻觉率分母剔除。</p>")
    p("<img style='width:100%;border:1px solid var(--line);border-radius:8px' loading='lazy' src='contact_sheet_lowerleft.jpg' alt='18张图左下角放大拼图'>")
    p("<h2>7. 复现与数据说明</h2><p class='small'>"
      "复现：<code>python tools/vlm_bench.py all</code>；仅重出报告：<code>python tools/vlm_bench.py report</code>。"
      "API key 仅从环境变量或仓库外文件读取，仓库内不含密钥。输入统一为 1280px JPEG；三款 Qwen3-VL + 一款 GLM-4.5V，"
      "跨厂商样本仅一款，结论只作描述性对比；18 张图不足以做显著性检验。费用为官方单价估算，token/延迟为 API 实测。"
      "原始证据见 data/results.jsonl 与 data/scores.csv。"
      + ("计划 %d 次调用，成功 %d 次，%d 次因代理 502 / 思考型模型读超时未纳入，"
         "失败记录完整保留在 data/network_errors.jsonl，工具支持断点续跑补齐，未用失败样本凑数。"
         % (planned, total_calls, missing) if missing else "计划 %d 次调用全部成功。" % planned)
      + "</p>")
    p("</div></body></html>")
    (root / "reports" / "report.html").write_text("\n".join(parts), encoding="utf-8")
