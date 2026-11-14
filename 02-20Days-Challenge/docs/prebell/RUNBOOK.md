# 部署与运行手册

> ⚠ **本文已作废（2026-11-14）**：属于 2.0 版（企业微信群机器人 / WxPusher 主备双通道、
> 6 个外部 cron job、30/5 分双时点、每天 6 条）。3.0 版只需一个 `PREBELL_SENDKEY`，
> 定时直接在 GitHub Actions，无需注册第三方网站或造 PAT。
> 当前口径见 `docs/prebell/README.md` 与 `02-20Days-Challenge/README.md`。本文保留作过程证据。

## 1. 目录与 protected 边界

```
02-20Days-Challenge/
├── src/prebell/            源码、课表、配置样例、静态提醒表、自检（本地可写）
├── docs/prebell/           规则契约 / 本手册 / 隐私说明（本地可写）
├── feedback/               8 位真实用户反馈（只放模板，内容由真人填）
├── iterations/prebell/     3 次数据驱动迭代说明（不预写）
├── process_logs/           ★ protected：仅云端 Actions 写
├── state/                  ★ protected：仅云端 Actions 写
└── public/                 ★ protected：仅云端 Actions 写
```

`★` 三个前缀写死在工作区根 `.workbuddy/sync_to_github.py` 的 `PROTECT_PREFIXES`：本地同步既不删也不覆盖。
本机 `git push` 被代理拦截，从工作区根运行 `python .workbuddy/sync_to_github.py "说明"`（Git Data API）。
本地 dry-run 与自检一律把 `--root` 指向临时目录，不碰这三个目录。

## 2. 微信通道：1:1 通知给个人（不是群消息）

**需求变更**：用户要「通知给个人」。群机器人无论怎么配，消息都落在群会话，已从默认路径移除；
`channels.py` 仍保留 `send_wecom()` 作为可选回退，但默认不发群。

### 为什么不用企业微信自建应用

自建应用本来是免费 1:1 通道（`POST /cgi-bin/message/send?access_token=...`，`touser` 指定成员），
但 2022-06-20 后新建自建应用强制「企业可信 IP」：官方原文
`仅配置的可信IP能调用企业微信接口`、`企业可信IP不支持添加IP段、不支持添加含*的IP`、
`目前企业可信IP仅支持配置ipv4`，且会拦截第三方服务商 IP。
GitHub Actions 托管 runner 出口 IP 动态，无法登记 → **排除**。
出处：`open.work.weixin.qq.com/help2/pc/21711`、`work.weixin.qq.com/nl/act/p/32d807ad4c554975`。

### 默认两条通道（都是 1:1 个人通知）

| | 主通道 Server酱 Turbo | 备用 WxPusher 极简推送 SPT |
|---|---|---|
| 送达 | 微信服务号会话，1:1 私聊 | 1:1 个人通知（App / 微信 ClawBot） |
| 接口 | `POST https://sctapi.ftqq.com/<SendKey>.send`，form `title` / `desp` | `POST https://wxpusher.zjiecode.com/api/send/message/simple-push`，JSON `content` / `summary` / `contentType:1` / `spt` |
| 成功 | `code == 0` | `code == 1000` |
| 额度 | 免费 **5 条/天**、每分钟 50 条（官方 FAQ） | 免费；接口约每 10 秒 20 次调用；无 5 条/天限制 |
| 门槛 | 微信扫码登录 `sct.ftqq.com` → 复制 SendKey | 微信扫码得 `SPT_xxx`；需装 WxPusher App 或绑定微信 ClawBot |

**为什么要备用**：周一 3 大节 × 2 阶段 = 6 条，Server酱免费只有 5 条。
`build_sender()` 在主通道失败（含额度耗尽）时自动切备用，仍是 1:1 个人通知；
绝不把两条提醒合并成一条，也不静默丢掉第 6 条。日志如实记 `channel` 与 `fallback_from`。

**只想要一个通道、6 条全在微信服务号**：订阅 Server酱（官方页 8 元/1 月、39 元/12 月，1000 条/天），
再把 `config.example.json` 的 `fallback_channel_enabled` 设为 `false`，代码一行不改。

**其它候选（如实记录，未采用）**：PushPlus 是 1:1 微信服务号、实名后 200 条/天，
但实名需填姓名 / 身份证 / 手机号并支付认证费（官方 `pushplus.plus/doc/function/verify.html` 原文
`实名认证是付费的，且不支持退款`）；WxPusher 微信 ClawBot 通道激活后 24 小时内最多 10 条、
用尽需手动回复重新激活，不适合 7 天无人值守，因此 WxPusher 只作备用而非主通道。

### 用户侧准备（一次性）

1. 微信扫码登录 `https://sct.ftqq.com` → 关注「方糖」服务号 → 复制 **SendKey**（`SCT...`）。
2. 微信扫 `https://wxpusher.zjiecode.com/docs/#/?id=spt` 的 SPT 二维码 → 复制 **SPT**（`SPT_...`）；
   装 WxPusher App，或在 App 内绑定微信 ClawBot 作为接收端。
3. GitHub 仓库 → Settings → Secrets and variables → Actions → New repository secret：
   - `PREBELL_SENDKEY` = Server酱 SendKey（**必填**）
   - `PREBELL_WXPUSHER_SPT` = WxPusher SPT（**备用必填**；若已订阅 Server酱并关掉备用，可不填）
4. **不要把 SendKey / SPT 发给我、贴进聊天、写进任何文件**。两者泄漏后任何人都能给你发消息，
   而本仓库按官网要求必须公开。填完回一句「填好了」即可，我不需要看到值。

