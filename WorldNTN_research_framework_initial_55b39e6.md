# WorldNTN：基于 Physics-Grounded World Model 的自主与韧性非地面网络研究框架

> **核心定位**：不把 LLM 作为必要组件。研究的技术核心是一个 **physics-grounded、action-conditioned、uncertainty-aware 的 NTN World Model**，利用 LEO 轨道与几何的确定性先验，只学习网络中真正不确定、难以解析建模的动态；同一个 World Model 同时服务于 **预测式网络编排（Predictive Orchestration）** 与 **异常检测/自主防御（Resilience & Security）**。

---

## 0. 一句话版本

传统 NTN Digital Twin 可以根据星历/轨道较容易地预测卫星位置、可见性、距离、仰角、名义 Doppler 和 FSPL，因此这些内容本身不应成为主要创新点。

本项目要研究的是：

> **Can an NTN learn a physics-grounded world model of its own dynamics, use the model to imagine the consequences of candidate actions before executing them, and detect/recover from abnormal conditions when the real network deviates from the predicted world?**

换成中文：

> **能否让 NTN 在确定性轨道物理模型之上，学习一个能够预测“网络如何演化、动作会造成什么后果”的 World Model，并利用这个模型完成主动资源编排、异常检测和自主恢复？**

---

# 1. 为什么不应该只做 “NTN Digital Twin”

LEO NTN 中相当多的未来状态本来就是高度可预测的。

给定卫星星历、UE 位置和时间，可以直接计算或高精度估计：

$$
\mathbf p_s(t),\quad
d_{u,s}(t),\quad
\theta_{u,s}(t),\quad
\phi_{u,s}(t),
$$

进一步得到：

$$
f_D(t),\quad
\tau(t),\quad
L_{\mathrm{FSPL}}(t),
$$

以及 satellite visibility window。

因此，如果所谓 Digital Twin 只是：

```text
TLE / Ephemeris
      ↓
Orbit Propagator
      ↓
Position / Elevation / Doppler / FSPL
```

技术难度和研究 novelty 都有限。

真正难的是轨道信息无法直接回答的问题，例如：

- 下一段时间的业务流量如何变化；
- 卫星负载和排队如何演化；
- weather / blockage / shadowing 对链路造成多少 residual degradation；
- 多用户、多卫星之间的干扰如何变化；
- 某个 handover / beam / power / association action 执行后，未来 KPI 会怎样变化；
- 当前性能突然下降是正常环境变化、拥塞、故障还是 jamming；
- 如果采取不同 mitigation actions，哪个未来结果最好。

这正是从 **Digital Twin** 转向 **World Model** 的意义。

---

# 2. Digital Twin 和 World Model 在这个项目里的区别

## 2.1 Digital Twin：描述“世界现在是什么”

在本项目中，Digital Twin 更适合作为 **physics backbone**：

$$
\mathcal{T}_{\mathrm{phys}}
$$

输入：

$$
\text{ephemeris},\ \text{UE location},\ t
$$

输出：

$$
c_t =
[
\text{visibility},
d,
\text{elevation},
\text{azimuth},
f_D,
\tau,
L_{\mathrm{FSPL}},
\ldots
].
$$

它主要描述 deterministic / semi-deterministic 状态。

---

## 2.2 World Model：学习“世界在 action 作用下会怎样演化”

World Model 要学习：

$$
p_\theta(s_{t+1:t+H}\mid s_{\le t},a_{t:t+H-1},c_{t+1:t+H}),
$$

其中：

- $s_t$：当前网络状态；
- $a_t$：控制动作；
- $c_t$：由 physics twin 提供的确定性上下文；
- $H$：预测 horizon。

关键区别是 **action-conditioned prediction**：

> 不只是预测“未来会怎样”，而是预测“如果我这样做，未来会怎样”。

例如：

$$
p(R_{t+1:t+H}\mid a_t=\text{stay on Sat A})
$$

和

$$
p(R_{t+1:t+H}\mid a_t=\text{handover to Sat B})
$$

应该不同。

这使 World Model 可以用于 counterfactual rollout，也就是在模型内部尝试多个未来。

---

# 3. 项目总体框架

推荐名称：

## **WorldNTN**
### *A Physics-Grounded World Model for Autonomous and Resilient Non-Terrestrial Networks*

总体结构：

```text
                    ┌───────────────────────────────┐
                    │   Deterministic Physics Twin │
                    │ orbit / geometry / FSPL /    │
                    │ Doppler / visibility         │
                    └──────────────┬────────────────┘
                                   │ c_t
                                   ↓
Network telemetry ───────→ ┌───────────────────────┐
                           │   NTN WORLD MODEL      │
Actions a_t ─────────────→ │                       │
                           │ latent dynamics        │
                           │ KPI prediction         │
                           │ uncertainty            │
                           │ counterfactual rollout │
                           └───────────┬───────────┘
                                       │
                   ┌───────────────────┴───────────────────┐
                   ↓                                       ↓
        Predictive Orchestration                  Resilience / Security
                   │                                       │
        association / handover                   anomaly detection
        beam / power / routing                   fault / jammer detection
        load balancing                           mitigation planning
                   │                                       │
                   └───────────────────┬───────────────────┘
                                       ↓
                                  Physical NTN
                                       │
                                       └──── telemetry feedback
```

这里完全不需要 LLM。

**World Model + Planner + Detector** 就可以形成闭环。

---

# 4. 最核心的研究思想：Physics learns what is known; AI learns what is unknown

建议把整个状态拆成两部分：

$$
s_t = (c_t,x_t).
$$

其中：

## 4.1 Physics context $c_t$

由解析模型直接得到：

$$
c_t =
[
\mathbf p_s,
d_{u,s},
\theta_{u,s},
f_D,
\tau,
L_{\mathrm{FSPL}},
V_{u,s}
].
$$

这里的 $V_{u,s}$ 表示 visibility。

---

## 4.2 Learned network state $x_t$

需要 World Model 学习：

$$
x_t =
[
\text{SINR residual},
\text{traffic},
\text{load},
\text{queue},
\text{interference},
\text{blockage},
\text{fault state},
\ldots
].
$$

因此可以写成：

$$
x_{t+1}
=
F_\theta(
x_{\le t},
c_{\le t+1},
a_t
)
+
\epsilon_t.
$$

或者更直观地写：

$$
y_t
=
y_{\mathrm{physics},t}
+
r_t,
$$

World Model 不重新学习整个 $y_t$，只学习 residual：

$$
r_{t+1}
=
F_\theta(r_{\le t},c_{\le t+1},a_t).
$$

这比 black-box 网络更合理，也更容易泛化。

---

# 5. 推荐的具体技术方案：Physics-Grounded Graph Latent World Model

我最推荐的不是普通 LSTM，也不是直接套一个大 Transformer，而是：

## **PG-GLWM: Physics-Grounded Graph Latent World Model**

原因是 NTN 天然可以表示成动态异构图：

