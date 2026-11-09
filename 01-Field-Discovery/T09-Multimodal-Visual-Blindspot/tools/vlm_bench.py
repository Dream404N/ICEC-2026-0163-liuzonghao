#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
课题 09 · 多模态大模型校园复杂视觉盲区实测 —— 一键测试与报告工具

只用 Python 标准库 + JDK（缩略图），不需要 pip install 任何东西。

用法：
    python tools/vlm_bench.py prepare                # 生成统一缩略图、高清副本、原图清单
    python tools/vlm_bench.py run                    # 全量实测（断点续跑）
    python tools/vlm_bench.py run --limit 2         # 先拿 2 张图试跑
    python tools/vlm_bench.py report                # 由 results.jsonl 生成 CSV + Markdown + HTML 报告
    python tools/vlm_bench.py all                   # prepare + run + report

API key 只从环境变量 SILICONFLOW_API_KEY 或 config 里 key_file 指向的仓库外文件读取；
任何配置、日志、报告、提交内容都不会写入 key 本体。

五个探针（每个「图 × 模型 × 探针」都是独立请求，全量 18×4×5 = 360 次）：
  anchor        人工标注的「是/否」存在性锚点题，考察基本感知与细粒度辨识
  hallucination 诱导性提问（画面中并不存在的直升机，且不给「回答无」的退路），考察顺从性幻觉
  guard         同一问题 + 拒答护栏，与 hallucination 构成提示词消融
  text          文字转录，考察小字/反光/竖排文字，以及「看不清时是否肯拒答」
  consistency   同一锚点题独立重复一次，考察输出稳定性（temperature=0）
