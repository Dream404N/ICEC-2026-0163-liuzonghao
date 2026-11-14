# 部署与运行手册

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

## 2. 微信通道：企业微信群机器人 Webhook

官方接口（`https://developer.work.weixin.qq.com/document/path/91770`）：

```
POST https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=<YOUR_KEY>
Content-Type: application/json
{"msgtype": "text", "text": {"content": "..."}}
```

- `content` 最长 2048 字节、必须 UTF-8；程序按字节截断到 2000。
- 返回 `errcode == 0` 视为成功。
- **每个消息推送不超过 20 条/分钟**；本程序最多 6 条/天，不会触发。
- 官方警告原文：`一定要保护好消息推送的webhook地址，避免泄漏！不要分享到github、博客等可被公开查阅的地方`。
  本仓库按官网要求必须公开，因此 Webhook URL **只能**放 GitHub Actions Secrets。

### 用户侧准备（一次性，约 5 分钟）
1. 手机装企业微信，手机号注册（个人可注册，不需要营业执照/企业认证；企业名随意填）。
2. 建一个只有自己的群 → 群设置 → 群机器人 → 添加 → 复制 Webhook URL。
3. GitHub 仓库 → Settings → Secrets and variables → Actions → New repository secret：
   - `PREBELL_WECOM_WEBHOOK` = 完整 Webhook URL（**必填**）
   - `PREBELL_SENDKEY` = Server酱 SendKey（**可选**，仅当 `fallback_channel_enabled=true`）
4. 可选：企业微信 App →「我的企业 → 微信插件」用个人微信扫码绑定，部分资料称群消息可推送到个人微信；
   **需上线前实测**，若不可用消息仍会留在企业微信 App 并正常弹通知。

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

1. 填好 2 个 Secrets（其中 `PREBELL_WECOM_WEBHOOK` 必填）。
2. 在 cron 服务建 6 个 job，时区 UTC；先各手动触发一次 `source=test` 验连通，日志会如实标 test。
3. **停用既有 `.github/workflows/probe.yml` 的 `schedule: '17 */3 * * *'`**（保留文件、只去掉定时触发），避免废弃的旧雷达日志继续污染 `process_logs/` 的溯源链。
4. 连推 6 条实测 `source=test`，确认 `actual_sent=6`、`error=null`（企业微信无日条数上限，Server酱免费 5 条/天只作备用）。
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
