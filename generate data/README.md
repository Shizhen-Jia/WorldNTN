# 第一版多星座 FSPL 数据生成

入口是 [main.ipynb](main.ipynb)。其余 `.py` 文件提供 CSV 读取、射频计算、换星状态机、评分和训练视图。只读取已经生成的轨道 CSV，不下载星历、不修改原 CSV。

本实现参考 `literature review/plan.jpg` 与《多星座宽带LEO_WorldModel_训练测试数据采集与生成计划》，以本次用户提出的简化范围为准：一对 victim 链路、一对 aggressor 链路、单活动同频下行、固定增益与功率、只计 FSPL 和热噪声。没有实现原长计划中的阵列方向图、背景用户、多波束调度、导频扫描、报告延迟或完整切换协议。

## 这些输入能否用于第一版

可以。图中的 A 是 victim 地面站，A2 是其当前卫星；B 地面站连接某颗 B 星，该星在 A 处形成干扰。代码不硬编码编号 B1，而是随 B 的连接变化。

默认训练输入包括：

- 历史每一时刻服务链路的 SINR、SNR、INR；
- 干扰到达方向在 A 的 ENU 系中的单位向量，日志另存方位角、仰角；
- 全部输入 A/B 目录的历史 ECEF 位置和有效性 mask；
- 当前服务星索引、已知换星动作和目标星索引，以及缺测/无链路标志。

卫星 ID 用于关联位置与动作，不需要直接当连续数值送入网络。位置历史默认不附加速度；速度保存在公开轨道文件中，后续可用 `TrainingView(..., include_velocity=True)` 启用。触发器的窗口分数和连接年龄也保存，但默认不进入最小特征集；可用 `include_controller_state=True` 启用。

SINR、SNR、INR 在同一噪声定义下满足

`SINR_dB = SNR_dB - 10 log10(1 + 10^(INR_dB/10))`。

因此可以同时记录三者做校验，但它们不是三个独立自由度。第一版假设这些量能准确、即时观测；现实接收机能否把总干扰分解出精确 INR，是后续测量模型的问题。

**固定方向无关的增益会消除“转动接收方向以压制干扰”的机制。** 此版同一时刻切换 A 星只改变期望信号及后续驻留，不改变 B→A 干扰功率。方向仍可帮助根据轨道推断干扰源变化，但不会作用于增益。这适合验证时序、数据接口和采集策略；仅凭该版不能证明 world model 学会了阵列方向避干扰。固定功率、准确轨道和确定性 B 规则也使环境较容易解析预测，应保留解析/规则基线。

## 推荐功率与物理模型

推荐第一版每颗**当前活动卫星在整个信道上发射 10 W**。与原方案的单波束标称功率一致；这里不建多波束，不能把 10 W 解读为全星平台功率，也不再乘一次带宽。

| 参数 | 默认研究值 |
|---|---:|
| 中心频率 / 带宽 | 20 GHz / 250 MHz |
| 两方卫星发射功率 | 10 W，单活动卫星、全信道 |
| 两方固定发射增益 | 30 dBi |
| 两地面站固定接收增益 | 30 dBi |
| 温度 / 噪声系数 | 290 K / 6 dB |
| A 位置 | 39.95697°N，−105.16033°E，1660 m |
| B 位置 | A 以东约 1 km，相同椭球高 |