$$
G_t=(V_t,E_t).
$$

---

## 5.1 节点

可以包含：

### Satellite node

特征：

$$
[
\mathbf p_s,
\mathbf v_s,
SOC_s,
load_s,
queue_s,
compute_s
].
$$

最初 MVP 不需要 battery/compute，可以只用：

$$
[
\mathbf p_s,
load_s
].
$$

### UE node

$$
[
\mathbf p_u,
traffic_u,
QoS_u,
serving\ satellite
].
$$

### Gateway node（后期）

$$
[
capacity_g,
load_g,
availability_g
].
$$

### Jammer / interference source

训练时不一定显式作为 node。

如果希望检测未知 jammer，更好的做法反而是：

> 正常训练数据中不存在 jammer node，模型只学习 normal dynamics。

---

## 5.2 边

例如：

- UE–Satellite；
- Satellite–Gateway；
- Satellite–Satellite ISL。

UE–Satellite edge feature：

$$
e_{u,s,t} =
[
d_{u,s},
\theta_{u,s},
L_{\mathrm{FSPL}},
f_D,
SINR,
R_{u,s},
visibility
].
$$

其中 deterministic 的部分来自 physics engine。

---

# 6. World Model 的内部结构

推荐四个模块：

```text
G_t + Physics c_t
       ↓
┌─────────────────┐
│ Graph Encoder   │
└────────┬────────┘
         ↓
        z_t
         │
a_t ─────┼─────────────┐
         ↓             │
┌───────────────────┐  │
│ Latent Dynamics   │  │
│ Model             │  │
└────────┬──────────┘  │
         ↓             │
   ẑ_{t+1:t+H}         │
         │             │
 ┌───────┴────────┐    │
 ↓                ↓    ↓
KPI Decoder   State Decoder   Reward/Cost Head
```

---

## 6.1 Graph Encoder

用 heterogeneous GNN / graph attention network：

$$
z_t = E_\phi(G_t,c_t).
$$

它将规模较大的 NTN 图压缩为 latent representation。

如果网络规模较小，第一版甚至可以不做全图 latent，只保留每个 UE 周围的 local subgraph。

---

## 6.2 Action-conditioned latent dynamics

核心：

$$
\hat z_{t+1}
=
F_\theta(z_t,a_t,c_{t+1}).
$$

多步 rollout：

$$
\hat z_{t+k}
=
F_\theta(
\hat z_{t+k-1},
a_{t+k-1},
c_{t+k}
).
$$

这里 $c_{t+k}$ 不需要预测，因为 orbit 可以直接计算。

这是 NTN 相比普通 mobile network 一个非常大的优势：

> **World Model 不需要浪费 capacity 学卫星运动，只需学习 physics-conditioned residual dynamics。**

---

# 7. Latent Dynamics 应该选什么 AI 方法

可以按照难度分三档。

## 方案 A：Graph Encoder + GRU/LSTM

最容易做。

$$
z_{t+1}=\mathrm{GRU}(z_t,a_t,c_{t+1}).
$$

优点：

- 训练稳定；
- 快；
- 很适合 first prototype。

缺点：

- “World Model”味道稍弱；
- 长 horizon prediction 可能容易 drift。

建议作为 baseline。

---

## 方案 B：Graph Recurrent State-Space Model（推荐主模型）

可以做成类似 RSSM 的 stochastic latent dynamics：

$$
h_{t+1}
=
f(h_t,z_t,a_t,c_{t+1}),
$$

$$
p(z_{t+1}\mid h_{t+1})
=
\mathcal N(\mu_\theta,\Sigma_\theta).
$$

observation encoder 提供 posterior：

$$
q(z_{t+1}\mid o_{t+1},h_{t+1}).
$$

这样模型天然具有：

- uncertainty；
- latent rollout；
- model-based planning；
- anomaly likelihood。

这是我认为最适合完整 paper 的版本。

可以把它称为：

### **Physics-Conditioned Graph RSSM**

---

## 方案 C：Graph-JEPA / Predictive Representation World Model

这是更新、也更有“AI-native 6G”味道的做法。

不是强迫模型重建所有 telemetry：

$$
\hat o_{t+1}\approx o_{t+1},
$$

而是预测 future latent embedding：

$$
\hat z_{t+k}
=
F_\theta(z_{\le t},a,c),
$$

并让：

$$
\hat z_{t+k}\approx
\mathrm{stopgrad}(E(o_{t+k})).
$$

优势：

1. 不需要精确重构所有噪声；
2. 学到对控制有意义的 representation；
3. 特别适合 anomaly detection；
4. 可以做 self-supervised pretraining。

建议作为 **第二阶段/更有 novelty 的模型**。

---

# 8. 为什么不建议第一版用 Diffusion World Model

Diffusion 可以建模复杂多模态未来：

$$
p(s_{t+1:t+H}\mid s_t,a_t).
$$

但它用于实时 NTN control 有明显问题：

- rollout 成本高；
- candidate actions 多时采样次数会快速增加；
- latency 不容易控制。

因此它比较适合作为未来增强，而不是第一版。

第一篇更建议：

> **Graph-RSSM / Graph-JEPA + Model Predictive Control**

---

# 9. World Model 训练目标

建议不要只有 single-step MSE。

总 loss 可以写成：

$$
\mathcal L
=
\lambda_1\mathcal L_{\mathrm{KPI}}
+
\lambda_2\mathcal L_{\mathrm{latent}}
+
\lambda_3\mathcal L_{\mathrm{rollout}}
+
\lambda_4\mathcal L_{\mathrm{unc}}
+
\lambda_5\mathcal L_{\mathrm{phys}}.
$$

---

## 9.1 KPI prediction loss

预测：

- SINR；
- throughput；
- satellite load；
- queue；
- outage probability。

例如：

$$
\mathcal L_{\mathrm{KPI}}
=
\sum_{k=1}^{H}
w_k
\|
\hat y_{t+k}-y_{t+k}
\|_2^2.
$$

---

## 9.2 Latent prediction loss

如果使用 JEPA：

$$
\mathcal L_{\mathrm{latent}}
=
\sum_{k=1}^{H}
\|
\hat z_{t+k}
-
\mathrm{sg}(z_{t+k})
\|_2^2.
$$

---

## 9.3 Multi-step rollout loss

需要特别防止：

> single-step prediction 很准，但 rollout 20 步后崩掉。

因此训练时直接做：

$$
\hat s_{t+1:t+H}
$$

并计算 multi-step loss。

---

## 9.4 Uncertainty loss

如果输出 Gaussian：

$$
p(y_{t+k})
=
\mathcal N(
\mu_{t+k},
\Sigma_{t+k}
),
$$

则可以使用 NLL：

$$
\mathcal L_{\mathrm{unc}}
=
-\log
p_\theta(y_{t+k}).
$$

这对安全检测很重要，因为 anomaly 不能只看绝对误差，而应该考虑：

> 这个误差相对于模型本身的 uncertainty 是否异常。

