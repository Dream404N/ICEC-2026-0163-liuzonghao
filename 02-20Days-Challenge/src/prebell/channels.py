"""可插拔推送通道：默认两条都是「1:1 通知给个人」，不往群里发。

主通道 Server酱 Turbo：微信服务号会话 1:1 推送，扫码即得 SendKey。
  POST https://sctapi.ftqq.com/<SendKey>.send  form: title / desp
  成功判据 code == 0；免费 5 条/天（官方 FAQ sct.ftqq.com/docs/getting-started/faq）。
备用通道 WxPusher 极简推送 SPT：同为 1:1 个人通知，扫码得 SPT、免费、无 5 条/天限制，
  用来兜住周一 6 条/天里主通道发不出的第 6 条。
  POST https://wxpusher.zjiecode.com/api/send/message/simple-push
  {"content":..., "summary":..., "contentType":1, "spt":"SPT_xxx"}
  成功判据 code == 1000（官方文档 wxpusher.zjiecode.com/docs/#/?id=spt）。
可选通道 wecom_webhook：群机器人，代码保留便于回退，但默认不启用——群会话不满足「通知给个人」。

为何不用企业微信自建应用（本来也是免费 1:1）：2022-06-20 后新建自建应用强制「企业可信 IP」，
仅支持单个 IPv4、不支持 IP 段、且拦截第三方服务商 IP；GitHub Actions 出口 IP 动态，无法登记。
出处：open.work.weixin.qq.com/help2/pc/21711、work.weixin.qq.com/nl/act/p/32d807ad4c554975、

所有凭据只从环境变量（GitHub Actions Secrets）读取，日志只记脱敏后的结果。
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from prebell import model

SERVERCHAN_QUOTA_NOTE = "Server酱 Turbo 免费 5 条/天、每分钟 50 条（官方 FAQ）；订阅后 1000 条/天。"
WXPUHER_QUOTA_NOTE = "WxPusher 极简推送免费；接口默认约每 10 秒 20 次调用；6 条/天无压力。"
WECOM_LIMIT_NOTE = "群机器人 20 条/分钟；仅作可选回退，默认不发群。"

DEFAULT_ENV = {
    "serverchan_turbo": "PREBELL_SENDKEY",
    "wxpusher_spt": "PREBELL_WXPUSHER_SPT",
    "wecom_webhook": "PREBELL_WECOM_WEBHOOK",
}


def _result(status, http_status, duration_ms, error, channel):
    return {
        "status": status,
        "http_status": http_status,
        "duration_ms": duration_ms,
        "error": model.scrub_text(error) if error else None,
        "channel": channel,
    }


def _post(url, data, content_type, timeout, channel, success):
    """统一 POST。success(parsed_body, raw_body) -> bool 决定业务层是否成功。"""
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": content_type,
                 "User-Agent": "ICEC-P04-PreBell/2.0"},
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
            ok = r.status == 200 and bool(success(parsed, body))
            return _result("ok" if ok else "failed", r.status, ms,
                           None if ok else body[:200], channel)
    except urllib.error.HTTPError as e:
        return _result("failed", e.code, int((time.time() - t0) * 1000),
                       "HTTP %s %s" % (e.code, e.reason), channel)
    except Exception as e:
        return _result("failed", 0, int((time.time() - t0) * 1000),
                       "%s: %s" % (type(e).__name__, e), channel)


def _clip_utf8(text, limit=2000):
    """按 UTF-8 字节截断，避免超出各通道的内容长度上限。"""
    b = text.encode("utf-8")
    if len(b) <= limit:
        return text
    return b[:limit].decode("utf-8", "ignore") + "…"


def _env_var(config, kind):
    for section in ("primary", "fallback"):
        if config.get(section, {}).get("type") == kind:
            return config[section].get("env_var", DEFAULT_ENV[kind])
    return config.get("channels", {}).get(kind, {}).get("env_var", DEFAULT_ENV[kind])


def _credential(config, kind):
    name = _env_var(config, kind)
    value = os.environ.get(name, "").strip()
    if not value:
        return None, _result("failed", 0, 0, "missing credential %s" % name, kind)
    return value, None


def send_serverchan(title, content, config, timeout=10):
    """微信服务号 1:1 私聊。title ≤32 字且不能含换行，desp 支持 Markdown。"""
    key, missing = _credential(config, "serverchan_turbo")
    if missing:
        return missing
    url = "https://sctapi.ftqq.com/%s.send" % key
    data = urllib.parse.urlencode({"title": title[:32].replace("\n", " "),
                                   "desp": content}).encode("utf-8")
    return _post(url, data, "application/x-www-form-urlencoded; charset=utf-8",
                 timeout, "serverchan_turbo",
                 lambda p, b: p.get("code", -1) == 0)


def send_wxpusher(title, content, config, timeout=10):
    """1:1 个人通知（SPT 极简推送）。contentType=1 纯文本，summary 显示在通知栏。"""
    spt, missing = _credential(config, "wxpusher_spt")
    if missing:
        return missing
    payload = {
        "content": _clip_utf8(title + "\n" + content),
        "summary": _clip_utf8(title.replace("\n", " "), 100),
        "contentType": 1,
        "spt": spt,
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return _post("https://wxpusher.zjiecode.com/api/send/message/simple-push",
                 data, "application/json; charset=utf-8", timeout, "wxpusher_spt",
                 lambda p, b: p.get("code", -1) == 1000)


def send_wecom(title, content, config, timeout=10):
    """可选回退：群机器人。默认配置不启用，因为群会话不是「通知给个人」。"""
    url, missing = _credential(config, "wecom_webhook")
    if missing:
        return missing
    text = _clip_utf8(title + "\n" + content)
    data = json.dumps({"msgtype": "text", "text": {"content": text}},
                      ensure_ascii=False).encode("utf-8")
    return _post(url, data, "application/json; charset=utf-8", timeout,
                 "wecom_webhook", lambda p, b: p.get("errcode", -1) == 0)


def build_sender(config, timeout=None):
    """返回 (title, content) -> result；主通道失败时切到备用通道，两条都是 1:1。"""
    timeout = timeout or config.get("timeout_sec", 10)
    senders = {
        "serverchan_turbo": send_serverchan,
        "wxpusher_spt": send_wxpusher,
        "wecom_webhook": send_wecom,
    }
    primary_kind = config.get("primary", {}).get("type", "serverchan_turbo")
    fallback_kind = config.get("fallback", {}).get("type", "wxpusher_spt")
    fallback_enabled = bool(config.get("fallback_channel_enabled", True))

    def sender(title, content):
        res = senders[primary_kind](title, content, config, timeout)
        if res["status"] == "ok" or not fallback_enabled:
            return res
        alt = senders[fallback_kind](title, content, config, timeout)
        alt["fallback_from"] = res["error"]
        return alt

    return sender
