# -*- coding: utf-8 -*-
"""把「叮叮课表 Windows 客户端」的真实使用日志提交到 GitHub。

由 dingding_win.py 每天 23:50 调用，也可手动跑：
    python tools/dingding/commit_usage_logs.py

边界（刻意收紧，别放宽）：
  - 只推 tools/dingding/usage_logs/ 下的 *.jsonl 与 README.md；
    绝不碰 process_logs/、state/、public/ —— 那是云端自动化运行证据，
    本机客户端不能写、不能改、也不能删。
  - GitHub 凭据只从工作区外的 .workbuddy/.gh_token 读，不在本文件、不在日志、不入库。
  - 只增改、不删远端任何文件；没日志就不提交，不造空文件凑连续天数。
  - 提交前机械扫描疑似密钥串，命中即中止。
"""
import base64
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent           # <repo>/tools/dingding
REPO_ROOT = HERE.parents[1]
WORKSPACE = HERE.parents[2]
LOG_DIR = HERE / "usage_logs"
TOKEN_FILE = WORKSPACE / ".workbuddy" / ".gh_token"
OWNER, REPO = "Dream404N", "ICEC-2026-0163-liuzonghao"
PREFIX = "tools/dingding/usage_logs/"
ALLOWED = re.compile(r"^(\d{4}-\d{2}-\d{2}\.jsonl|README\.md)$")
SECRET = re.compile(rb"sk-[A-Za-z0-9_\-]{16,}|SCT[A-Za-z0-9]{8,}")
TIMEOUT = 30


def api(method, path, body=None, token=None):
    url = "https://api.github.com" + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Accept": "application/vnd.github+json",
               "User-Agent": "dingding-usage-logs"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if data:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            raw = r.read().decode("utf-8", "ignore")
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "ignore")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"message": raw[:200]}


def blob_sha(content):
    return hashlib.sha1(b"blob %d\0" % len(content) + content).hexdigest()


def collect():
    if not LOG_DIR.exists():
        return {}
    out = {}
    for p in sorted(LOG_DIR.iterdir()):
        if not p.is_file() or not ALLOWED.match(p.name):
            continue
        b = p.read_bytes()
        if SECRET.search(b):
            raise SystemExit("中止：%s 里出现疑似密钥串" % p.name)
        out[PREFIX + p.name] = b
    return out


def submit_once(token):
    base = "/repos/%s/%s" % (OWNER, REPO)
    code, info = api("GET", base, token=token)
    if code != 200:
        raise RuntimeError("读仓库失败 %s %s" % (code, info.get("message")))
    branch = info.get("default_branch") or "main"

    code, br = api("GET", base + "/branches/" + branch, token=token)
    if code != 200:
        raise RuntimeError("读分支失败 %s" % br.get("message"))
    head = br["commit"]["sha"]

    code, tree = api("GET", base + "/git/trees/" + head + "?recursive=1", token=token)
    if code != 200:
        raise RuntimeError("读 tree 失败 %s" % tree.get("message"))
    remote = {x["path"]: x["sha"] for x in tree.get("tree", [])
              if x["type"] == "blob" and x["path"].startswith(PREFIX)}

    local = collect()
    entries = []
    for rel, content in sorted(local.items()):
        sha = blob_sha(content)
        if remote.get(rel) == sha:
            continue
        code, blob = api("POST", base + "/git/blobs", {
            "content": base64.b64encode(content).decode(), "encoding": "base64"}, token)
        if code not in (200, 201):
            raise RuntimeError("上传 %s 失败：%s" % (rel, blob.get("message")))
        entries.append({"path": rel, "mode": "100644", "type": "blob",
                        "sha": blob["sha"]})
    if not entries:
        return None, "无新增日志，未提交（不造空文件凑天数）"

    names = [e["path"].rsplit("/", 1)[-1] for e in entries]
    date = max((n[:10] for n in names if re.match(r"\d{4}-\d{2}-\d{2}", n)),
               default="unknown")
    code, tr = api("POST", base + "/git/trees",
                   {"base_tree": tree["sha"], "tree": entries}, token)
    if code not in (200, 201):
        raise RuntimeError("建 tree 失败：%s" % tr.get("message"))
    code, cm = api("POST", base + "/git/commits", {
        "message": "叮叮课表 客户端使用日志 %s（本机真实事件，非云端运行日志）" % date,
        "tree": tr["sha"], "parents": [head]}, token)
    if code not in (200, 201):
        raise RuntimeError("建 commit 失败：%s" % cm.get("message"))
    code, ref = api("PATCH", base + "/git/refs/heads/" + branch,
                    {"sha": cm["sha"]}, token)
    if code == 422:
        return "CONFLICT", "并发提交冲突，交给上层重试"
    if code not in (200, 201):
        raise RuntimeError("更新分支失败：%s" % ref.get("message"))
    return cm["sha"], "已提交 %d 个日志文件" % len(entries)


def main():
    token = os.environ.get("ICEC_GH_TOKEN", "").strip()
    if not token and TOKEN_FILE.exists():
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    if not token:
        print("没有 GitHub 凭据（%s），本次不提交；不写假日志。" % TOKEN_FILE)
        return 1

    for attempt in range(3):
        try:
            sha, msg = submit_once(token)
            if sha == "CONFLICT":
                continue
            if sha is None:
                print(msg)
                return 0
            print("远端提交 %s · %s" % (sha[:7], msg))
            return 0
        except Exception as e:
            print("提交失败（第 %d 次）：%s" % (attempt + 1, e), file=sys.stderr)
            if attempt == 2:
                return 1
    print("并发冲突重试 3 次仍失败，本次不提交。", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
