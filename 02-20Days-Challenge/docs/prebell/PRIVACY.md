# 密钥、脱敏与隐私

## 1. 官方硬约束

企业微信开发者中心原文（`https://developer.work.weixin.qq.com/document/path/91770`）：

> 特别特别要注意：一定要**保护好消息推送的webhook地址**，避免泄漏！不要分享到 github、博客等可被公开查阅的地方，否则坏人就可以用你的消息推送来发垃圾消息了。

而官网 Step 0 要求**公开仓库**（assessment.html L202）。因此本项目把「凭据不入库」当作硬性设计约束，不是可选项。

## 2. 凭据存放

| 凭据 | 存放位置 | 是否入库 |
|---|---|---|
| `PREBELL_WECOM_WEBHOOK` | GitHub → Settings → Secrets and variables → Actions | ❌ 绝不入库 |
| `PREBELL_SENDKEY`（可选） | 同上 | ❌ 绝不入库 |
| 触发 cron 的 PAT（Actions:write） | cron 服务端 + 本机 `.workbuddy/.gh_token` | ❌ 绝不入库 |

- `config.example.json` 只存**环境变量名**，不存值。
- 真实本地配置如需覆盖，复制为 `config.json`；该文件已被 `.gitignore` 排除。
- workflow 只用 `${{ secrets.* }}` 注入环境变量，代码只用 `os.environ.get()` 读取。
- 同步脚本 `sync_to_github.py` 的 `assert_no_secrets()` 会机械拦截 `config.json` / `*.key` / `.env*` / `*api_key*` 及疑似密钥串，命中即中止提交。

## 3. 日志脱敏

`model.scrub_text()` 对所有进入日志的外部文本做三层替换：

```
key=xxxxx            → key=[redacted]
SCT/sctp 开头的密钥  → [sendkey]
https?://...         → [url]
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
- 不向任何第三方上传课表内容以外的个人信息（课表本身只含节次与占位课程名）。
- 不把估算锚点、未核对课表格包装成已核实数据。
- 不补推、不回填、不编造时间戳或日志。

## 6. 通道额度口径（程序不硬编码）

| 通道 | 官方口径 | 出处 |
|---|---|---|
| 企业微信群机器人 | 免费；20 条/分钟；无每日条数上限 | 企业微信开发者文档 |
| Server酱 Turbo | 免费 5 条/天；每分钟 50 条；订阅 1000 条/天 | `https://sct.ftqq.com/docs/getting-started/faq` |

程序侧只有 `max_push_per_day=6`（自身上限）以及日志里的 `actual_sent` / `error` 实测值。