### 本地连通性自测（凭据只留在本机环境变量，不经过对话、不写日志）

```bash
curl -sS -X POST "https://sctapi.ftqq.com/$PREBELL_SENDKEY.send" \
  -d "title=PreBell 连通性测试" -d "desp=收到说明主通道已通"
# 期望 {"code":0,...}

curl -sS -X POST "https://wxpusher.zjiecode.com/api/send/message/simple-push" \
  -H 'Content-Type: application/json' \
  -d "{\"content\":\"PreBell 连通性测试\",\"contentType\":1,\"spt\":\"$PREBELL_WXPUSHER_SPT\"}"
# 期望 {"code":1000,...}
```

把两个返回的 `code` 告诉我就够，不用贴凭据。注意自测会占用 Server酱当天免费额度。

## 3. 六个外部 cron job

时区设为 **UTC（Etc/UTC）**。北京 = UTC+8，所有触发时刻 ≥ 08:10，减 8 小时后仍是同一日历日，无需 ±1 天偏移。
有课大节：P1 周一/周四、P3 周一/二/三/五、P4 周一/二/三/四（沿用课表初稿口径，**未核对**）。

| Job | UTC cron | 北京 | period | stage | 次/周 |
|---|---|---|---|---|---|
| J1 | `10 0 * * 1,4` | 08:10 | P1 | depart | 2 |
| J2 | `35 0 * * 1,4` | 08:35 | P1 | enter | 2 |
| J3 | `0 5 * * 1,2,3,5` | 13:00 | P3 | depart | 4 |
| J4 | `25 5 * * 1,2,3,5` | 13:25 | P3 | enter | 4 |
| J5 | `40 6 * * 1,2,3,4` | 14:40 | P4 | depart | 4 |
| J6 | `5 7 * * 1,2,3,4` | 15:05 | P4 | enter | 4 |

合计 **20 次唤醒/周**；周一最满：3 大节 × 2 阶段 = **6 条/天**。

每个 job 的请求：

```
POST https://api.github.com/repos/Dream404N/ICEC-2026-0163-LZH/actions/workflows/prebell-remind.yml/dispatches
Authorization: Bearer <PAT，需 Actions:write>
Accept: application/vnd.github+json
{"ref":"main","inputs":{"period":"P1","stage":"depart","source":"cron"}}
```

**分支必须 `main`**（仓库默认分支为 main；本机 git 镜像可能是 master，不要照抄）。
`prebell-remind.yml` 本身不带 `schedule:`；只有 `prebell-daily.yml` 带一条 `55 15 * * *`（UTC）= 北京 23:55，负责每日汇总与验真，不计入上述 6 个 job。

## 4. 部署顺序

1. 填好 2 个 Secrets（`PREBELL_SENDKEY` 必填；`PREBELL_WXPUSHER_SPT` 备用，订阅 Server酱后可省）。
2. 在 cron 服务建 6 个 job，时区 UTC；先各手动触发一次 `source=test` 验连通，日志会如实标 test。
3. **停用既有 `.github/workflows/probe.yml` 的 `schedule: '17 */3 * * *'`**（保留文件、只去掉定时触发），避免废弃的旧雷达日志继续污染 `process_logs/` 的溯源链。
4. 连推 6 条实测 `source=test`，确认 `actual_sent=6`、`error=null`；周一第 6 条预期记 `channel=wxpusher_spt` 与 `fallback_from`，属主通道额度耗尽后的正常兜底，不是失败。
5. 观察首日日志 → 由真实发现驱动第 1 次 Git 迭代（不预写）。
6. 每日 23:55 由 `prebell-daily.yml` 出汇总与验真公示。

## 5. 本地验收命令

```bash
cd 02-20Days-Challenge/src
python -m py_compile prebell/*.py prebell/tests/*.py
python prebell/planner.py --check                 # 360 条 / 20 条·周 / 键唯一
python prebell/tests/test_prebell.py              # 11 项自检
python prebell/run.py --period P1 --stage depart --source test --dry-run
python prebell/verify.py --date 2026-11-16 --root <临时目录>
```

真实证据链只能在云端跑出来；本地 dry-run 的输出不入库、不计入 7 天窗口。

## 6. 时间账（今天 2026-11-14 周六）

真实日历：11/15 周日、**11/16 周一**、11/17 周二、11/18 周三、11/19 周四、11/20 周五、
11/21 周六、11/22 周日、11/23 周一、**11/24 周二**、12/01 周二。

| 日期 | 动作 |
|---|---|
| 11/14 | 代码与文档定稿、自检全绿（已完成） |
| 11/15 周日 | 配 Secrets、建 6 个 job、停用 probe schedule、`source=test` 冒烟 |
| **11/16 周一** | **推荐起跑首日**；7 天窗口 11/16–11/22（5 上课日 + 周末 2 天 heartbeat） |
| 11/18 / 11/20 / 11/22 | 3 次由日志驱动的 Git 迭代（011 / 012 / 013） |
| 11/19 起 → 11/22 前 | 收齐 8 位真实用户反馈 |
| 11/23 周一 | 缓冲：`verify.py` 全绿、公示更新、文档口径对齐 |
| **11/24 周二** | 工坊结束 / 面试启动（官网「初定」）；封仓（出处：顶层 README） |
| 12/01 周二 | 公布名单 |

**零缓冲点**：最晚硬线 11/17 起跑（窗口 11/17–11/23，只留 11/24 一天归档）。
理论极限 11/18 起跑 = 11/18–11/24 恰好 7 天，但撞封仓与面试启动、当日日志未必能完整提交，零容错，不采用。
窗口内任一天 cron 失败或日志未当日提交都会断链且**无法补跑**。