---

## 9.5 Physics consistency loss

例如模型输出的 path-loss residual 不应该重新破坏 deterministic geometry trend。

可以加入：

$$
\mathcal L_{\mathrm{phys}}
=
\|
\hat y_t
-
(
y_{\mathrm{physics},t}
+
\hat r_t
)
\|^2.
$$

或者对某些完全 deterministic 的 state 直接不预测。

**最好的 physics constraint 是 architectural constraint，而不是仅仅加 loss。**

也就是说：

> 已知的 orbit / geometry 直接输入未来真值，不让 neural network 预测。

---

# 10. Branch A：Predictive NTN Orchestration

这是第一条应用主线。

World Model 的作用不是直接输出 action，而是提供：

$$
\text{candidate action}
\rightarrow
\text{predicted future}.
$$

---

## 10.1 最适合第一版的问题：Satellite Association + Handover

定义：

$$
x_{u,s}[t]\in\{0,1\},
$$

表示 UE $u$ 在时刻 $t$ 是否连接 satellite $s$。

约束：

$$
\sum_s x_{u,s}[t]=1.
$$

如果需要容量约束：

$$
\sum_u x_{u,s}[t]R_u[t]
\le C_s[t].
$$

---

## 10.2 目标函数

例如：

$$
J
=
\sum_{\tau=t}^{t+H}
\left[
\sum_u R_u[\tau]
-
\lambda_{\mathrm{HO}}N_{\mathrm{HO}}[\tau]
-
\lambda_{\mathrm{out}}N_{\mathrm{out}}[\tau]
-
\lambda_{\mathrm{bal}}L_{\mathrm{imbalance}}[\tau]
\right].
$$

然后不是用真实网络测试所有 action，而是在 World Model 中：

$$
\hat J(a_{t:t+H-1})
=
\mathbb E_{\mathrm{WM}}[J].
$$

选择：

$$
a^*
=
\arg\max_a
\hat J(a).
$$

---

# 11. Planner 不需要 LLM，也不一定需要 RL

这是非常重要的一点。

World Model 和 planner 可以完全分离。

推荐：

## **Model Predictive Control (MPC)**

每个时间 $t$：

1. 读取 real telemetry；
2. 更新 latent state $z_t$；
3. 枚举/采样候选 actions；
4. World Model rollout；
5. 计算未来 utility；
6. 选择最优 action；
7. 只执行第一步；
8. 下一时隙重新规划。

即：

$$
a_t^*
=
\arg\max_{a_t}
\mathbb E
\left[
\sum_{k=0}^{H-1}
\gamma^k r_{t+k}
\right].
$$

---

## 11.1 action space 小时

直接 enumerating top-K candidate satellites。

例如每个 UE 只考虑：

$$
K=3\sim 8
$$

个最有希望的 visible satellites。

---

## 11.2 action space 大时

可以使用：

- Cross-Entropy Method (CEM)；
- beam search；
- Monte-Carlo Tree Search；
- learned proposal policy + World Model evaluation。

第一版推荐 CEM 或 beam search。

---

# 12. 为什么这个方法比普通 DRL 更有研究价值

传统 model-free DRL：

$$
s_t
\rightarrow
\pi_\phi(a_t|s_t).
$$

它直接记 policy。

World Model：

$$
(s_t,a_t)
\rightarrow
p(s_{t+1},r_{t+1}).
$$

因此同一个模型可以：

- 换 objective；
- 做不同 counterfactual；
- 检测 anomaly；
- 解释 action consequence；
- 在攻击状态下重新规划。

所以 World Model 是一个 **reusable environment intelligence layer**，而不是一个 task-specific handover policy。

---

# 13. Branch B：World-Model-Based Anomaly Detection

这部分可以和 orchestration 共用同一个模型。

这是整个大框架最漂亮的地方。

World Model 在 normal network 上学习：

$$
p_\theta(o_{t+1}\mid o_{\le t},a_t,c_{t+1}).
$$

实际网络返回：

$$
o_{t+1}^{\mathrm{real}}.
$$

如果现实和 predicted world 明显不同：

$$
o_{t+1}^{\mathrm{real}}
\not\sim
p_\theta(o_{t+1}),
$$

则认为存在 abnormal condition。

---

# 14. Anomaly Score

可以设计成三个分量：

## 14.1 KPI residual

$$
A_t^{\mathrm{KPI}}
=
(
y_t-\hat\mu_t
)^T
\hat\Sigma_t^{-1}
(
y_t-\hat\mu_t
).
$$

这比普通 MSE 更合理，因为考虑 uncertainty。

---

## 14.2 Latent residual

$$
A_t^{\mathrm{latent}}
=
\|
z_t^{\mathrm{obs}}
-
\hat z_t^{\mathrm{pred}}
\|^2.
$$

特别适合 JEPA。

---

## 14.3 Likelihood score

$$
A_t^{\mathrm{NLL}}
=
-\log p_\theta(y_t|h_{t-1},a_{t-1},c_t).
$$

最终：

$$
A_t
=
\alpha A_t^{\mathrm{KPI}}
+
\beta A_t^{\mathrm{latent}}
+
\gamma A_t^{\mathrm{NLL}}.
$$

当：

$$
A_t>\eta
$$

触发 anomaly。

---

# 15. 为什么非常适合 jamming detection

正常情况下，geometry 可能预测：

$$
\Delta L_{\mathrm{FSPL}}
\approx 0.3\ {\rm dB}.
$$

但实际 SINR 突然下降：

$$
\Delta SINR=-12\ {\rm dB}.
$$

同时 satellite load 和 traffic 没有相应变化。

那么这一 observation 与 learned normal dynamics 的 likelihood 很低。

这意味着：

> “轨道物理无法解释当前变化，正常网络 dynamics 也无法解释。”

模型不需要一开始就知道 “这是 jammer”。

它首先只需要知道：

$$
\text{This state is abnormal.}
$$

---

# 16. 第一版安全研究最好先做 “Detection”，而不是强行做 Attack Classification

建议训练数据只包括 normal state。

测试加入：

- jammer；
- sudden blockage；
- traffic surge；
- satellite failure。

先回答：

> World Model 能不能检测 unseen abnormal dynamics？

这比训练一个：

$$
\text{normal/jammer classifier}
$$

更有研究意义，因为 supervised classifier 依赖 attack labels。

---

# 17. 第二阶段：Root Cause / Diagnosis

如果第一阶段成功，再研究：

$$
H_0=\text{normal}
$$

$$
H_1=\text{jamming}
$$

$$
H_2=\text{blockage}
$$

$$
H_3=\text{traffic congestion}
$$

$$
H_4=\text{satellite/gateway failure}.
$$

不需要 LLM，可以用两种方法。

---

## 方法 A：Structured Hypothesis Models

每个 hypothesis 有一个扰动 model：

$$
p(o_t|H_i).
$$

选择：

$$
H^*
=
\arg\max_i
p(o_t|H_i).
$$