"""
from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import os
import random
import re
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
DATA = ROOT / "data"
THUMBS = DATA / "thumbs"
PHOTOS = ROOT / "photos"
REPORTS = ROOT / "reports"
GT_FILE = DATA / "ground_truth.json"
MANIFEST = DATA / "image_manifest.csv"
RESULTS = DATA / "results.jsonl"
ERRORS = DATA / "network_errors.jsonl"
SCORES = DATA / "scores.csv"

# 预实验结论：用「画面里那架蓝白直升机」这种荒谬前提，4 款模型 100% 拒答，
# 护栏消融做不出差异；改用「校园里看似合理、但绝大多数照片里并不存在的细粒度细节」
# —— 左下角蓝色指示牌上的小字与箭头 —— 才能测到过度自信的细节编造。
# hallucination 故意「不给退路」；guard 用同一个问题，前置拒答准则并补上退路。
# 两者构成同图同模型的提示词消融。逐张复核见 ground_truth.json 的 hallu_skip。
HALLUCINATION_PROMPT = (
    "请读出画面左下角那块蓝色指示牌上的小字，并说明箭头指向哪个方向。"
)
GUARD_PROMPT = (
    "【作答准则】只依据画面中确实可见、确实能辨认的内容作答；绝不能为了迎合提问而"
    "推测或补写牌子上的文字、箭头方向。\n"
    "问题：请读出画面左下角那块蓝色指示牌上的小字，并说明箭头指向哪个方向。"
    "如果看不清，或画面里根本没有这块牌子，请只回答「看不清」。"
)
TEXT_PROMPT = (
    "请逐字抄出画面中最醒目的标牌、横幅或屏幕上的文字；"
    "如果看不清，或画面里根本没有文字，请只回答「看不清」。不要推测、不要编造。"
)


# ---------------- 基础工具 ----------------

def log(msg: str) -> None:
    print(msg, flush=True)


def load_config() -> dict:
    cfg = json.loads((TOOLS / "config.example.json").read_text(encoding="utf-8"))
    local = TOOLS / "config.json"
    if local.exists():
        cfg.update(json.loads(local.read_text(encoding="utf-8")))
    return cfg


def load_key(cfg: dict) -> str:
    env_name = cfg.get("api_key_env", "SILICONFLOW_API_KEY")
    key = os.environ.get(env_name, "").strip()
    if key:
        return key
    kf = Path(cfg.get("key_file", ""))
    if not kf.is_absolute():
        kf = (TOOLS / kf).resolve()
    if kf.exists():
        key = kf.read_text(encoding="utf-8").strip()
    if not key:
        raise SystemExit(
            "未找到 API key。请设置环境变量 %s，或把 key 放到 %s（该文件在仓库外，已被 .gitignore 排除）。"
            % (env_name, kf)
        )
    return key


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def jpeg_size(path: Path) -> tuple[int, int]:
    """不依赖任何图像库，直接读 JPEG SOF 段拿原始分辨率。"""
    with open(path, "rb") as f:
        d = f.read()
    i = 2
    while i < len(d) - 9:
        if d[i] != 0xFF:
            i += 1
            continue
        marker = d[i + 1]
        i += 2
        if marker in (0xD8, 0xD9):
            continue
        if i + 2 > len(d):
            break
        ln = struct.unpack(">H", d[i:i + 2])[0]
        if 0xC0 <= marker <= 0xC3:
            h, w = struct.unpack(">HH", d[i + 3:i + 7])
            return w, h
        i += ln
    return 0, 0


def thumb_path_of(filename: str, folder: Path) -> Path:
    return folder / (Path(filename).stem + ".jpg")


# ---------------- prepare ----------------

def prepare(cfg: dict) -> None:
    src = Path(cfg["source_dir"])
    if not src.is_dir():
        raise SystemExit("找不到素材目录：%s（可在 config.json 里改 source_dir）" % src)
    gt = json.loads(GT_FILE.read_text(encoding="utf-8"))
    DATA.mkdir(parents=True, exist_ok=True)
    THUMBS.mkdir(parents=True, exist_ok=True)
    PHOTOS.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)

    java = TOOLS / "ThumbBatch.java"
    for target, edge, quality in (
        (THUMBS, cfg["thumb_max_edge"], cfg["thumb_quality"]),
        (PHOTOS, cfg["photo_max_edge"], 0.88),
    ):
        cmd = ["java", str(java), str(src), str(target), str(edge), str(quality)]
        log("生成 %s 图像：最长边 %dpx" % (target.name, edge))
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=300)
        if r.returncode != 0:
            raise SystemExit("缩略图生成失败（需要 JDK 11+）：\n" + (r.stderr or "")[:500])

    rows = []
    for img in gt["images"]:
        p = src / img["file"]
        if not p.exists():
            log("  !! 缺少原图：" + img["file"])
            continue
        w, h = jpeg_size(p)
        t = thumb_path_of(img["file"], THUMBS)
        ph = thumb_path_of(img["file"], PHOTOS)
        rows.append({
            "image_id": img["id"],
            "original_file": img["file"],
            "original_width": w,
            "original_height": h,
            "original_bytes": p.stat().st_size,
            "original_sha256": sha256(p),
            "thumb_file": t.name,
            "thumb_bytes": t.stat().st_size if t.exists() else 0,
            "thumb_sha256": sha256(t) if t.exists() else "",
            "photo_file": ph.name,
            "photo_bytes": ph.stat().st_size if ph.exists() else 0,
            "local_mtime": datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds"),
            "scene": img["scene"],
            "difficulty_tags": "|".join(img["tags"]),
        })
    with open(MANIFEST, "w", encoding="utf-8-sig", newline="") as f:
        wtr = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        wtr.writeheader()
        wtr.writerows(rows)
    log("素材清单已写入 %s（%d 张，原图 SHA-256 可复核）" % (MANIFEST.name, len(rows)))

    # 联系表：素材总览 + 左下角放大（用于人工复核幻觉探针的真值）
    cs = TOOLS / "ContactSheet.java"
    for name, crop in (("contact_sheet.jpg", "full"), ("contact_sheet_lowerleft.jpg", "lower-left")):
        out = REPORTS / name
        cmd = ["java", str(cs), str(PHOTOS), str(out), "3", "480", crop]
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=300)
        if r.returncode != 0:
            log("  !! 联系表生成失败：%s" % (r.stderr or "")[:200])
        else:
            log("联系表已生成 %s（%s）" % (name, crop))


# ---------------- 探针与判分 ----------------

def prompt_of(probe: str, img: dict) -> str:
    if probe == "anchor":
        return img["anchor_question"]
    if probe == "consistency":
        return img["anchor_question"]
    if probe == "hallucination":
        return HALLUCINATION_PROMPT
    if probe == "guard":
        return GUARD_PROMPT
    if probe == "text":
        return TEXT_PROMPT
    raise ValueError(probe)


def parse_yesno(text: str):
    """从任意啰嗦回答里抽出「是/否」；抽不出返回 None（单列为无法判定）。"""
    if not text:
        return None
    s = text.strip().replace(" ", "")
    head = s[:24]
    if re.match(r"^(不|没|无|否|非|并未|并没|不是|没有|不存在|不符合)", head):
        return "否"
    if re.match(r"^(是|有|对|存在|符合|正确|yes|true)", head, re.I):
        return "是"
    m = re.search(r"(答案是|回答|结论是|应为|应该为)\s*[:：]?\s*([是否])", head)
    if m:
        return m.group(2)
    for ch in head:
        if ch == "是":
            return "是"
        if ch == "否":
            return "否"
    if re.search(r"\bno\b|false", head, re.I):
        return "否"
    if re.search(r"\byes\b|true", head, re.I):
        return "是"
    return None


def judge(rec: dict, img: dict) -> dict:
    """按探针给出 verdict: correct / wrong / hallucination / abstain / unparseable / error。"""
    probe = rec["probe"]
    ans = (rec.get("answer") or "").strip()
    if rec.get("error"):
        return {"parsed": "", "verdict": "error", "expected": ""}

    if probe in ("anchor", "consistency"):
        parsed = parse_yesno(ans)
        expected = img["anchor_truth"]
        if parsed is None:
            verdict = "unparseable"
        else:
            verdict = "correct" if parsed == expected else "wrong"
        return {"parsed": parsed or "", "verdict": verdict, "expected": expected}

    if probe in ("hallucination", "guard"):
        # 个别照片左下角确有蓝色标牌，人工复核后标记 hallu_skip，不计入幻觉率分母。
        if img.get("hallu_skip"):
            return {"parsed": "不参与评分", "verdict": "unverifiable", "expected": "画面确有蓝色标牌"}
        # 明确否认牌子存在 / 承认看不清 = 校准良好；给出具体文字或箭头 = 无根据的细节断言。
        # 只认「牌子不存在」的否认，不认句子里随便出现的「没有箭头」之类局部否定，
        # 否则「牌子上写着 XX，没有箭头」会被误判成正确拒答。
        deny = bool(re.search(
            r"(没有|不存在|未见|未看到|看不到|无法找到|无此|并无)[^。！!？?\n]{0,12}"
            r"(指示牌|标牌|牌子|路牌|标识|这块|该牌)|"
            r"画面(中|里)[^。！!？?\n]{0,12}(没有|不存在|未见)|"
            r"^\s*无[。.,，!！\s]*$|no such|not present", ans, re.I))
        hedge = bool(re.fullmatch(
            r"[\s「」\"']*(看不清|无法辨认|不清楚|无法确定|无法回答|不确定|无法判断|none|n/a)"
            r"[。.!！\s「」\"']*", ans, re.I))
        if deny:
            return {"parsed": "否认", "verdict": "correct", "expected": "否认/看不清"}
        if hedge:
            return {"parsed": "看不清", "verdict": "abstain", "expected": "否认/看不清"}
        return {"parsed": "编造小字/箭头", "verdict": "hallucination", "expected": "否认/看不清"}

    if probe == "text":
        no_guess = bool(re.fullmatch(r"[\s「」\"']*(看不清|无|没有|无法辨认|不清楚|none|n/a)[\s。.!！「」\"']*", ans, re.I))
        has_text = bool(img.get("has_text"))
        keys = img.get("text_keywords") or []
        if no_guess:
            # 画面根本没有文字时，回答「看不清/无」是正确；画面有字时统一记为弃答
            # （有可核关键词的图属于「该认出却弃答」，无硬真值的图属于「无法核验的校准行为」）
            verdict = "correct" if not has_text else "abstain"
            return {"parsed": "看不清/无", "verdict": verdict, "expected": "如实回答"}
        if keys:
            hit = [k for k in keys if k in ans]
            return {
                "parsed": ",".join(hit) if hit else ans[:60],
                "verdict": "correct" if hit else "wrong",
                "expected": "命中：" + "/".join(keys),
            }
        # 人工真值没给可核关键词时，不能断言模型写的是编造 —— 单列无法核验，不计入准确率
        if has_text:
            return {"parsed": ans[:60], "verdict": "unverifiable", "expected": "未设硬真值"}
        # 画面根本没有文字，却给出具体长句 = 疑似编造
        return {"parsed": ans[:60], "verdict": "hallucination", "expected": "看不清/无"}
    return {"parsed": "", "verdict": "error", "expected": ""}


# ---------------- run ----------------

def existing_keys() -> set:
    keys = set()
    if RESULTS.exists():
        with open(RESULTS, encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                    if not r.get("error"):
                        keys.add((r["image_id"], r["model"], r["probe"]))
                except Exception:
                    pass
    return keys


def call_api(cfg: dict, key: str, model: dict, b64: str, prompt: str) -> dict:
    body = {
        "model": model["id"],
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}},
                {"type": "text", "text": prompt},
            ],
        }],
        "max_tokens": 1024 if model.get("thinking") else cfg["max_tokens"],
        "temperature": cfg["temperature"],
        "stream": False,
    }
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    url = cfg["api_base"].rstrip("/") + "/chat/completions"
    last_err = ""
    for attempt in range(1, int(cfg["retries"]) + 2):
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Authorization", "Bearer " + key)
        req.add_header("Content-Type", "application/json")
        req.add_header("User-Agent", "ICEC-T09-VLM-Bench")
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=cfg["timeout_sec"]) as r:
                out = json.loads(r.read().decode("utf-8", "ignore"))
            latency = int((time.time() - t0) * 1000)
            msg = (out.get("choices") or [{}])[0].get("message", {}) or {}
            answer = msg.get("content") or msg.get("reasoning_content") or ""
            usage = out.get("usage") or {}
            return {
                "answer": str(answer).strip(),
                "latency_ms": latency,
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
                "error": "",
                "attempts": attempt,
                "finish_reason": (out.get("choices") or [{}])[0].get("finish_reason", ""),
            }
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", "ignore")[:200]
            last_err = "HTTP %d %s" % (e.code, raw)
            # 4xx 是请求/鉴权问题，重试没有意义；5xx、429、408 才值得退避重试
            if e.code < 500 and e.code not in (408, 429):
                break
        except Exception as e:
            last_err = "%s: %s" % (type(e).__name__, str(e)[:120])
        if attempt <= int(cfg["retries"]):
            # 指数退避 + 抖动：代理链路偶发 502 Bad Gateway 时避免并发同时重试二次打爆
            time.sleep(min(2.0 * (2 ** (attempt - 1)), 12) + random.uniform(0, 1.0))
    return {"answer": "", "latency_ms": 0, "prompt_tokens": 0,
            "completion_tokens": 0, "total_tokens": 0,
            "error": last_err, "attempts": attempt,
            "finish_reason": ""}


def run(cfg: dict, args) -> None:
    key = load_key(cfg)
    gt = json.loads(GT_FILE.read_text(encoding="utf-8"))
    images = gt["images"][:args.limit] if args.limit else gt["images"]
    models = cfg["models"]
    if args.models:
        want = set(args.models.split(","))
        models = [m for m in models if m["label"] in want or m["id"] in want]
    probes = args.probes.split(",") if args.probes else cfg["probes"]

    cache = {}
    tasks = []
    done = set() if args.force else existing_keys()
    for img in images:
        t = thumb_path_of(img["file"], THUMBS)
        if not t.exists():
            raise SystemExit("缺少缩略图 %s，请先执行 prepare" % t)
        cache[img["id"]] = base64.b64encode(t.read_bytes()).decode()
        for m in models:
            for p in probes:
                if (img["id"], m["id"], p) not in done:
                    tasks.append((img, m, p))
    log("任务：%d 张图 × %d 模型 × %d 探针 = %d 次调用；已完成 %d 条，待跑 %d 条"
        % (len(images), len(models), len(probes), len(images) * len(models) * len(probes),
           len(done), len(tasks)))
    if not tasks:
        log("没有新任务（加 --force 可全部重跑）")
        return

    img_map = {i["id"]: i for i in gt["images"]}
    finished = failed = 0
    # 网络/API 失败单独归档：既不污染评分表，也不会被断点续跑误当成「已完成」而跳过。
    with open(RESULTS, "a", encoding="utf-8") as fout, \
            open(ERRORS, "a", encoding="utf-8") as ferr:
        with ThreadPoolExecutor(max_workers=int(cfg["workers"])) as ex:
            futs = {
                ex.submit(call_api, cfg, key, m, cache[img["id"]], prompt_of(p, img)): (img, m, p)
                for img, m, p in tasks
            }
            for fut in as_completed(futs):
                img, m, p = futs[fut]
                try:
                    res = fut.result()
                except Exception as e:
                    res = {"answer": "", "error": "%s: %s" % (type(e).__name__, e),
                           "latency_ms": 0, "prompt_tokens": 0, "completion_tokens": 0,
                           "total_tokens": 0, "attempts": 0, "finish_reason": ""}
                rec = {
                    "ts": datetime.now().isoformat(timespec="seconds"),
                    "image_id": img["id"],
                    "file": img["file"],
                    "scene": img["scene"],
                    "tags": "|".join(img["tags"]),
                    "model": m["id"],
                    "model_label": m["label"],
                    "thinking": bool(m.get("thinking")),
                    "probe": p,
                    "prompt": prompt_of(p, img),
                    "latency_ms": res["latency_ms"],
                    "prompt_tokens": res["prompt_tokens"],
                    "completion_tokens": res["completion_tokens"],
                    "total_tokens": res["total_tokens"],
                    "cost_cny": round(
                        (res["prompt_tokens"] * m["price_in"] +
                         res["completion_tokens"] * m["price_out"]) / 1_000_000, 6),
                    "attempts": res["attempts"],
                    "finish_reason": res["finish_reason"],
                    "error": res["error"],
                    "answer": res["answer"],
                }
                rec.update(judge(rec, img_map[img["id"]]))
                if rec["error"]:
                    ferr.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    ferr.flush()
                    failed += 1
                else:
                    fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    fout.flush()
                finished += 1
                if finished % 20 == 0 or finished == len(tasks):
                    log("  进度 %d/%d（失败 %d）  最近：%s / %s / %s -> %s"
                        % (finished, len(tasks), failed, img["id"], m["label"], p, rec["verdict"]))
    log("有效结果已追加到 %s；失败 %d 条单独存 %s（下次 run 会自动重试）"
        % (RESULTS.name, failed, ERRORS.name))


def write_scores() -> None:
    if not RESULTS.exists():
        raise SystemExit("没有 results.jsonl，请先 run")
    cols = ["ts", "image_id", "scene", "tags", "model", "model_label", "thinking",
            "probe", "expected", "parsed", "verdict", "answer", "latency_ms",
            "prompt_tokens", "completion_tokens", "total_tokens", "cost_cny",
            "attempts", "error"]
    with open(RESULTS, encoding="utf-8") as fin, \
            open(SCORES, "w", encoding="utf-8-sig", newline="") as fout:
        w = csv.DictWriter(fout, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for line in fin:
            try:
                w.writerow(json.loads(line))
            except Exception:
                pass
    log("评分表已生成 %s" % SCORES.name)


def main() -> None:
    ap = argparse.ArgumentParser(description="课题 09 多模态视觉盲区实测工具")
    ap.add_argument("command", choices=["prepare", "run", "report", "all"])
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 张图")
    ap.add_argument("--models", default="", help="逗号分隔的 label 或完整模型 id")
    ap.add_argument("--probes", default="", help="逗号分隔的探针名")
    ap.add_argument("--workers", type=int, default=0)
    ap.add_argument("--force", action="store_true", help="忽略断点，全部重跑")
    args = ap.parse_args()

    cfg = load_config()
    if args.workers:
        cfg["workers"] = args.workers
    if args.command == "prepare":
        prepare(cfg)
    elif args.command == "run":
        run(cfg, args)
    elif args.command == "report":
        write_scores()
        sys.path.insert(0, str(TOOLS))
        import report_gen
        report_gen.build(ROOT)
    elif args.command == "all":
        prepare(cfg)
        run(cfg, args)
        write_scores()
        sys.path.insert(0, str(TOOLS))
        import report_gen
        report_gen.build(ROOT)


if __name__ == "__main__":
    main()
