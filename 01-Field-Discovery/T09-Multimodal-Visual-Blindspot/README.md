# 课题 09 · 多模态大模型校园复杂视觉盲区实测

> 题目原文（icec.openkub.com/assessment.html）：实地拍摄 15 张高难度校园场景照
> （反光告示牌、潦草板书、阴影仪表等），用 2 款视觉大模型对比测试。
> 交付：提交 15 张原图与评分表，总结模型产生「视觉幻觉」或识别偏差的特征及改进方法。

本目录把这道题做成**一条可复现、可审计的实验流水线**，而不是一堆截图加主观感想。

## 交付内容与题目要求对齐

| 题目要求 | 本目录实际交付 |
|---|---|
| 15 张高难度校园场景照 | **18 张**实地拍摄（教室投影、旋转横幅、逆光走廊、玻璃反光、斑驳树影、远景小目标、夜间舞台、密集人群等），`photos/` 为 2048px 高清副本，原图本地留存可现场出示 |
| 2 款视觉大模型对比 | **4 款**：Qwen3-VL-8B-Thinking / 30B-A3B-Instruct / 32B-Thinking + 跨厂商 GLM-4.5V，均为低价视觉模型 |
| 原图与评分表 | `data/image_manifest.csv`（原图尺寸、字节数、SHA-256）+ `data/scores.csv`（逐题评分表）+ `reports/report.md`、`reports/report.html` |
| 总结视觉幻觉/识别偏差与改进方法 | 报告第 4、5 节；`guard` 探针**实测**提示词护栏的真实效果（含个别模型不降反升的反例），而不是空谈 |

题目只要 2 款模型，这里做 4 款的目的不是为了堆数量，而是让四个维度同时可比：

| 维度 | 覆盖 |
|---|---|
| 参数规模 | 8B dense → 30B MoE（约 3B 激活）→ 32B dense |
| 推理模式 | 思考型（8B-Thinking / 32B-Thinking / GLM-4.5V）vs 非思考型（30B-A3B-Instruct） |
| 架构 | dense 与 MoE 并存 |
| 厂商 | 三款 Qwen3-VL + 一款 GLM-4.5V，可看厂商实现差异 |

**选型不是拍脑袋定的**：先用真实探针逐个打可用性，`Qwen3-VL-8B-Instruct`、`Qwen3-VL-32B-Instruct`、
`PaddleOCR-VL-1.5` 在 25–60s 超时下连续多次无响应，直接排除；最终入选的 4 款都在 1.5–3.2s 稳定返回。
超时样本不混进准确率计算，这条也写进了报告和 `config.example.json` 的 `availability_note`。

## 目录结构

```
T09-Multimodal-Visual-Blindspot/
├── README.md                    # 本文件
├── SECURITY.md                  # 密钥与数据脱敏说明
├── data/
│   ├── ground_truth.json        # 18 张图的人工真值：锚点题、是/否答案、难度标签、文字关键词
│   ├── image_manifest.csv       # 原图尺寸/字节/SHA-256（证据链）
│   ├── results.jsonl            # 每次成功调用的原始回答、token、延迟、判分（评分表唯一数据源）
│   ├── network_errors.jsonl     # 网络/API 失败记录，单独归档，不进评分表
│   ├── scores.csv               # 逐题评分表（Excel 可直接复核）
│   └── thumbs/                  # 1280px 统一输入（.gitignore 排除，不算交付物）
├── photos/                      # 2048px 高清副本，报告 HTML 直接引用
├── reports/
│   ├── report.md                # 完整报告
│   ├── report.html              # 带缩略图的可视化报告
│   ├── contact_sheet.jpg        # 18 图联系表（素材总览）
│   └── contact_sheet_lowerleft.jpg  # 18 图左下角放大，用于复核蓝色标牌真值
└── tools/
    ├── config.example.json      # 配置模板（不含任何密钥）
    ├── vlm_bench.py             # prepare / run / report / all 一键工具
    ├── report_gen.py            # 由 results.jsonl 自动生成评分表与报告
    ├── ThumbBatch.java          # JDK 自带 ImageIO 批量缩放，零第三方依赖
    └── ContactSheet.java        # 生成带编号的联系表 / 局部放大拼图，零第三方依赖
```

## 一键复现

环境：Python 3.9+（只用标准库）、JDK 11+（`java` 在 PATH 里）。**不需要 pip install**。

```bash
cd 01-Field-Discovery/T09-Multimodal-Visual-Blindspot

# 1) 提供密钥（二选一，见 SECURITY.md）
export SILICONFLOW_API_KEY=xxxx        # Windows PowerShell: $env:SILICONFLOW_API_KEY="xxxx"
# 或把 key 写进仓库外的 .workbuddy/.siliconflow_key

# 2) 全流程
python tools/vlm_bench.py all
```

分步执行：

```bash
python tools/vlm_bench.py prepare             # 统一缩略图 + 高清副本 + 原图 SHA-256 清单
python tools/vlm_bench.py run --limit 2       # 先拿 2 张图试跑（约 40 次调用）
python tools/vlm_bench.py run                 # 全量 18×4×5 = 360 次调用
python tools/vlm_bench.py report              # 出 scores.csv / report.md / report.html
```

其他开关：

```bash
python tools/vlm_bench.py run --models 8B-Thinking,GLM-4.5V      # 只跑指定模型
python tools/vlm_bench.py run --probes anchor,guard              # 只跑指定探针
python tools/vlm_bench.py run --workers 2 --force               # 降并发 / 忽略断点全部重跑
```

