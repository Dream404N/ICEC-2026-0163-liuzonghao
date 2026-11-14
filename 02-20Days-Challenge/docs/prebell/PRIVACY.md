# 密钥、脱敏与隐私

> ⚠ **部分作废（2026-11-14）**：文中关于「WxPusher SPT / 企业微信 Webhook 两个 Secret」
> 的描述属于 2.0 版。3.0 版只保留一个 Secret `PREBELL_SENDKEY`。
> 「凭据只进 GitHub Actions Secrets、绝不入库、日志脱敏」这条**依然有效**。
> 当前口径见 `docs/prebell/README.md`。

## 1. 官方硬约束

- 官网 Step 0 要求**公开仓库**（assessment.html L202）。
- Server酱的 `SendKey` 是推送凭据，泄漏后他人可用它给你发消息。
- WxPusher 官方文档原文：`请勿泄漏SPT，SPT泄漏后，任意用户都可以给你发送消息！！！`

因此本项目把「凭据不入库」当作硬性设计约束，不是可选项。

## 2. 凭据存放

| 凭据 | 存放位置 | 是否入库 |
|---|---|---|
| `PREBELL_SENDKEY`（主通道，必填） | GitHub → Settings → Secrets and variables → Actions | ❌ 绝不入库 |
| `PREBELL_WXPUSHER_SPT`（备用，默认必填） | 同上 | ❌ 绝不入库 |
| `PREBELL_WECOM_WEBHOOK`（可选群回退，默认不用） | 同上 | ❌ 绝不入库 |
| 触发 cron 的 PAT（Actions:write） | cron 服务端 + 本机 `.workbuddy/.gh_token` | ❌ 绝不入库 |

- `config.example.json` 只存**环境变量名**，不存值。
- 真实本地配置如需覆盖，复制为 `config.json`；该文件已被 `.gitignore` 排除。
- workflow 只用 `${{ secrets.* }}` 注入环境变量，代码只用 `os.environ.get()` 读取。
- 同步脚本 `sync_to_github.py` 的 `assert_no_secrets()` 会机械拦截 `config.json` / `*.key` / `.env*` / `*api_key*` 及疑似密钥串，命中即中止提交。

## 3. 日志脱敏

`model.scrub_text()` 对所有进入日志的外部文本做替换：

```
key=xxxxx              → key=[redacted]
SCT... / sctp...       → [sendkey]
SPT_... / AT_...       → [token]
https?://...           → [url]
```

时间戳只保留**日期 + 分钟级**（`2026-11-16 08:35（脱敏·分钟级）`），不含账号、设备型号、IP、手机号。
报错记录保留脱敏后的指纹，便于面试官追问「异常数据原因」，但不会反推出凭据。

## 4. 反馈脱敏

`feedback/TEMPLATE.md` 的字段不含真实姓名、学号、手机号、身份证。
8 份反馈必须由真实用户填写，用匿名代号标识（如 `U01`）；**不代写、不预填**。
`.gitignore` 已排除 `*身份证*`、`*准考证*`、`*手机号*`。

## 5. 本程序不做的事

- 不读取微信 / 企业微信本地数据库、聊天记录、群消息。
- 不逆向微信客户端、不模拟登录、不使用任何个人号协议库。
- **默认不往群里推送**：主备两条通道都是 1:1 个人通知。
- 不向任何第三方上传课表内容以外的个人信息（课表本身只含节次与占位课程名）。
- 不把估算锚点、未核对课表格包装成已核实数据。
- 不补推、不回填、不编造时间戳或日志。

## 6. 通道额度口径（已核实官方页，程序不硬编码）

| 通道 | 官方口径 | 出处 |
|---|---|---|
| Server酱 Turbo 主通道 | 免费 5 条/天、每分钟 50 条；订阅 1000 条/天（8 元/1 月、39 元/12 月） | `sct.ftqq.com/docs/getting-started/faq` |
| WxPusher 极简推送备用 | 免费；接口默认约每 10 秒 20 次调用；App 渠道单日约 3000 条后不再提醒 | `wxpusher.zjiecode.com/docs/#/?id=limit` |
| PushPlus（未采用） | 实名后微信渠道 200 次/天；实名付费且不支持退款 | `pushplus.plus/doc/guide/use.html`、`/doc/function/verify.html` |
| 企业微信群机器人（不启用） | 20 条/分钟 | `developer.work.weixin.qq.com/document/path/91770` |

程序侧只有 `max_push_per_day=6`（自身上限）以及日志里的 `actual_sent` / `error` / `channel` 实测值。
