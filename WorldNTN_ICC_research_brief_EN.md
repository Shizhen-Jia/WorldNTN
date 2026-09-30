# WorldNTN: Research Brief for Advisor Discussion

**Working title:** *Task-Aware Active Probing for Predictive Receive Beam Control under LEO Cochannel Interference*

**Status:** Proposed research targeting IEEE ICC; no implementation or experimental results are claimed. Scope and milestones follow scientific evidence rather than a submission deadline. This brief condenses the [full research plan](WorldNTN_ICC_concrete_research_plan.md).

## 1. Research question and motivation

**When should a ground terminal spend reception time probing interference, and which direction should it probe, to improve its subsequent receive-beam decisions?**

Consider a fixed ground terminal receiving a saturated downlink from one serving LEO satellite, with noncooperative cochannel interference from other LEO satellites. Available ephemerides predict their directions and distances, but not their transmission activity or actual illumination power.

The terminal has a **single RF chain and a quantized, phase-only receive array**. It observes one spatial combination at a time; it cannot continuously obtain all antenna samples or a full interference covariance matrix. Additional directional measurements therefore consume reception time and may interrupt service.

The central hypothesis is that **probing should reduce uncertainty that can change future communication decisions, rather than maximize general information gain**. Predictable orbital geometry determines when uncertain interference becomes relevant; temporal dynamics determine whether a measurement remains informative when its result arrives.

The initial scope excludes handover, malicious-attack attribution, multiuser scheduling, and coordinated satellite transmit control. Single-RF hardware is an explicit assumption, to be tested against multiple-RF and full-observation references.

## 2. System, observations, and objective

### Physical model and actions

Let $\mathbf a_{j,t}$ be the known array response toward interferer $j$. Unknown effective received powers $p_{j,t}\geq0$ capture activity, illumination, and propagation residuals. The interference-plus-noise covariance is

$$
\mathbf R_t=\sum_jp_{j,t}\mathbf a_{j,t}\mathbf a_{j,t}^{H}
+(p_{\mathrm{diff},t}+\sigma_n^2)\mathbf I.
$$

For communication beam $a$, with feasible phase-only weights $\mathbf w_{a,t}$,

$$
\mathrm{SINR}_t(a)=
\frac{S_t|\mathbf w_{a,t}^{H}\mathbf a_{s,t}|^2}
{\mathbf w_{a,t}^{H}\mathbf R_t\mathbf w_{a,t}},
\qquad |[\mathbf w_{a,t}]_m|=1/\sqrt M.
$$

$S_t$ is the unknown serving-link power before array gain. Phase values are quantized. All competing algorithms share a geometry-generated communication codebook, initially 12–32 beams, including matched and interference-suppressing patterns. Codebook construction cannot use hidden interference powers; achievable suppression must be verified after quantization.

Each control interval selects a **communication beam and either no extra probe or one probe beam**. Receiver actions affect observations, service, and switching state; they do not change satellite trajectories or the nonadaptive interferers' activity.

### Measurement interface and causality

Normal communication pilots are available to every method. Extra probing uses the serving satellite's existing pilot resources, without requiring cooperation from interferers. Least-squares removal of the known pilot yields a scalar desired-channel estimate and residual interference-plus-noise power $y$. Under a locally constant channel and independent complex-Gaussian residual samples,

$$
y\mid\xi_t,m\sim\mathrm{Gamma}\left(L-1,\frac{q_m}{L-1}\right),
\qquad q_m=\mathbf v_m^H\mathbf R_t\mathbf v_m.
$$

The desired-channel estimate is also noisy and must be included in the observation update. Waveform validation will test correlated samples, CFO, asynchronous OFDM, and pilot contamination, which can bias this likelihood.

The initial implementation uses control-boundary updates: a probe cannot affect a beam selected before its report arrives. Reports carry sampling and availability timestamps. Same-interval updating is a required comparison; a one-interval processing delay must not be presented as satellite round-trip delay.

### Communication objective

Maximize successfully delivered data after normal pilots, probing, switching, and actual computation delay. With normalized service $g_t=D_t/(B\Delta)$ and low-service indicator $v_t=\mathbf1\{g_t<g_{\min}\}$,

$$
\max_\pi\;\mathbb E[\overline g]
\quad\text{s.t.}\quad
\mathbb E[\overline v]\leq\epsilon,\qquad
\mathbb E\!\left[\frac{\sum_t\tau_m(m_t)}{T\Delta}\right]\leq\beta.
$$

Use a common causal MCS rule and BLER curves, accumulating delivery over data subslots when activity changes within an interval. Shannon rate is only a debugging surrogate. Count overlapping overhead once and retain all difficult periods in evaluation.

These are **average constraints, not hard per-slot guarantees**. Finite-horizon planning uses validation-tuned Lagrange prices, then freezes them for testing. Report goodput–probing–reliability Pareto curves and identify infeasible reliability targets.

## 3. Proposed contributions and technical approach

### A. Identify information needed for future beam decisions