---

## 方法 B：Small diagnosis head

World Model encoder freeze 后：

$$
z_t\rightarrow
\text{fault classifier}.
$$

只需要少量 attack labels。

这样可以形成：

> self-supervised normal-state pretraining + few-shot diagnosis。

---

# 18. Branch C：World-Model-Based Autonomous Recovery

Detection 以后，最关键的是不要使用固定 response：

```text
jammer detected → always handover
```

而是在 World Model 中测试 mitigation。

例如：

$$
\mathcal A_{\mathrm{mit}}
=
\{
\text{handover},
\text{beam nulling},
\text{power control},
\text{frequency switch},
\text{TN fallback}
\}.
$$

对每个 action：

$$
a_i
\rightarrow
\mathrm{WM}
\rightarrow
\hat s_{t+1:t+H}^{(i)}.
$$

计算：

$$
J_i
=
R_i
-
\lambda_1 P_{\mathrm{out},i}
-
\lambda_2 C_{\mathrm{HO},i}
-
\lambda_3 P_{\mathrm{TX},i}.
$$

然后：

$$
a^*
=
\arg\max_i J_i.
$$

这就形成：

$$
\boxed{
Predict
\rightarrow
Detect
\rightarrow
Recover
}
$$

---

# 19. 最重要的统一视角

Orchestration 和 Security 不是两个拼在一起的项目。

它们本质上是同一个机制：

## 正常情况下

$$
\text{World Model}
+
\text{counterfactual rollout}
\rightarrow
\text{best control action}.
$$

## 异常情况下

$$
\text{prediction mismatch}
\rightarrow
\text{anomaly}
\rightarrow
\text{counterfactual rollout}
\rightarrow
\text{best mitigation action}.
$$

可以在论文里概括为：

> **The same predictive model that tells the network what should happen under normal operation also provides the reference needed to recognize when the real system no longer behaves as expected.**

这应该成为整篇工作的核心 narrative。

---

# 20. 推荐的第一版系统模型

为了在较短时间内做出完整结果，第一版不要做整个 mega-constellation。

推荐：

- 一个有限地理区域；
- $N_u=8\sim 32$ 个 UE；
- 每个 UE 同时看到若干候选 LEO satellites；
- time slot：0.5–2 s；
- episode：2–10 min；
- horizon：5–30 steps；
- satellite motion：SGP4 / orbital propagator；
- channel：FSPL + shadowing / weather residual；
- traffic：AR / bursty / Markov-modulated traffic；
- jammer：固定或移动 terrestrial jammer。

第一版只做：

$$
\boxed{
association + handover + jamming
}
$$

后面再扩展 beamforming。

---

# 21. Environment 的具体状态定义

对于 UE $u$、satellite $s$：

$$
s_t =
\{
c_t,\,
q_u,\,
L_s,\,
I_{u,s},\,
SINR_{u,s},\,
R_{u,s},\,
x_{u,s}
\}.
$$

其中 physics context：

$$
c_t=
\{
\theta_{u,s},
d_{u,s},
f_{D,u,s},
L_{\mathrm{FSPL},u,s},
T_{\mathrm{remain},u,s}
\}.
$$

推荐加入一个非常 NTN-specific 的特征：

$$
T_{\mathrm{remain},u,s}
$$

即剩余可服务时间。

---

# 22. Action

第一阶段：

$$
a_t=x_{u,s}[t].
$$

也就是 association。

第二阶段：

$$
a_t=
[
x_{u,s},
P_s
].
$$

第三阶段：

$$
a_t=
[
x_{u,s},
P_s,
w_s,
f_s
].
$$

其中 $w_s$ 为 beamforming action。

---

# 23. Traffic Model

为了让 World Model 真正有东西可以学习，不应让整个 simulator 都 deterministic。

至少加入：

$$
\lambda_u(t)
=
\mu_u(t)+\epsilon_t.
$$

可以使用：

### AR(1)

$$
\lambda_{t+1}
=
\rho\lambda_t
+
(1-\rho)\mu
+
\epsilon_t.
$$

或 Markov-modulated Poisson process。

后面再使用真实 traffic trace。

---

# 24. Channel Residual

可以：

$$
L_{u,s}(t)
=
L_{\mathrm{FSPL}}(t)
+
L_{\mathrm{weather}}(t)
+
L_{\mathrm{shadow}}(t)
+
L_{\mathrm{misc}}(t).
$$

World Model 已知：

$$
L_{\mathrm{FSPL}}(t),
$$

只学习：

$$
r_t
=
L_{\mathrm{weather}}
+
L_{\mathrm{shadow}}
+
L_{\mathrm{misc}}.
$$

这就是 clean physics-grounded formulation。

---

# 25. Jammer Model

第一版可以很简单。

jammer 到 UE：

$$
P_J^{rx}(t)
=
P_J
+
G_J
+
G_{UE}
-
L_J(t).
$$

SINR：

$$
SINR_{u,s}
=
\frac{
P_{s,u}
}{
I_{network}
+
P_J^{rx}
+
N_0B
}.
$$

训练 World Model 时：

$$
P_J=0.
$$

测试时随机加入：

$$
P_J>0.
$$

这样可以严格测试：

> **unseen anomaly detection**。

---

# 26. 第一组实验：World Model 本身是否预测准确

需要先证明：

> World Model 真的学会 network dynamics。

指标：

### SINR prediction

$$
RMSE_{\mathrm{SINR}}(H)
$$

### Throughput prediction

$$
RMSE_R(H)
$$

### Load prediction

$$
RMSE_L(H)
$$

### Calibration

例如：

$$
P(
y_{t+k}
\in
[\mu-2\sigma,\mu+2\sigma]
).
$$

画：

> prediction error vs prediction horizon。

---

# 27. 第二组实验：Predictive Orchestration

比较：

## Baseline 1：Max-SNR

$$
s^*
=
\arg\max_s SINR_s(t).
$$

## Baseline 2：Max remaining visibility

## Baseline 3：Load-aware greedy

## Baseline 4：Optimization with perfect deterministic orbit only

也就是知道未来 geometry，但不知道 future traffic/interference residual。

## Baseline 5：Model-free RL

例如 PPO / SAC / DQN。

## Proposed

$$
\text{Physics-Grounded WM + MPC}.
$$

---

# 28. Orchestration Metrics

至少：

### Average throughput

$$
\bar R
$$

### 5th percentile throughput

$$
R_{5\%}
$$

### Outage probability

$$
P_{\mathrm{out}}.
$$

### Number of handovers

$$
N_{\mathrm{HO}}.
$$

### Load imbalance

例如：

$$
\sigma_L
$$

或 Jain's fairness index。

### Planning latency

$$
T_{\mathrm{decision}}.
$$

---

# 29. 第三组实验：Anomaly / Jamming Detection

测试不同：

- JNR；
- jammer distance；
- jammer duty cycle；
- burst jammer；
- unseen jammer power；
- multiple jammers。