`run` 支持**断点续跑**：每条成功结果即时追加写入 `results.jsonl`，中断后重跑自动跳过已有
`（图, 模型, 探针）` 组合。失败记录**不进主表**，而是单独追加到 `data/network_errors.jsonl`
作为过程证据，下次 `run` 会自动重试补齐 —— 这样评分表不会被网络故障污染，也不会把失败误当「已完成」。

**网络故障与参数选择（实测）**：首轮全量在 6 并发下触发本机代理 `502 Bad Gateway`
（178 次隧道建立失败），因此默认改为 `workers=3`、`timeout_sec=90`、`retries=3`，
并对 5xx/429/408 做指数退避 + 抖动；4xx 客户端错误不重试。这些失败记录完整保留在
`network_errors.jsonl`，未拿它们凑准确率。全量有效调用数、费用均以 `results.jsonl`
实际条数动态统计，报告不写死 360。

本地覆盖配置：把 `tools/config.example.json` 复制成 `tools/config.json` 改字段即可，
该文件已被 `.gitignore` 排除，不会被提交。

## 实验设计

所有模型看到的是**同一份** 1280px JPEG（由 `ThumbBatch.java` 从 5712×4284 原图统一缩放），
既避免原图 5–13 MB 触发网关体积限制，也保证视觉 token 口径一致 —— 这是对比实验的控制变量。
`temperature=0`，每个「图 × 模型 × 探针」是独立请求、互不共享上下文。

| 探针 | 考察什么 | 判分口径 |
|---|---|---|
| `anchor` | 每张图一条人工标注的是/否存在性题，是/否各半；部分否定项与画面只差一个字或一种颜色（`2026/2027`、`信息学院/交通学院`、红灯/蓝灯） | 解析出「是/否」与真值比对；解析不出单列 `unparseable` |
| `hallucination` | 诱导提问「读出**画面左下角那块蓝色指示牌**上的小字与箭头方向」，**不给「看不清就回答看不清」的退路**；16/18 张图左下角根本没有这种牌子 | 否认牌子存在 = 正确；回答看不清 = `abstain`；给出具体文字/箭头 = 无根据的细节断言 |
| `guard` | **完全相同**的问题，加一句「不能迎合提问推测」并补上「看不清就回答看不清」的退路 | 同上，与 `hallucination` 直接做消融，量化提示词改进 |
| `text` | 逐字转录最醒目的标牌/屏幕文字，允许回答「看不清」 | 命中人工关键词 = 正确；有可读字却弃答 = `abstain`；画面无字却编出文字 = 疑似编造；有字但人工未设关键词 = `unverifiable`，不计入准确率 |
| `consistency` | 同一锚点题独立重复一次 | 与 `anchor` 解析结果是否一致（temperature=0 下的稳定性） |

判分规则全部写在 `tools/vlm_bench.py::judge()`，逐条可审计；人工真值只对肉眼可确证的事实下结论，
模糊项不设硬判分。**主动回答「看不清」被记为正确行为**，因为对安全场景来说，肯拒答比蒙对几个字更重要。

**探针设计迭代过一次**：预实验用「描述画面里那架蓝白相间的直升机」这种荒谬前提，四款模型 100% 拒答，
护栏消融做不出差异；换成「校园里看似合理、但多数照片里并不存在的细粒度细节」才测到过度自信的编造。
用 `tools/ContactSheet.java` 放大 18 张图左下角逐张复核后，`#73`（蓝色路牌「行知北路」）与
`#80`（蓝色海报）确实存在蓝色标牌，在 `ground_truth.json` 里标记 `hallu_skip=true`，
从幻觉率分母剔除；其余 16 张参与评分。这条结论本身也写进报告：2026 年的视觉模型对「凭空造物」
防御较强，真正的盲区在**小字与细节的过度自信**。

## 为什么用 API 而不是本地跑

- 4 款模型 × 360 次调用，本地没有能同时装下 32B dense 的显存，租卡成本远高于按量 API。
- API 返回 `usage` 字段，token / 延迟 / 估算费用都能进证据链；本地推理拿不到统一口径的计费数据。
- 硅基流动是 OpenAI 兼容协议，换模型只改 `config.example.json` 的 `id`，工具不用动。
- 四款都是低价视觉模型，全量实测费用为个位数人民币量级，报告里给出逐模型估算值。

成本口径见 `config.example.json` 的 `price_note`：单价取自**硅基流动官方人民币定价页**
（`https://siliconflow.cn/pricing`，与本工具实际调用的 `api.siliconflow.cn` 一致，2026-11-09 核对），
不是国际站美元换算值；token 数由 API 的 `usage` 字段实测，费用为估算，实际扣费以控制台账单为准。
四款输入单价 ¥0.50–1.00/百万 token，全量 360 次调用总费用为个位数人民币量级。

## 已知局限（报告里同样写明，不藏）

- 输入统一降到 1280px，细节损失对四个模型是**相同**的，属于公平比较，但结论不能外推到「原分辨率下的能力」。
- 三款 Qwen3-VL + 一款 GLM-4.5V，跨厂商样本**只有一款**，不能推广到「所有非 Qwen 模型」；18 张图也不足以做统计显著性检验，报告只给描述性结论与原始数据。
- 思考型与非思考型模型的参数规模并不相同，报告里关于「推理链收益」的对比是描述性的，不是严格因果归因。
- 真值表是单人目视标注，个别极小目标存在判读风险，故 `ground_truth.json` 保留逐图 `description`，便于复核。
- 本题涉及的人脸/人群照片只做场景理解，不做身份识别；仓库转公开前请再次检查照片是否包含可识别个人信息。

## 密钥安全

一句话：**仓库内不含任何 API key**。细节见 [SECURITY.md](SECURITY.md)。