自由空间损耗采用 `L = 20 log10(4πdf/c)`；接收功率为 `P_rx,dBW = 10 log10(P_tx,W) + G_tx + G_rx − L`。[ITU-R P.525](https://www.itu.int/rec/R-REC-P.525-5-202411-I/en)

噪声为 `N = k T B × 10^(NF/10)`，本配置约 −84.00 dBm；先在 W 域计算 `S/(I+N)`、`S/N` 和 `I/N`，再转 dB。[热噪声及噪声系数定义](https://www.mathworks.com/help/phased/ug/receiver-preamp.html)

| 斜距 km | 10 W 下无干扰 SNR dB |
|---:|---:|
| 550 | 10.72 |
| 600 | 9.96 |
| 1000 | 5.53 |
| 1500 | 2.01 |
| 2000 | −0.49 |

这组值给出可解释的初始链路余量，而不是拟合某家商用系统。主 notebook 有同一公式生成的表格，可调频率、带宽和增益后重新查看。两方同时加大发射功率不能消除同频干扰；干扰占主导时，SINR 上限主要取决于 S/I。

只让 B 当前服务星发射，其余 B 星没有活动业务辐射。B 星必须在 A 地平线以上才贡献干扰，但不套用 A 的 25°接入仰角门限：一个低仰角外方星仍可能干扰 A。B 是否发射由 B 地面站处的连接决定，故 B 站位置虽然不是 A 模型输入，却是仿真必需配置。第一版 B 不对 A 动作作出响应。

## 输入 CSV 与时间轴

建议选 `generate satellite` 输出的 `*_all_states.csv`。在上游 `scenario.json` 设置 `write_all_states=true`，然后重跑所需真实/虚拟 tracker。需要包含当时未被 A 看到、但可能被 B 看到的卫星。默认拒绝 visible-only CSV；`allow_partial_catalog=True` 仅用于明确标注的缺目录诊断，不能恢复被裁剪的轨迹。

每一方可以选 `[真实 all_states CSV, 一种虚拟 all_states CSV]`。同一 `(Time, Satellite ID)` 重复会报错，不能混用同一星座的获批补全与自定义替代场景。`amazon`、`Amazon Leo` 自动映射到 `kuiper`。

需要 `Time`、`Satellite ID`（或 `Name`）、三个 ECEF 位置列 `x/y/z_ECEF (m)`、三个速度列 `vx/vy/vz_ECEF (m/s)`。ENU 坐标依赖原观测站，不能直接挪给 B。默认读取并验证旁边的 `metadata.json`，拒绝失败/未完成输出；外部无 sidecar CSV 可以显式 `allow_unverified_csv=True`，前提是自行核实坐标、单位和覆盖范围。旧无时区时间需显式设置 `assume_naive_utc=True`。

读取分两遍按块完成，不拼接整个多百万行 DataFrame。时间轴来自 upstream metadata，保留完全没有卫星记录的时间点；缺轨道数据用 mask 表示，不插值、不前向填充。输入目录在上游已被排除的低轨/DTC对象不会在这里恢复。A/B 必须采用完全一致的 UTC 采样网格；可用 `start_time_utc` 与 `max_steps` 选择其子区间。

**采样间隔决定换星反应时间。** 120 秒 CSV 的下一时刻就是 120 秒后，不能据此声称完成了秒级动作。建议在上游生成 1–5 秒网格；默认触发窗口以采样点计，5 点窗口的样本覆盖跨度为 `4Δt`，对应最近 5 次质量检查。

## 连接与换星规则

B 初始选在自身地点满足 `elevation >= min_elevation` 且 `SNR >= min_snr` 的卫星中，连续剩余可接入采样数最长者，之后保持，直到 SNR 或可见性不合格，再在该采样边界重新选择。只统计连续覆盖，不把下一次过境累加进去；同分按稳定卫星 ID。轨迹尾部的剩余连接时长受 CSV 截断，B 日志标明这一点，不外推未知时段。

A 初始可选同样的 `longest_remaining`，也可选 `random` 或 `max_snr`。连接建立后，SNR 降到接入门限以下仍保留当前连接并采集低质量样本，直到触发切换；不会因为用于筛选候选的 SNR 门限而跳过“两次 5 分”的机制。

默认触发规则：

| 当前 SINR | 分数 |
|---|---:|
| `< sinr_min_db` | 5 |
| `[sinr_min_db, middle_start_db)` | 3 |
| `[middle_start_db, highest_start_db)` | 2 |
| `>= highest_start_db` | 1 |

默认边界 0 / 3 / 6 dB，窗口 5 点，累计 **≥10** 触发。这里按“两次 5 分足够”的要求使用 ≥ 而非 >。窗口未填满也检查；累计达到阈值后，在本时刻发出动作，下一个采样时刻执行。

可见性丢失或没有连接时，SINR 记缺失、计 5 分，不伪造为 0 dB。默认仍按窗口触发；`force_on_geometry_loss=True` 可显式开启失去几何资格时立即发出下一步切换的工程对照。无干扰时 SINR=SNR，只要 SNR 跌到 SINR 最低门限以下，两次 5 分就足够触发；具体轨迹也可能先退出接入仰角范围。默认 SNR 接入与 SINR 最低门限同为 0 dB，分开修改时边界不再相同。

每次实际换星成功后清空旧窗口，从新星本时刻样本重新计分；没有合法备用星时记录 `blocked_no_candidate`，保留当前状态和计分，不重复选择当前卫星来假装完成切换。最后一个采样时刻不发出无法执行的终端动作。没有额外 RF 转向停顿或协议随机失败；动作固定延迟一个采样周期，不宣称是标准化 handover 时延。

若把窗口改到 10 点，优质样本每次 1 分也会达到 10。代码会提示这种周期性切换配置；可保持 5 点窗口，或明确改变高区分数/总门限。

## 为什么先用随机换星

合法随机选择适合采集初版动作结果：能覆盖不同备用星，不会只生成贪心最优方向的样本。当前和下一采样时刻都满足接入条件、且不同于当前星的候选才可选。下一步可见性/SNR来自固定轨道的公开预测，**不读取未来干扰/SINR 来筛目标**。选择概率记录为 `1/候选数`，固定 seed 可复现。

同时保留两个对照：`max_snr` 偏向当前/执行时刻的强期望信号，`longest_remaining` 偏向连续驻留。三者共享相同触发逻辑。第一版没有宣称其中某个策略全局最优；随机是探索采集策略，未来可以在同一基础场景下比较预测策略。

仅观察已执行动作不能得到所有其他动作的真实结果。不同 seed 会采到不同连接，但“同状态下所有候选动作的反事实评分”需要额外分支重跑，本版没有把未连接星的潜在 SINR 伪装成测量。多步 `prediction_samples>1` 的标签沿实际日志中的后续动作演化，不代表固定当前动作一直不变的反事实 rollout；先用默认一步预测。

## 换星后的分数与成功标签

对从新连接生效到下一次连接改变之前的观测区间，令驻留时长为 D，低于 SINR 最低门限或无链路的累计时间为 O，定义

`Q = Σ Δt × log2(1 + 10^(SINR_dB(t)/10))`

`score = α D/T_ref + β Q/T_ref − γ O/T_ref − handover_cost`。

默认 `T_ref=60 s, α=1, β=1, γ=2, handover_cost=0.05`。Q 是与 SINR 单调相关的频谱效率积分，避免直接累加 dB 的负值、单位和采样率问题；固定带宽下也与理想服务量相关。未观测/失联的 Q 为 0。驻留奖励保留用户希望的长连接偏好，同时用 outage 惩罚防止“长时间无服务仍高分”。

积分用左端采样值覆盖 `[t_k,t_{k+1})`，最后一个时间戳后不外推。D 包含低质量时段，另存 `usable_service_seconds`；可调 α、β、γ 形成其他偏好。初始连接也有描述性分数，但没有 `origin_action_id`，不是换星动作样本；训练动作评分时需筛 `is_action_outcome=True`。

完整连接段可用 `score >= success_score_threshold`（默认 2）定义质量成功。该阈值是研究标签设置，不是通信标准，也不是切换执行成功标志。最后一段如果因 CSV 结束而停止观察，标为 `right_censored=True`，`score_label_valid=False`，质量成功标签为空；不能把这段的部分观测分数直接当完整监督标签。所有得分只放在 `labels/`，不进入事先的观测。

## 输出、训练接口与复现

```text
outputs/<victim>_vs_<aggressor>_<UTC>_seed<seed>/
  manifest.json                 # 完成状态、输入/代码哈希、分组、来源范围
  quality_report.json           # 分数档位、SINR分布、阻塞/换星、有效标签数量
  window_index.csv              # 历史窗口与未来标签区间
  public/
    observations.csv            # 仅已连接方向的观测及本方控制状态
    actions.csv                 # 本时刻动作、目标、下一步生效时刻、采样概率
    executions.csv              # 实际切换结果
    geometry.npz                # 所有输入 A/B 星的位置/速度/ID及有效性mask
    config.json                 # 本方已知设置和最小特征允许列表
  labels/
    transitions.csv             # 一步实际观测标签
    link_segments.csv           # 驻留、积分质量、结果分数及删失标志
  private/
    simulation_config.json      # 完整配置，含 B 地面站与策略
    aggressor_trace.csv         # B 实际连接及剩余时间真值
    power_truth.csv             # S、I、N 与实际活动 B 星
```

`TrainingView(run_dir).sample(i)` 返回 `inputs` 和 `labels`。inputs 只取历史范围、当前已发出动作和已知几何；缺测值填 0 并提供 mask。默认不读取 private 或 link_segments。`INR=0` 的线性值对应 dB 未定义，日志将 `inr_db` 留空，用 `interference_present=False`、`inr_linear=0` 区分无干扰与有效的 0 dB INR。

多个重叠滑窗、随机 seed 和策略变体不能随机拆到 train/test。默认按相同源 CSV 哈希及地面站生成同一组 ID；同一输出目录下发现同组被写入不同 split 会报错。更换快照但仍是相邻日期/相近轨迹时，应手动指定共同 `scenario_group_id`，自动哈希不解决跨快照近重复识别。归一化、模型训练和大规模场景采集不在本次代码中执行。

## 运行和验证

```bash
cd "/home/shizhen/my_project/WorldNTN/generate data"
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pytest -q tests
.venv/bin/python tests/smoke_main.py
```

选择此 Python 内核打开 `main.ipynb`，设置路径和配置后顺序运行。没有找到合适输入时 notebook 提示选择/生成 all_states CSV，不创建伪造的生产数据。`tests/smoke_main.py` 只在临时目录使用 8 个时间点的人工几何，执行所有 notebook 单元；这些人工坐标仅用于管线诊断，不是轨道仿真或商业数据。