---

# 30. Security Baselines

## Baseline 1：Energy threshold

## Baseline 2：SINR drop detector

$$
SINR_t-SINR_{t-1}<-\eta.
$$

## Baseline 3：Autoencoder

normal reconstruction error。

## Baseline 4：LSTM predictor

prediction residual。

## Baseline 5：Graph predictor without physics grounding

## Proposed

$$
\text{Physics-Grounded World Model anomaly score}.
$$

---

# 31. Detection Metrics

必须做：

$$
P_D
$$

$$
P_{FA}
$$

ROC / AUC。

另外非常建议：

### Detection delay

$$
T_{\mathrm{detect}}.
$$

### Detection vs JNR

$$
P_D(JNR).
$$

### False alarm under normal distribution shift

例如：

- traffic surge；
- weather change；
- high-load state。

这个非常重要，因为真正困难的不是检测一个很强 jammer，而是：

> **不要把正常网络变化误判成 attack。**

---

# 32. 第四组实验：Autonomous Recovery

攻击出现以后比较：

### No mitigation

### Always handover

### Always power boost

### Rule-based mitigation

### World-Model planning

指标：

- post-attack throughput；
- outage duration；
- recovery time；
- extra power；
- handover cost；
- mitigation success rate。

---

# 33. 最重要的 Ablation Study

这是论文能不能站住的关键。

---

## Ablation A：No Physics

World Model 自己学习所有 dynamics。

对比：

$$
\text{Black-box WM}
$$

vs

$$
\text{Physics-grounded WM}.
$$

期待：

- 训练更快；
- data efficiency 更高；
- OOD orbit / UE geometry 泛化更好。

---

## Ablation B：Physics Only

只有 Digital Twin：

$$
\text{orbit + FSPL + deterministic prediction}
$$

没有 learned residual。

证明：

> Digital Twin 可以准确描述 geometry，但无法充分预测 traffic / interference / anomaly。

---

## Ablation C：No Action Conditioning

模型预测：

$$
p(s_{t+1}|s_t)
$$

而不是：

$$
p(s_{t+1}|s_t,a_t).
$$

如果后者在 planning 明显更好，就证明：

> World Model 的价值不是普通 forecasting。

---

## Ablation D：Single-Step vs Multi-Step Training

证明 rollout loss 对 MPC 的重要性。

---

## Ablation E：Deterministic vs Uncertainty-Aware

对 anomaly detection 尤其重要。

---

## Ablation F：No Graph

将所有 features flatten 后用 MLP/Transformer。

证明 graph inductive bias 在动态 NTN topology 中有价值。

---

# 34. OOD Generalization：非常值得作为 paper 的亮点

World Model 最容易被 reviewer 问：

> “是不是只是在 simulator distribution 上拟合？”

因此必须测试 OOD。

例如：

### OOD-1：不同 satellite orbital plane

### OOD-2：不同 UE density

### OOD-3：不同 traffic distribution

### OOD-4：不同 jammer power/location

### OOD-5：部分 satellite failure

### OOD-6：训练没见过的 weather / shadowing intensity

如果 physics-grounded model 的泛化比 black-box 好，这会成为很强的结果。

---

# 35. Data Efficiency 实验也很有价值

训练数据只使用：

$$
10\%,25\%,50\%,100\%.
$$

比较：

$$
\text{Physics-grounded WM}
$$

vs

$$
\text{Black-box WM}.
$$

如果前者在少量数据下仍能表现好，就能支持一个非常强的观点：

> NTN 的 deterministic orbital structure 可以作为强 inductive bias，降低 world-model learning 的数据需求。

---

# 36. 推荐的最终模型版本

如果目标是 **poster + 后续完整 paper**，我建议最终采用：

## **Physics-Conditioned Heterogeneous Graph RSSM**

### Encoder

$$
E_\phi(G_t)
\rightarrow
z_t.
$$

### Deterministic hidden state

$$
h_{t+1}
=
f_\theta(
h_t,
z_t,
a_t,
c_{t+1}
).
$$

### Prior

$$
p_\theta(z_{t+1}|h_{t+1}).
$$

### Posterior

$$
q_\phi(z_{t+1}|h_{t+1},o_{t+1}).
$$

### KPI decoder

$$
p(y_{t+1}|z_{t+1},h_{t+1}).
$$

### Utility head

$$
\hat r_{t+1}
=
R_\psi(z_{t+1},h_{t+1}).
$$

这样一个模型就能支持：

- stochastic prediction；
- uncertainty；
- multi-step imagination；
- MPC；
- likelihood-based anomaly detection。

---

# 37. 第二个更有 AI novelty 的版本

如果第一版结果好，可以进一步改成：

## **Physics-Grounded Graph-JEPA World Model**

训练时：

```text
Past NTN Graph
      ↓
Context Encoder
      ↓
     z_t
      │
action + future physics
      ↓
Predictor
      ↓
  ẑ_{t+k}
      ↑
Future NTN Graph
      ↓
Target Encoder
      ↓
   z_{t+k}
```

loss：

$$
\|
\hat z_{t+k}
-
\mathrm{sg}(z_{t+k})
\|^2.
$$

随后：

- lightweight KPI head；
- anomaly residual；
- MPC planning。

这个版本可能比普通 RSSM 更容易和最新 “predictive representation / AI-native 6G” literature 对接。

---

# 38. 为什么 Graph-JEPA 对 Security 很自然

训练时只看 normal network：

$$
z_t
\rightarrow
\hat z_{t+1}.
$$

正常测试：

$$
\hat z_{t+1}
\approx
z_{t+1}.
$$

攻击时：

$$
\|
\hat z_{t+1}
-
z_{t+1}^{attack}
\|
\gg 0.
$$

因此 representation prediction 本身就是 anomaly detector。

不需要：

- 重建所有 I/Q；
- 大量 attack labels；
- 专门训练 jammer classifier。

---

# 39. 研究贡献可以如何写

最终论文可以明确写成四个 contribution。

## Contribution 1 — Physics-Grounded NTN World Model

提出一个 NTN-specific World Model，将 deterministic orbital/geometry dynamics 从 learned dynamics 中显式分离：

$$
\text{known physics}
+
\text{learned residual dynamics}.
$$

---

## Contribution 2 — Action-Conditioned Predictive Orchestration

World Model 学习：

$$
p(s_{t+1:t+H}|s_t,a_t),
$$

并通过 counterfactual rollout + MPC 实现 proactive satellite association / handover。

---

## Contribution 3 — Unified Normal-State Anomaly Detection

利用 predicted network evolution 作为 “normal world reference”，通过 uncertainty-aware prediction residual 检测 jamming / fault / unforeseen interference。

---

## Contribution 4 — Model-Based Autonomous Recovery

检测异常后，World Model 对候选 mitigation actions 进行 imagined rollout，选择性能最优的恢复策略。

---

# 40. 什么地方是真正的 Novelty，什么地方不是

## 不足以单独构成 novelty