A communication action only queries interference projections

$$
I(a,t)=\mathbf g_{a,t}^{T}\mathbf p_t,
\qquad [\mathbf g_{a,t}]_j=|\mathbf w_{a,t}^{H}\mathbf a_{j,t}|^2,
$$

rather than necessarily requiring complete CSI or covariance recovery.

For a simplified noiseless linear model, let observations be $\mathbf y=O_t\mathbf p_t$, future powers satisfy $\mathbf p_{t+k}=F_k\mathbf p_t$, and stack future action projections into $T_t$. These projections are identifiable exactly when

$$
\ker O_t\subseteq\ker T_t
\quad\Leftrightarrow\quad
\operatorname{row}(T_t)\subseteq\operatorname{row}(O_t).
$$

This is a standard linear-algebra condition, not a claimed new theorem. Its purpose is to guide sensing and characterize decision ambiguity. Positivity restrictions and process noise require separate treatment.

**Critical check:** $T_t$ may have full column rank. We must measure its singular spectrum rather than assume a low-dimensional task state. If exact reduction is unavailable, focus on finite-precision action comparisons: which uncertainty can reverse a near-optimal decision? Uniform utility error $\delta$ implies at most $2\delta$ one-step selection regret, but threshold-based reliability requires additional analysis.

### B. Derive geometry-based bounds for pruning plans and probes

This is the intended concrete distinction from generic learned-POMDP planning.

Use jointly calibrated trajectory sets for interference powers and serving-link gain. Known future array gains convert these sets into SINR, service, and plan-value intervals $[J_P^-,J_P^+]$, including switching state and costs. Prune a plan only if

$$
J_P^+<\max_{P'}J_{P'}^-.
$$

For a fixed current communication action and declared tail-plan family, the conservative gap

$$
\Delta_{\mathcal P}=\max_PJ_P^+-\max_PJ_P^-
$$

bounds the possible improvement from perfect information. A probe need not be expanded if a valid lower bound on its immediate net utility cost exceeds that gap.

These certificates are **conditional on the trajectory set and plan family**, including permitted MCS sequences. Marginal prediction intervals do not establish simultaneous coverage. Unknown serving gain must be included, and current-beam dominance alone cannot justify skipping future sensing. Report coverage, erroneous pruning, and speedup; accept that loose intervals may provide no useful pruning.

### C. Test whether learned dynamics improve decisions

Use a hybrid model:

- **Analytical:** orbit propagation, array responses, observation likelihood, report timing, SINR, and service/cost accounting.
- **Learned:** activity persistence, effective log-power dynamics, and slow serving-link residuals.

Start with a shared GRU transition model, activity/log-power mixture heads, and a particle belief updated by the analytical likelihood. Include a small common latent only when needed for correlated sources. Initial sizes: 64–128 hidden units, 2–3 mixture components, 128–256 particles, and a 3–5-model ensemble. Delayed measurements update their sampling-time states before replay to the present.

Train with transition likelihood, multi-step free-rollout projection scoring such as CRPS, and pre-assimilation observation likelihood. Simulated hidden-state supervision must be disclosed and offered equally to learning baselines; include an observable-feedback-only variant. Do not label actions using a single privileged future trajectory.

**Learning is conditional, not a predetermined contribution:** if a properly configured HMM/HSMM/AR model performs equally well, retain the sensing mechanism and narrow the world-model claim.

### Closed-loop planning

1. Update belief using arrived reports and propagate available ephemerides.
2. Enumerate feasible communication/probe pairs; apply only validated pruning rules.
3. Sample possible reports, including normal pilots in the **no-extra-probe** branch.
4. Update the entire belief for each report and optimize a shared tail plan.
5. Average branch values, execute the current action, and replan after real feedback.

The first version uses one observation branching layer and a multi-step open-loop beam-search tail. It is an approximate belief-space planner, not an optimal POMDP solution. A branch cannot reveal the hidden particle that generated its observation; reports arriving after the horizon cannot receive invented within-horizon value.

## 4. Data and initial experimental configuration

Generate orbit geometry, transmitter illumination/activity, and array inputs first—not independently sampled beam SINRs. Use parameterized Walker constellations and a frozen public ephemeris snapshot for external geometry checks; real ephemerides are not real communication measurements.

| Item | Proposed starting point |
|---|---|
| Geometry and radio | Approximately 600 km altitude, 25° elevation threshold; 20 GHz / 20 MHz |
| Receiver | $16\times16$ half-wavelength array, 1 RF chain, 4-bit phases; compare other array sizes and 2/4 RF chains |
| Timing | $\Delta=0.2$ s; sweep 0.02–1 s; horizons 1/5/10/20 steps |
| Sensing | 16/64/256 effective independent pilot samples; 0–10% extra probing; measured and swept report delays |
| Data scale | 200–500 diagnostic episodes; initially 8,000 training episodes of 120 s, approximately 4.8 million steps |
| Held-out data | 1,000 validation, 1,000 calibration, at least 2,000 ID-test episodes; initially 500 per OOD category |

