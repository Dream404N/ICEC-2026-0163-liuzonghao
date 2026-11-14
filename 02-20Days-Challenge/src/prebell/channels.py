"""可插拔推送通道。

主通道：企业微信群机器人 Webhook 直连（免费、无每日条数上限）。
备用通道：Server酱 Turbo（微信服务号直达，免费 5 条/天，可选开关）。

官方接口原文（developer.work.weixin.qq.com/document/path/91770）：
  POST https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx
  {"msgtype": "text", "text": {"content": "..."}}
  text.content 最长 2048 字节、必须 UTF-8；每个消息推送不超过 20 条/分钟。
官方特别提醒：webhook 地址绝不能出现在 GitHub 等公开可查阅的地方，
所以凭据只从环境变量（GitHub Actions Secrets）读取，且不写进任何日志。
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from prebell import model

WECOM_LIMIT_NOTE = "官方限流 20 条/分钟；本程序最多 6 条/天，不会触发。"
SERVERCHAN_QUOTA_NOTE = "Server酱 Turbo 免费 5 条/天（官方 FAQ），仅作备用。"


def _result(status, http_status, duration_ms, error, channel):
    return {
        "status": status,
        "http_status": http_status,
        "duration_ms": duration_ms,
        "error": model.scrub_text(error) if error else None,
        "channel": channel,
    }


def _post_json(url, payload, timeout):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json; charset=utf-8",
                 "User-Agent": "ICEC-P04-PreBell/2.0"},
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", "ignore")
            ms = int((time.time() - t0) * 1000)
            try:
                errcode = json.loads(body).get("errcode", -1)
            except json.JSONDecodeError:
                errcode = -1
            ok = r.status == 200 and errcode == 0
            return _result("ok" if ok else "failed", r.status, ms,
                           None if ok else body[:200], "wecom_webhook")
    except urllib.error.HTTPError as e:
        return _result("failed", e.code, int((time.time() - t0) * 1000),
                       "HTTP %s %s" % (e.code, e.reason), "wecom_webhook")
    except Exception as e:
        return _result("failed", 0, int((time.time() - t0) * 1000),
                       "%s: %s" % (type(e).__name__, e), "wecom_webhook")


def _post_form(url, fields, timeout):
    data = urllib.parse.urlencode(fields).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
                 "User-Agent": "ICEC-P04-PreBell/2.0"},
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", "ignore")
            ms = int((time.time() - t0) * 1000)
            try:
                code = json.loads(body).get("code", -1)
            except json.JSONDecodeError:
                code = -1
            ok = r.status == 200 and code == 0
            return _result("ok" if ok else "failed", r.status, ms,
                           None if ok else body[:200], "serverchan_turbo")
    except urllib.error.HTTPError as e:
        return _result("failed", e.code, int((time.time() - t0) * 1000),
                       "HTTP %s %s" % (e.code, e.reason), "serverchan_turbo")
    except Exception as e:
        return _result("failed", 0, int((time.time() - t0) * 1000),
                       "%s: %s" % (type(e).__name__, e), "serverchan_turbo")


def _clip_utf8(text, limit=2000):
    """按 UTF-8 字节截断，避免超出官方 2048 字节上限。"""
    b = text.encode("utf-8")
    if len(b) <= limit:
        return text
    return b[:limit].decode("utf-8", "ignore") + "…"


def send_wecom(title, content, config, timeout=10):
    env_var = config["primary"]["env_var"]
    url = os.environ.get(env_var, "").strip()
    if not url:
        return _result("failed", 0, 0, "missing credential %s" % env_var,
                       "wecom_webhook")
    text = _clip_utf8(title + "\n" + content)
    return _post_json(url, {"msgtype": "text", "text": {"content": text}}, timeout)


def send_serverchan(title, content, config, timeout=10):
    env_var = config["fallback"]["env_var"]
    key = os.environ.get(env_var, "").strip()
    if not key:
        return _result("failed", 0, 0, "missing credential %s" % env_var,
                       "serverchan_turbo")
    url = "https://sctapi.ftqq.com/%s.send" % key
    return _post_form(url, {"title": title[:32], "desp": content}, timeout)


def build_sender(config, timeout=None):
    """返回 (title, content) -> result 的可调用对象；主通道失败可切备用。"""
    timeout = timeout or config.get("timeout_sec", 10)
    primary_kind = config.get("primary", {}).get("type", "wecom_webhook")
    fallback_enabled = bool(config.get("fallback_channel_enabled", False))

    def _primary(title, content):
        if primary_kind == "serverchan_turbo":
            return send_serverchan(title, content, config, timeout)
        return send_wecom(title, content, config, timeout)

    def _fallback(title, content):
        if primary_kind == "serverchan_turbo":
            return send_wecom(title, content, config, timeout)
        return send_serverchan(title, content, config, timeout)

    def sender(title, content):
        res = _primary(title, content)
        if res["status"] == "ok" or not fallback_enabled:
            return res
        alt = _fallback(title, content)
        alt["fallback_from"] = res["error"]
        return alt

    return sender