- 使用 SGP4 建卫星 Digital Twin；
- 根据 orbit 预测 handover；
- 用 GNN 做 satellite association；
- 用 autoencoder 检测 jammer；
- 用 Transformer 预测 SINR；
- 用 DRL 做 handover。

这些方向目前都已经有大量或正在快速增长的工作。

---

## 真正应该强调的组合

$$
\boxed{
NTN\ deterministic\ physics
+
action\text{-}conditioned\ learned\ world\ dynamics
+
counterfactual\ planning
+
normal\text{-}state\ anomaly\ detection
}
$$

最强的 narrative 是：

> **一个统一 World Model，同时成为 network planner 和 normality model。**

---

# 41. 与当前文献的关系和研究空白

截至 2026 年 8 月，几个非常相关的方向已经出现，因此论文一定要避开“只是换名字”的风险。

## 41.1 Telecom World Models

2026 年的 *Telecom World Models: Unifying Digital Twins, Foundation Models, and Predictive Planning for 6G* 已经提出：

- action-conditioned dynamics；
- uncertainty-aware prediction；
- model-based rollout；
- telecom world model architecture。

因此：

> “把 World Model 用于 telecom” 本身已经不是 novelty。

你的区别必须是 **NTN-specific physics structure + unified resilience**。

---

## 41.2 Wireless World Model

*A Wireless World Model for AI-Native 6G Networks* 使用 joint-embedding predictive architecture 和多模态 Transformer，把 CSI、3D point cloud 和 trajectory 融合起来学习 wireless propagation。

所以：

> “World Model 学 channel” 也不是足够独特。

你的 focus 应该是：

> **network-level state/action dynamics，而不是只做 channel foundation model。**

---

## 41.3 Physics-Informed NTN Digital Twin

2026 年已经有工作将 satellite orbital dynamics、channel、weather 和 traffic prediction 放进 physics-informed NTN Digital Twin。

因此：

> “Physics-informed NTN Digital Twin” 本身也不能作为唯一 contribution。

我们的下一步是：

$$
\text{Physics DT}
\rightarrow
\text{Action-conditioned World Model}
\rightarrow
\text{Planning + Resilience}.
$$

---

## 41.4 Predictive LEO Handover

PreHO 已经明确利用 ephemeris 和 LEO 可预测性做 proactive handover planning。

因此不能只说：

> “我们的 World Model 根据未来 satellite trajectory 提前 handover。”

这会被问：

> 为什么需要 AI？Orbit 已经知道。

所以 World Model 必须负责：

- stochastic traffic；
- load；
- interference；
- channel residual；
- abnormal dynamics；
- action consequences。

---

## 41.5 GNN LEO Orchestration

2026 年已有 heterogeneous GNN 用于动态 LEO association / orchestration。

因此 GNN 是 representation tool，而不是核心 novelty。

---

## 41.6 JEPA for AI-Native 6G

近期已有工作明确讨论使用 predictive latent representation 做：

- future network state prediction；
- anomaly detection；
- jamming/spoofing detection。

因此如果使用 JEPA，必须将贡献定位为：

> **NTN-specific physics-grounded graph world model and unified planning/security loop**，

而不是“第一次用 JEPA 检测网络异常”。

---

# 42. 当前最有希望的 research gap

基于上述文献，最值得切入的 gap 是：

> **How can deterministic orbital knowledge be explicitly fused with an action-conditioned learned world model so that a single NTN model can support both proactive control and resilience under unforeseen disturbances?**

三个关键词：

### 1. Physics-grounded

不是 pure data-driven。

### 2. Action-conditioned

不是普通 forecasting。

### 3. Unified planning + anomaly

不是两个独立 AI。

---

# 43. 第一篇 paper / poster 不要做太大

虽然总体框架很大，但第一版只做：

$$
\boxed{
LEO\ association/handover
+
jamming
}
$$

足够。

一个最小闭环：

```text
Orbit / Geometry
       ↓
Physics Context
       ↓
World Model ← telemetry
       ↓
Predict future SINR/load/throughput
       ↓
MPC satellite association
       ↓
Physical simulator
       ↓
prediction mismatch?
       │
      yes
       ↓
anomaly detector
       ↓
simulate mitigation
       ↓
handover / power / nulling
```

---

# 44. Brooklyn AI-Native 6G Summit Poster 可以怎么讲

图中 Summit topic 最匹配：

- **Digital twins and simulation environments**
- **Network automation and intent-based networking**
- **AI for security, privacy, and trust**

不需要强行强调 LLM。

Poster headline 可以是：

## **WorldNTN: A Physics-Grounded World Model for Autonomous and Resilient 6G Non-Terrestrial Networks**

副标题：

> **Predict the network. Detect when reality deviates. Imagine the best action before acting.**

Poster 最好展示三个核心 panel：

### Panel A — Physics + World Model

Deterministic orbit + learned residual dynamics。

### Panel B — Predictive Orchestration

多个 candidate satellites 的 future rollout。

### Panel C — Resilience

现实偏离 prediction → anomaly → mitigation rollout。

---

# 45. Poster 最值得画的一张主图

可以画成：

```text
                      KNOWN PHYSICS
             Orbit / Geometry / Doppler / FSPL
                           │
                           ↓
Telemetry ────────→ ┌───────────────┐ ←──── Candidate actions
                    │   WorldNTN    │
                    │  World Model  │
                    └───────┬───────┘
                            │
                 IMAGINED FUTURE WORLDS
          ┌─────────────────┼──────────────────┐
          ↓                 ↓                  ↓
       Stay A            Switch B          Switch C
       R=...             R=...             R=...
       Outage=...        Outage=...        Outage=...
          └─────────────────┬──────────────────┘
                            ↓
                       Best Action
                            ↓
                        Real Network
                            ↓
                         Telemetry
                            │
                 prediction consistent?
                     /              \
                   yes              no
                    │                │
                 continue       ANOMALY
                                     ↓
                         mitigation rollouts
```

这一张图基本可以把整项工作解释完。

---

# 46. 推荐的结果图

如果时间有限，优先做 5 张。

## Figure 1

**Architecture / framework**

---

## Figure 2

**World-model prediction**

$$
\text{Real KPI vs predicted KPI}
$$

并带 uncertainty band。

---

## Figure 3

**Prediction RMSE vs horizon**

对比：

- physics only；
- black-box predictor；
- proposed。

---

## Figure 4

**Throughput vs handover tradeoff**

对比：

- max-SNR；
- greedy；
- model-free RL；
- WM-MPC。

---

## Figure 5

**Jamming ROC / detection probability**

并加 mitigation 后 throughput recovery。

---

# 47. 推荐开发路线

## Phase 0 — Environment

先建立：

- orbital propagation；
- visibility；
- FSPL；
- traffic；
- association；
- queue/load；
- jammer。

输出 episode 数据：

```text
time
UE state
satellite state
physics features
action
SINR
throughput
load
queue
```

---

