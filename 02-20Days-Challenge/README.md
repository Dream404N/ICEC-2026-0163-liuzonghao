# 预备铃 / PreBell · 项目四

**一句话**：上课前 20 分钟，微信收到一条「下一节上什么课、在哪个教室」，顺带把今天剩下的课全列出来。
手机不用装 App，电脑不用开机，你什么都不用点。

> 本文件对应 **3.0 版（2026-11-14）**。`src/PREBELL.md`、`docs/prebell/RUNBOOK.md`、
> `PLAN.md` 里那些「5 分钟轮询」「30/5 分双时点」「每天 6 条」「6 个外部 cron job」
> 都是 11-13 ~ 11-14 白天被推翻的旧方案，留作过程证据，**不要再照着做**。

## 你现在就能用的两样东西

| | 文件 | 怎么用 |
|---|---|---|
| 课表网页 | `public/index.html` | 双击打开，看今天、看本周、翻上一周下一周 |
| 手机日历 | `public/prebell.ics` | 下载导入手机自带日历，课前 20 分钟由**手机本地**提醒 |

**`.ics` 是最可靠的一层**：不依赖网络、不依赖 GitHub、不依赖微信、不会排队迟到。
微信推送只是增强。哪怕某轮定时任务丢了，日历照样响。

## 微信提醒怎么来的

`src/prebell/timetable.json` 是整张课表（课程名、周次、教室），`src/prebell/planner.py`
一次把整学期展开成 140 条「真正有课」的提醒，写进 `schedule.json`。
运行时只查表，不再现场猜周次。四条 GitHub Actions 定时：

| 北京时间 | 大节 | 上课 | UTC cron |
|---|---|---|---|
| 08:20 | P1 | 08:40 | `20 0 * * 1-5` |
| 10:00 | P2 | 10:20 | `0 2 * * 1-5` |
| 13:10 | P3 | 13:30 | `10 5 * * 1-5` |
| 14:50 | P4 | 15:10 | `50 6 * * 1-5` |

本周没这一节 → 静默跳过，只写一条 `no_schedule` 日志，**不打扰你**。
一大节多门课合并成一条；一天最多 4 条；同一节跑重了靠 `state/pushed.json` 去重。

推送走 **Server酱 Turbo**（微信服务号 1:1 私聊）。SendKey 已在 GitHub Actions Secrets
`PREBELL_SENDKEY`。2026-11-13 与 11-14 在境外 runner 上实测 HTTP 200 / `code:0` / 3.0s。

> **勘误（2026-11-14）**：此前文档写「`code:0` 真发到微信」是过度结论，现更正。
> `code:0` 只证明 **Server酱服务端受理了这条请求**，不能证明手机微信已经弹出。
> 微信能否收到，取决于使用者本人有没有在 Server酱后台完成「微信消息通道」绑定（见下）。
> 云端日志无法替本人确认送达，这一项必须由使用者看一眼微信才能判定。

## 你要做的事

**① 微信端绑定 —— 唯一必须本人动手的一步（约 1 分钟）**

微信扫码登录 `sct.ftqq.com` → 「消息通道」→ 关注 **「方糖」服务号**并完成微信绑定。
漏掉这一步，接口照样返回 `code:0`，但消息没有落脚的地方，于是「配置全绿却一条都收不到」。
绑好后，提醒出现在微信「方糖」服务号的会话里，跟普通微信消息一样弹出。

**② 之后完全不用管**：周一到周五 08:20 / 10:00 / 13:10 / 15:10 自动查表，有课才发。
不用开电脑、不用装 App、不用打开网页、不用点任何按钮。
**不在上述时刻（周末、晚上、假期）本来就不会有消息，这是正常的，不是坏了。**

**③ 建议核对课表**：打开 `public/index.html`，首屏会显示「今天 / 下一次上课」和
「下一次微信提醒」的具体时间；对照原图 `src/timetable-source.png`，尤其确认
第 1 周周一是不是 `2026-09-07`（估算锚点，错一周整张表整体平移）。
有错改 `src/prebell/timetable.json` 后重跑 `python src/prebell/planner.py`，网页/日历/推送表一起更新。

不用注册 cron-job.org、不用造 PAT、不用装 WxPusher App、不用填第二个 Secret、
不用建 6 个定时 job —— 那些是旧方案留下的负担，这一版全部撤掉了。

## 诚实边界