All values are research configurations, not claims about a commercial system. Verify link budgets, array normalization, natural harmful-interference incidence, angular motion relative to beamwidth, activity correlation time, and achievable codebook gains before training.

Use three generator levels: matched static/AR/HMM diagnostics; traffic/scheduling-driven or semi-Markov activity with correlated power; and independent mechanisms for OOD testing. Collect mixed periodic-scan, classical-control, random-feasible, and event-driven trajectories.

Separate controller-visible logs from privileged labels. Split by orbit pass, location, time block, and interference layout **before** creating windows; keep all counterfactual branches together. Index exogenous random streams independently of actions. Distinguish zero-shot transfer, adaptation, and retraining.

## 5. Evidence needed to support the paper

### Strong comparisons

The decisive baselines are a **strong geometry/timing-aware probing rule**, **HMM/HSMM/AR dynamics with the same observation-branch planner**, and a **generic learned-POMDP planner with the same model, geometry, likelihood, and unpruned search space**.

Also include periodic scanning, uncertainty/information-gain probing, fixed probing with the proposed model, and full-covariance/black-box prediction with the same planner. Recurrent model-free RL is supplementary. Full-state, noncausal-future, and full-digital references must be labeled by their extra information or hardware.

Match information, hardware, supervision, actual probing time, and computation. With ample search, pruning should approach the unpruned planner's quality; its benefit should appear in computation saved or performance under a fixed runtime budget.

### Essential experiments

| Question | Required evidence |
|---|---|
| Does the physical problem exist? | Before learning: observation ambiguity, harmful-interference frequency, and feasible beam gains under natural geometry |
| Does probing improve communication? | Delivered-data Pareto curves at matched probing cost and low-service rate |
| Does information change decisions? | Similar current observations but different future optimal beams; reverse probe priority by changing geometry, delay, or persistence |
| Does the proposed mechanism matter? | Task-rank analysis, action regret, interval coverage, pruning errors, and runtime savings |
| Are learning and branching both needed? | A 2×2 study: strongest classical vs. learned dynamics, crossed with strong-rule vs. observation-branch probing |
| Is geometry genuinely useful? | Correct future geometry vs. frozen geometry and black-box geometry inputs, stratified by angular motion/beamwidth |
| Where should gains disappear? | No harmful interference, independent random activity, fresh full observation, inseparable directions, excessive delays, and nearly static geometry |
| Does it survive mismatch? | New activity mechanisms, unregistered sources, ephemeris/array errors, CFO and pilot contamination; independent waveform simulation or hardware-in-the-loop validation |

Report mean delivery, 5th-percentile service, low-service fraction, longest low-service run, probing/switching time, and p50/p95/p99 decision latency. Evaluate calibration and action regret alongside prediction error. Use at least five training seeds and paired, scenario-group bootstrap intervals; correlated slots are not independent trials. Preserve reproducible configurations, data hashes, random streams, and baseline tuning/search budgets.

## 6. Positioning, milestones, and advisor decisions

**Novelty to establish:** a computable, cost-aware mechanism for identifying and resolving future receive-beam ambiguity under limited RF observations—not simply “world models for satellites.” The identifiability argument, information-value principle, and interval dominance each have existing foundations.

The full plan identifies close work on [learned beam-training POMDPs](https://arxiv.org/abs/2107.05466), [active Bayesian beam tracking](https://arxiv.org/abs/2106.11281), [active sensing for beam tracking](https://arxiv.org/abs/2405.03129), [LEO geometry-based tracking](https://arxiv.org/abs/2410.21658), [NTN physics-informed digital twins](https://arxiv.org/abs/2605.23155), [DWM-RO](https://arxiv.org/html/2511.05972v3), and [scanning-array covariance estimation](https://www.ll.mit.edu/r-d/publications/covariance-estimation-scanning-arrays-fy23-rf-systems-technical-investment-program). Extend that comparison before claiming novelty.

**Evidence-based milestones:**

1. Validate the link budget, feasible codebook, observation interface, and natural interference encounters.
2. Demonstrate useful decision-changing measurements with a known-model planner and strong classical baseline.
3. Establish task analysis, reproducible data, and fair learned-POMDP comparisons.
4. Test learning and pruning separately; remove components without measurable value.
5. Complete OOD, negative-control, runtime, and independent waveform/hardware validation before finalizing claims.

Revise the direction if gains depend on artificial delays, privileged information, weak baselines, or selectively sampled rare encounters. If feasible receive beams cannot improve the physical link, report that boundary rather than alter the reward to hide it.

**Questions for my advisor:**

- Is the single-RF, cross-system interference scenario sufficiently compelling, and are its ephemeris and pilot-access assumptions defensible?
- Should the central contribution be decision ambiguity and conditional pruning, with learned dynamics treated as optional?
- What analytical result would make the contribution substantive beyond established active-sensing/POMDP methods?
- Which independent waveform or hardware validation is feasible, and which evidence should determine whether we proceed to a full ICC paper?