## Phase 1 — Prediction baseline

训练：

- MLP；
- GRU；
- Transformer。

目标：

$$
t-K:t
\rightarrow
t+1:t+H.
$$

确认数据中确实存在可学习的 stochastic dynamics。

---

## Phase 2 — Physics-grounded model

未来 orbit 直接输入。

只学习 residual。

与 black-box 模型比较。

---

## Phase 3 — Action conditioning

数据收集时必须探索不同 actions。

否则 World Model 只会看到一个 behavior policy，无法学习：

$$
a\rightarrow outcome.
$$

训练：

$$
p(s_{t+1}|s_t,a_t,c_{t+1}).
$$

---

## Phase 4 — MPC

先不用 RL。

World Model + candidate action rollout。

---

## Phase 5 — Normal-state anomaly detector

只用 normal training data。

测试 jammer。

---

## Phase 6 — Mitigation planning

World Model 评估：

- handover；
- power；
- nulling。

---

## Phase 7 — Graph / JEPA 升级

如果前面结果成立，再追求模型 novelty。

---

# 48. 数据收集时最容易踩的坑

World Model 训练时不能只运行一个 greedy policy。

否则：

$$
a_t
$$

和 state 强相关，模型没有看到足够多 counterfactual transitions。

例如 Sat B 明明 visible，但 greedy policy 从不连接 B。

模型就没有数据学习：

$$
p(s_{t+1}|a_t=B).
$$

因此训练数据要加入 exploration：

- random action；
- epsilon-greedy；
- mixture of policies；
- optimization policy；
- max-SNR；
- load-aware；
- random valid association。

构建更宽的 action support。

---

# 49. World Model 最大的研究风险：Model Exploitation

planner 会找到模型预测错误的区域。

即：

$$
\hat J(a)\gg J_{\mathrm{real}}(a).
$$

它不是找到真正最优 action，而是利用模型漏洞。

解决方法：

## Uncertainty penalty

$$
J_{\mathrm{robust}}
=
\hat J
-
\beta U(a).
$$

其中 $U(a)$ 是 uncertainty。

或者 ensemble：

$$
\{M_1,M_2,\ldots,M_K\}.
$$

选择：

$$
J
=
\mathbb E[J]
-
\beta \mathrm{Var}[J].
$$

这本身甚至可以成为 paper 的一个重要点：

> **uncertainty-aware safe planning in NTN World Models**。

---

# 50. 第二个风险：World Model 可能没有必要

reviewer 会问：

> Orbit 都能预测，为什么不直接 optimization？

所以必须专门设计实验：

### Physics-only planner

拥有 perfect future orbit。

### World-model planner

额外预测：

- traffic；
- load；
- interference；
- residual channel。

如果 WM 显著更好，才能证明必要性。

---

# 51. 第三个风险：Security 看起来像硬拼

解决办法不是把两个独立神经网络放在一个框图里。

一定坚持：

$$
\boxed{
\text{the same world model}
}
$$

既用于：

$$
\text{normal future prediction}
$$

又用于：

$$
\text{normality reference}.
$$

也就是：

$$
\text{prediction error}
\rightarrow
\text{anomaly}.
$$

这样安全分支是 World Model 的自然产物，而不是外挂。

---

# 52. 第四个风险：Simulator-to-reality

第一篇可以接受 simulation，但要为后续留接口。

后续可以逐步引入：

- real TLE；
- real weather；
- measured Starlink / NTN signal traces；
- RF testbed；
- hardware-generated interference。

最重要的是 World Model 本身不依赖某个特定 simulator。

---

# 53. LLM 是否需要？

## 结论：完全不需要。

第一篇甚至建议 **不要加 LLM**。

核心闭环已经完整：

$$
\boxed{
World\ Model
+
MPC
+
Anomaly\ Detector
}
$$

LLM 不会提升：

- channel prediction；
- dynamics modeling；
- anomaly likelihood；
- numerical optimization。

反而会增加：

- architecture complexity；
- latency；
- hallucination；
- reviewer 质疑。

---

# 54. LLM 以后可以放在哪里

如果后面想扩展到 Summit 更明显的 Agentic AI 方向，可以作为 optional layer：

```text
Human Intent
     ↓
LLM Agent
     ↓
objective / constraints
     ↓
World Model + Planner
```

例如：

> Protect emergency users even at the cost of overall throughput.

LLM 将其转换为：

$$
R_u\ge R_{\min},\quad u\in\mathcal U_{\mathrm{critical}}.
$$

但这一层可以完全独立于当前技术核心。

所以 roadmap 是：

$$
\textbf{World Model first, LLM optional later.}
$$

---

# 55. 我最推荐的最终研究题目

### Option A — 最稳

**WorldNTN: Physics-Grounded World Models for Predictive and Resilient Non-Terrestrial Networks**

### Option B — 更强调 autonomous

**WorldNTN: Physics-Grounded Predictive Intelligence for Autonomous 6G Non-Terrestrial Networks**

### Option C — 更强调 security

**Predict, Detect, Recover: A Physics-Grounded World Model for Resilient Non-Terrestrial Networks**

### Option D — 更像 AI conference / modern AI

**Learning the NTN World: Physics-Grounded Latent Dynamics for Predictive Control and Resilience**

当前我最推荐 **Option A**。

---

# 56. 可以直接用于 proposal/poster 的核心 abstract 草案

**Abstract —**  
Low-Earth-orbit non-terrestrial networks (NTNs) exhibit a unique combination of highly predictable physical dynamics and highly uncertain network dynamics. Satellite trajectories, visibility, propagation distance, Doppler shift, and nominal free-space path loss can be accurately derived from orbital information, whereas traffic demand, network load, residual channel variations, interference, and failures remain stochastic and difficult to model analytically. This project proposes **WorldNTN**, a physics-grounded, action-conditioned world model for autonomous and resilient NTN operation. Rather than relearning known orbital physics, WorldNTN uses a deterministic physical twin as structured context and learns only the residual network dynamics needed to predict future key performance indicators under candidate control actions. The learned model enables fast counterfactual rollouts for model-predictive satellite association and handover decisions. The same predictive model also serves as a normality reference: deviations between predicted and observed network evolution provide an uncertainty-aware signal for detecting previously unseen interference, jamming, and failures. Once an anomaly is detected, candidate mitigation actions are evaluated through imagined rollouts before execution. This unified **predict–detect–recover** framework explores how world models can move NTN digital twins beyond passive replication toward predictive control and autonomous resilience.

---

# 57. 最终建议的 research question

主问题：

> **How can deterministic orbital physics and learned network dynamics be combined into an action-conditioned NTN world model that supports both predictive control and autonomous resilience?**

可以拆成四个子问题：

### RQ1

Does explicit physics grounding improve long-horizon prediction and OOD generalization compared with purely data-driven world models?

### RQ2

Can action-conditioned world-model rollouts outperform reactive and model-free policies for satellite association and handover?

### RQ3