- 锚点未核对、课表未逐格签字确认；网页和每条消息都会带这句警示。
- 教师姓名是截图形近字辨读，置信度低，**不展示**，只留在 JSON 里作档案。
- GitHub cron 高峰期会排队。迟到 ≤15 分钟照发并在消息里写明晚到几分钟；超 15 分钟
  记 `skipped_late` 不发；上课后才醒记 `skipped_after_class`，**绝不补推、绝不回填历史**。
- 周末和无课的工作日不推消息，也不写假的「心跳」日志凑连续天数。
- 手工预览（`--preview`）只发消息、**不写** `process_logs`，不冒充无人值守证据。
- 每轮日志带 `prev_hash`，`src/prebell/verify.py` 一键验真；被否掉的旧雷达
  `probe.yml` 已停掉定时，历史日志保留不删。

## 运行日志会自动进 GitHub，不用手动 commit

`prebell-remind.yml`（工作日四个提醒点）和 `prebell-daily.yml`（每天 23:55 汇总）
在云端跑完后各自 `git commit + push` 回 `main`，提交者 `prebell-bot`，
落盘位置 `process_logs/YYYY-MM-DD.jsonl` / `*.summary.json` / `public/prebell-verify.json`。
本机同步脚本把 `process_logs/` 与 `state/` 设为保护目录，**本地写不了也删不了日志**——
这样日志只可能来自云端真实运行，不是手搓出来的。远端已有实证提交
`d7b2877 prebell-bot | 实测日志 2026-11-14 每日汇总与验真`。

- 周末四个提醒不跑，就没有明细日志，**不补写、不拿心跳凑连续天数**。
- 目录里 `11-10 ~ 11-14` 的日志属于已停用定时的旧「校园节点雷达」，
  不是课表提醒证据；区分口径见 `process_logs/README.md`。
- **勘误（11-15）**：原先这里写的「本地部署的叮叮课表不产生运行日志」是上午 v1 的旧口径，
  已作废。下午 v1.1 / 傍晚 v2.0 的 Windows 客户端每天 23:50 会自动把真实使用事件
  commit 到 `tools/dingding/usage_logs/`；后来加的「课序 0.1.2」客户端写到
  `tools/kexu/usage_logs/`。三者分目录存放，**都不写进 `process_logs/`，互不冒充云端运行日志**。
  仍然成立的是：安卓 APK 无 INTERNET 权限、不放 GitHub 凭据；关机 / 断网 / 没打开应用的那天
  不补写、不造心跳；日志只记真实发生的操作。口径见 `tools/kexu/usage_logs/README.md`。

## 代码与复现

| 文件 | 作用 |
|---|---|
| `src/prebell/timetable.json` | 课表原始数据（唯一需要人工维护的文件） |
| `src/prebell/planner.py` | 按周次展开，生成 `schedule.json` / `public/index.html` / `public/prebell.ics` |
| `src/prebell/run.py` | 单轮：查表 → 去重 → 推微信 → 写日志 |
| `src/prebell/notifier.py` | 把「这一节 + 今天全部」渲染成一条消息 |
| `src/prebell/channels.py` | Server酱单通道，凭据只从环境变量读 |
| `src/prebell/ledger.py` / `verify.py` | 哈希链日志与验真 |
| `.github/workflows/prebell-remind.yml` | 4 条 cron + 手动触发 |
| `.github/workflows/prebell-daily.yml` | 每天 23:55 汇总与验真 |

```bash
cd 02-20Days-Challenge/src
python prebell/planner.py              # 改课表后重跑，三份产物一起更新
python prebell/planner.py --check      # 只校验不写文件
python prebell/run.py --dry-run --date 2026-11-16 --period P1 \
    --now 2026-11-16T00:20:09Z         # 本机预览，不联网不写真数据
python -m unittest discover -s prebell/tests -t . -v
```

本机不跑常驻程序、不自启、不建定时任务；所有重复执行都在 GitHub Actions。

## 历史资产（原样保留）

`src/prebell.py`、`src/resolve.py`、`src/weeks.py`、`src/chain.py`、`src/verify.py`、
`src/timetable.json`、`preview.html`、`iterations/001–004`、`src/PREBELL.md` 与
11-10 起的全部日志，都是被迭代掉的旧版本真实过程数据，**不删、不改、不回填**。
它们不属于当前运行程序，也不计入 3.0 版的运行窗口。
