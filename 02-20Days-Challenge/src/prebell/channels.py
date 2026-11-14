"""推送通道：只保留 Server酱 Turbo（微信服务号 1:1 私聊）。

POST https://sctapi.ftqq.com/<SendKey>.send   form: title / desp
成功判据 code == 0；免费额度以官方 FAQ 为准，本程序一天最多 4 条。

2026-11-13 已在 GitHub Actions 境外 runner 上实测可达（HTTP 200 / code 0），
所以不需要备用通道。此前设计过的企业微信群机器人（群会话，非 1:1）与
WxPusher SPT（要额外装 App、多一个 Secret）全部撤掉：多一个通道就多一份
使用者要手工配置的东西，却并没有解决真实问题。

凭据只从环境变量（GitHub Actions Secrets）读，日志只记脱敏后的结果。
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from prebell import model


def _result(status, http_status, duration_ms, error, channel="serverchan_turbo"):
    return {
        "status": status,
        "http_status": http_status,
        "duration_ms": duration_ms,
        "error": model.scrub_text(error) if error else None,
        "channel": channel,
    }


def send_serverchan(title, content, config, timeout=10):
    """微信服务号 1:1 私聊。title ≤32 字且不能含换行，desp 支持 Markdown。"""
    name = config.get("env_var", "PREBELL_SENDKEY")
    key = os.environ.get(name, "").strip()
    if not key:
        return _result("failed", 0, 0, "missing credential %s" % name)

    url = "https://sctapi.ftqq.com/%s.send" % key
    data = urllib.parse.urlencode({
        "title": title[:32].replace("\n", " "),
        "desp": content,
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
                 "User-Agent": "PreBell/3.0"},
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", "ignore")
            ms = int((time.time() - t0) * 1000)
            try:
                parsed = json.loads(body)
            except json.JSONDecodeError:
                parsed = {}
            ok = r.status == 200 and parsed.get("code", -1) == 0
            return _result("ok" if ok else "failed", r.status, ms,
                           None if ok else body[:200])
    except urllib.error.HTTPError as e:
        return _result("failed", e.code, int((time.time() - t0) * 1000),
                       "HTTP %s %s" % (e.code, e.reason))
    except Exception as e:
        return _result("failed", 0, int((time.time() - t0) * 1000),
                       "%s: %s" % (type(e).__name__, e))


def build_sender(config, timeout=None):
    """返回 (title, content) -> result。只走一条通道，失败如实记 failed，不静默切备用。"""
    timeout = timeout or config.get("timeout_sec", 10)
    return lambda title, content: send_serverchan(title, content, config, timeout)
