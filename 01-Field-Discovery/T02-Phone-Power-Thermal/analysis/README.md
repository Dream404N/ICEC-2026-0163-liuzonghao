# 分析脚本

把 `raw_data/` 里的原始 CSV 变成图表和结论。**原始 CSV 不做任何手工修改**，所有加工都在这一步完成，保证可复现。

## 本次定稿实际用的是 `summarize_real.py`

```bash
python summarize_real.py        # 零第三方依赖，无需 pip install
```

输出 `summary.md`（如实结论稿）与 `figures/discharge.svg`（电量曲线）。
只读真实 CSV，三个完整工况出曲线与描述性统计，相机录像工况只有 2 点、单列端点对比，
**不插值、不补点、不做统计检验**。局限与理由见 `../DATA_QUALITY.md`。

下方 `analyze_t02.py` 是早期写的完整版流程，依赖 numpy / pandas / matplotlib 且假定 4 工况齐整；
因相机工况采样密度不足、起始温度不齐，**本次不运行**。若将来补齐 7 点后要跑它，
请把 `--out` 指到别的目录，避免覆盖本次定稿的 `summary.md`。

## `analyze_t02.py` 用法（本次未运行）

```bash
pip install -r requirements.txt
python analyze_t02.py --raw ../raw_data --out .
```

## `analyze_t02.py` 的目标输出（本次未生成）

| 文件 | 内容 |
|---|---|
| `completeness.csv` | 每个会话的完整性核验：采样点数、跨度、是否检出充电、数据通道（几行走 root）、收尾行 elapsed |
| `summary.csv` | 逐工况指标：平均/峰值电流、平均/峰值功率、积分电量、放电速率、温升 |
| `summary.md` | 可直接引用的结论稿（含统计检验结果） |
| `figures/fig1_current.png` | 4 个工况的电流时序（2×2 分面） |
| `figures/fig2_temperature.png` | 电池温度时序（同一坐标系叠放） |
| `figures/fig3_level.png` | 电量下降曲线 |
| `figures/fig4_bars.png` | 平均功率 / 温升 / 积分电量三联柱状图 |

## 方法说明

| 指标 | 方法 | 为什么这样做 |
|---|---|---|
| 积分电量 (mAh) | 对 I(t) 做梯形积分 `∫|I|dt / 3600` | 工况内负载不恒定（相机启动、游戏加载都有电流尖峰），「平均值 × 时长」会低估 |
| 放电速率 (%/h) | 电量对时间做最小二乘线性拟合取斜率 | 首尾两点相减对单点抖动极其敏感，拟合能滤掉采样噪声 |
| 工况差异检验 | Kruskal-Wallis 非参数检验 | 每工况仅 6 个点，不满足正态性，不能用单因素 ANOVA |
| 温度 | 取 `batt_temp_c`（电池）与 `soc_thermal_c`（SoC 类热区）两路 | 电池温度反映整机热积累，SoC 温度反映芯片局部热点，两者不同步 |

## 已知处理

- **电流符号**：CSV 按「负值 = 放电」记录。若首次数据出现相反符号（某些厂商约定不同），脚本绘图时统一取绝对值，**不修改原始 CSV**。
- **收尾行**：`is_final=1` 的行不进入曲线，只用于 `completeness.csv` 校验会话是否被提前中断。
- **缺失值**：某字段全部不可读时（如天玑平台 GPU 频率），指标显示为 `-` 而不是 0，避免把「读不到」误当成「耗电为零」。