Can normal-state world-model prediction residuals detect unseen interference/jamming without attack-specific training?

### RQ4

Can the same model select effective mitigation actions through counterfactual rollout after an anomaly occurs?

---

# 58. 最终建议的研究假设

### H1

Physics grounding reduces sample complexity and rollout error.

### H2

Action-conditioned planning reduces outage/handover tradeoff compared with reactive policies.

### H3

Uncertainty-aware latent prediction residuals can detect unseen jamming with lower false-alarm rate than simple KPI thresholding.

### H4

World-model-based mitigation outperforms fixed rule-based recovery under heterogeneous attacks/disturbances.

---

# 59. 如果只能先完成一个最小 MVP

建议只做：

$$
\boxed{
1\ UE
+
3\sim 8\ visible\ satellites
+
stochastic\ channel/load
+
1\ jammer
}
$$

先验证四件事：

1. Physics + learned residual 比 pure neural predictor 准；
2. action-conditioned model 能预测不同 satellite choice 的未来 throughput；
3. WM-MPC 比 max-SNR 少 outage / handover；
4. jammer 出现时 prediction residual 明显上升。

如果这四件事成立，再扩展多用户、多卫星和 graph。

---

# 60. 如果要直接冲一个更完整的 conference paper

系统规模扩展到：

- 8–32 UEs；
- 10–100 candidate satellites / time window；
- heterogeneous traffic；
- satellite capacity constraint；
- multi-user association；
- random jammer；
- partial satellite failures。

主模型：

$$
\boxed{
Physics\text{-}Conditioned\ Heterogeneous\ Graph\ RSSM
}
$$

控制：

$$
\boxed{
Uncertainty\text{-}Aware\ MPC
}
$$

安全：

$$
\boxed{
Latent\ Prediction\ Residual\ Detection
}
$$

这三个技术模块已经足够形成一篇完整 paper。

---

# 61. 项目最终结构总结

```text
WORLDNTN
│
├── 1. Physics Backbone
│   ├── Orbit
│   ├── Geometry
│   ├── Visibility
│   ├── Doppler
│   └── FSPL
│
├── 2. Learned World Model
│   ├── Graph Encoder
│   ├── Latent Dynamics
│   ├── Action Conditioning
│   ├── Multi-step Prediction
│   └── Uncertainty
│
├── 3. Predictive Orchestration
│   ├── Satellite Association
│   ├── Handover
│   ├── Load Balancing
│   └── MPC / Counterfactual Rollout
│
├── 4. Resilience
│   ├── Prediction Residual
│   ├── Anomaly Detection
│   ├── Jamming / Failure
│   └── Uncertainty-Aware Detection
│
└── 5. Autonomous Recovery
    ├── Candidate Mitigations
    ├── Imagined Rollouts
    ├── Robust Utility
    └── Best Action Execution
```

最核心的一句话仍然是：

$$
\boxed{
\text{Known physics tells us what should happen geometrically;}
}
$$

$$
\boxed{
\text{the world model learns what happens operationally;}
}
$$

$$
\boxed{
\text{the mismatch tells us when the world is abnormal.}
}
$$

---

# 62. 近期相关文献与定位

以下文献是设计这个方向时最需要关注的几个“相邻工作”。

1. **Hang Zou et al., “Telecom World Models: Unifying Digital Twins, Foundation Models, and Predictive Planning for 6G,” 2026.**  
   提出了 action-conditioned、uncertainty-aware telecom world model 和 predictive planning 的总体概念。  
   https://arxiv.org/abs/2604.06882

2. **Ziqi Chen et al., “A Wireless World Model for AI-Native 6G Networks,” 2026.**  
   使用 joint-embedding predictive architecture 与多模态 Transformer 融合 CSI、3D geometry/point cloud 和 trajectory，主要聚焦 wireless propagation world model。  
   https://arxiv.org/abs/2603.25216

3. **J. Zheng et al., “From Digital Twins to World Models,” 2026.**  
   系统讨论 Digital Twin 向 World Model 的演进以及 predictive / agent-centric modeling。  
   https://arxiv.org/abs/2603.17420

4. **“Physics-Informed Digital Twins for Channel Estimation and Traffic Prediction of Non-Terrestrial Networks,” 2026.**  
   已经将 orbital dynamics、channel / weather 和 traffic 建模结合到 NTN digital twin，因此本项目不能只停留在 “physics-informed DT”。  
   https://arxiv.org/abs/2605.23155

5. **Xingqiu He et al., “PreHO: Predictive Handover for LEO Satellite Networks,” 2026.**  
   展示了利用 LEO orbit/ephemeris 进行 predictive handover 的价值，因此 WorldNTN 必须进一步处理随机 traffic、load、interference 和 action-conditioned network dynamics。  
   https://arxiv.org/abs/2603.07987

6. **Aruna Jayarajan et al., “LEO Satellite Network Orchestration with Heterogeneous Graph Neural Networks,” 2026.**  
   使用 heterogeneous GNN 对动态 satellite-ground graph 做实时 orchestration，说明 graph 是自然表示方式，但并非 WorldNTN 的核心 novelty。  
   https://arxiv.org/abs/2606.31950

7. **“JEPA for AI-Native 6G: Predictive Representations and Open Challenges,” 2026.**  
   讨论 predictive representation、normal-state modeling 和 anomaly detection，包括 jamming/spoofing 等安全应用，为 Graph-JEPA 版本提供直接参考。  
   https://arxiv.org/abs/2607.09798

8. **ETSI TR 104 319 work item, “A reference functional architecture for integrating Network Digital Twins in 6G systems,” 2026.**  
   ETSI 已在推进面向 6G 的 Network Digital Twin 功能架构，包括 AI-driven orchestration、simulation 和 data management。  
   https://portal.etsi.org/webapp/WorkProgram/Report_WorkItem.asp?WKI_ID=79357

9. **3GPP Release 20.**  
   Release 20 同时涉及 AI/ML、Satellite/NTN、Energy Efficiency/Sustainability，并启动 early 6G studies。  
   https://www.3gpp.org/specifications-technologies/releases/release-20

---

# 63. 最后的技术选择建议

如果现在立刻开始做，我会按这个顺序：

1. **先不要加 LLM。**
2. **先不要直接做大 Transformer。**
3. 搭好 physics NTN simulator。
4. 建 stochastic traffic/channel/interference，使 network dynamics 真正有“未知量”。
5. 先做 **GRU predictor baseline**。
6. 做 **physics-conditioned latent state-space model**。
7. 加 action conditioning。
8. 上 **MPC**。
9. 用同一个模型做 **normal-state anomaly detection**。
10. 加 jammer。
11. 做 mitigation rollout。
12. 最后再决定是否升级为 heterogeneous graph / JEPA。

最值得保住的 research identity 是：

> **WorldNTN is not an AI replacement for orbital physics. It is a learned model of the uncertain network dynamics that remain after known NTN physics has been factored out.**

这句话基本定义了整个项目。
