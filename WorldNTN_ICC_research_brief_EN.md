# WorldNTN: Research Brief for Advisor Discussion

**Working title:** *Predictive Joint Receive Beamforming, Satellite Association, and Resource Reallocation under Partially Observed Interference*

**Status:** Proposed research targeting IEEE ICC; no implementation or results are claimed. This version replaces the single-terminal, fixed-serving-satellite scope with coordinated multiuser, multisatellite control. It summarizes the [full Chinese research plan](WorldNTN_ICC_concrete_research_plan.md). Milestones follow evidence rather than a submission deadline.

## 1. Research question

**When should an interfered terminal adjust its receive beam, share resources on its current satellite, or hand over—and how should the network account for the consequences for other users?**

Consider fixed ground terminals distributed across the contiguous United States and multiple LEO satellites operated by one coordinated network. Each terminal has a single RF chain and a quantized phase-only receive array. It can maintain at most one active satellite data connection, while a satellite serves multiple terminals with limited resources.

Two mechanisms motivate prediction:

- **Proactive resource release:** User A could remain on S1 to avoid a handover, but moving A to S2 may free capacity for user B, who will soon have a much better opportunity on S1 and few alternatives.
- **Interference-driven reassignment:** A disturbance may make A seek S2, affecting its existing users. The network can reduce allocations, defer admission, or move another user to S3. A chain of handovers is an outcome to evaluate, not a mandatory rule.

The central hypothesis is that **joint prediction can identify when local interference suppression is preferable to network-wide reassignment, and when the future service gains justify migration costs**. Decisions concern multiple users over a horizon; only currently executable actions are committed before replanning.

## 2. Scope and physical model

### Receive beamforming remains a core control

For an $M$-element terminal array,

$$
y_u=\mathbf w_u^H\mathbf x_u,\qquad
[\mathbf w_u]_m=M^{-1/2}e^{j\phi_{u,m}},
$$

with quantized phases. Geometric **beam steering** aligns reception with the serving satellite. **Interference-aware beamforming** additionally trades desired-signal gain against suppression in other directions. Handover changes the serving satellite and requires network admission and synchronization.

Use a shared feasible codebook, initially 8–16 receive patterns per candidate link, including matched and interference-suppressing beams. Recompute actual patterns after phase quantization. A phase-only array cannot realize arbitrary digital weights; nearly aligned desired and interfering signals may be inseparable.

Switching satellites does not automatically remove a terrestrial broadband interferer. The improvement must follow from changed spatial discrimination, serving-link gain, or allocated frequencies.

### Resource and interference assumptions

The initial model uses orthogonal time–frequency resources within each satellite and frequency reuse across satellites. Satellite transmit patterns follow a declared geometric rule, with fixed per-resource-block power; unrestricted transmit-precoder and power optimization are deferred.

Let $x_{u,s}(\ell)$ denote an established connection, $\rho_{u,s}(\ell)$ a target reservation, and $V_{u,s}(\ell)$ geometric service eligibility. At every execution subslot,

$$
\sum_sx_{u,s}\leq1,\qquad x_{u,s}\leq V_{u,s},\qquad
\sum_u(x_{u,s}+\rho_{u,s})\leq C_s.
$$

$C_s$ represents the explicitly modeled service-beam/session capacity, not an arbitrary device for forcing reassignment. An active session and its reservation cannot occupy the same satellite twice. Compare this abstraction with relaxed context capacity and time-shared beams.

For binary actual resource assignment $a_{u,s,q}$ and reserved assignment $r_{u,s,q}$,

$$
\sum_u(a_{u,s,q}+r_{u,s,q})\leq1,\qquad
a_{u,s,q}\leq x_{u,s},\qquad r_{u,s,q}\leq\rho_{u,s}.
$$

Reservations consume declared capacity but emit no signal. A new user need not displace an existing user if sharing remains feasible. Geographic competition must arise from real coverage and common resource pools; distant US terminals do not automatically contend with each other.

The received SINR is

$$
\Gamma_{u,s,q}=
\frac{S_{u,s,q}|\mathbf w_u^H\mathbf a_{u,s}|^2}
{\mathbf w_u^H(\mathbf R^{\mathrm{ext}}_{u,q}
+\mathbf R^{\mathrm{net}}_{u,q}+\sigma_q^2\mathbf I)\mathbf w_u}.
$$

External interference follows a spatially consistent source process. Network-generated interference depends on actual scheduled transmissions, transmit directions, and occupied resources, and must be recomputed after each candidate action.

The main scope excludes intersatellite routing and assumes adequate feeder/backhaul supply, with explicit context-transfer costs where applicable. Start with exogenous, temporally correlated rate demands; queueing is a separate extension. Each simulated user is an actual terminal, not a geographic region represented by one fictitious array.

## 3. Partial observation and executable handovers

A network controller receives delayed terminal measurements, satellite resource reports, and command acknowledgments. Terminals observe scalar pilot estimates, residual interference power, and decoding outcomes through their current beam. Candidate-link measurements require scheduled opportunities; complete current CSI is unavailable.

A short pilot block can use LS desired-signal removal and, under independent complex-Gaussian residuals,

$$
y\mid\xi,\mathbf w,\text{schedule}
\sim\mathrm{Gamma}(L-1,\nu/(L-1)),
$$

where $\nu$ includes external interference, actual network interference, and noise; the second Gamma parameter is its scale. Desired-channel estimates are also noisy. Independently validate CFO, asynchronous OFDM, correlation, and pilot contamination.

All methods initially share the same measurement schedule and budget. Task-aware extra probing is an optional extension rather than the central contribution.

Track sampling, report arrival, computation completion, and command activation separately. Delayed observations update their sampling-time states before propagation. Remote coordination cannot assume instantaneous local control or free access to all users' current states.

Use an explicit state machine:

**CONNECTED → PREPARING → SWITCHING → CONNECTED**, with rejection, cancellation, timeout, and recovery branches.

The old link may continue during preparation, except for measurement gaps. Network-side target reservation does not imply dual reception. The single-RF terminal stops old-link data during retuning, synchronization, and access; failed attempts still incur costs.

A feasible final assignment may have no feasible transition. If two satellites are full, exchanging users cannot silently reserve extra capacity or occur as a free atomic swap. The planner must wait, find another destination, or explicitly release service and count the interruption. Resource occupancy and reservations are checked at every subslot. Commands specify targets; actual connections follow the state machine. Satellites maintain authoritative reservation ledgers and acknowledge versioned commands. Stale-command rejection, retries, and service losses are counted through the same executor for every method.

## 4. Objective and proposed method

### Optimize delivery and user protection

Jointly choose satellite associations, resource reservations and allocations, handover start times, and receive-beam modes. Delivered bits are accumulated only over actual data subslots using a common causal MCS/BLER mapping. Pilot, measurement, computation-induced waiting, and handover losses enter the execution timeline once.

The initial demand model caps delivery by the offered bits in each interval and records unmet demand; it does not silently carry backlog. Define $g_{u,t}=D_{u,t}/(R_{\mathrm{ref}}\Delta_N)$ and long-term average $\bar g_u$. A candidate objective is

$$
\max_\pi\;\mathbb E\left[
\sum_u\omega_u\log(\varepsilon_0+\bar g_u)
-\lambda_{\mathrm{sig}}\overline C_{\mathrm{sig}}\right],
$$

subject to resource feasibility and per-user low-service targets, with optional handover budgets. A low-service event occurs when delivery falls below a fixed fraction of active demand. Signaling penalties cover costs not already reflected in lost delivery.

The rolling planner carries accumulated or explicitly smoothed user service into its fairness calculation and tests horizon-end effects; per-slot log rate is not automatically equivalent to the stated long-term objective. Report raw delivery alongside fairness utility. Do not sacrifice the same users repeatedly to improve the aggregate. Average reliability constraints are not hard guarantees; report infeasible operating regions and retain disrupted periods in evaluation.

### Three contributions to test

**1. Local recovery versus network-wide service cost.** Characterize how interference duration, angular separability, load, alternative coverage, and switching delay determine whether to stay, reshape the receive beam, reallocate resources, or migrate. Decompose a candidate plan's value into the affected user's benefit, other users' changes, and remaining overhead. This is an explanation of the full objective, not an extra penalty that double-counts other users' losses.

**2. Predictive planning with explicit migration dependencies.** Construct a time-varying graph of feasible links, shared resources, interference, and reservation/release dependencies. Search keep/share/move/swap/bounded-chain candidates, retaining local beam recovery as an alternative. Validate every candidate against the protocol timeline. The intended contribution is improved communication performance per unit of computation compared with equally informed generic MPC, not merely using a graph.

**3. Decision value of probabilistic dynamics.** Test whether learned interference persistence and demand correlations improve joint control relative to correctly configured HMM/HSMM/AR models using the same planner. If classical prediction suffices, retain the planning contribution and narrow the world-model claim.

### Hybrid world model and planner

Compute orbits, array responses, resource conservation, switching stages, controlled interference, and delivery analytically. Learn unknown external-source activity, power/link residuals, and demand dynamics. Network load and protocol states evolve through explicit action-dependent updates; receiver actions do not change exogenous orbits or nonadaptive interferer activity.

Start with shared GRU probability models, a structured particle belief, and an ensemble. Use graph interactions or shared latent factors when needed for cross-user/source dependence. Independent terminal sampling cannot represent a common interferer. Nationwide particle filtering requires factorization and scalability checks.

Train with transition likelihood, pre-assimilation observation likelihood, and proper multi-step projection/delivery scores such as CRPS. Disclose simulated hidden-state supervision and match it across baselines. Future action labels must integrate over current uncertainty and future randomness, not reveal a single privileged trajectory.

The initial controller uses **scenario MPC with a common open-loop tail**, evaluating association, resources, and receive beams together through nested search/iteration. It replans after actual reports. Future actions cannot depend on hidden scenario identity. Explicit observation branching is optional and must obey report arrival times.

Bounded neighborhoods and migration-chain depth are computational approximations. Account for boundary users and interference. Optional plan-value interval pruning requires joint coverage and applies only to the declared plan family; report erroneous pruning. Small discrete instances should provide exhaustive or certified optimization references.

## 5. Experimental plan

### Configuration and data

| Item | Starting configuration, subject to validation |
|---|---|
| Geography and users | Contiguous US; 6–12-user mechanism examples, approximately 60-terminal main case; 20/100/200 scaling |
| Satellites | Orbit-derived union of eligible satellites; report per-user candidates and overlap instead of imposing unrealistic counts |
| Radio and payload | Approximately 600 km altitude, 25° elevation threshold, 20 GHz / 20 MHz; 20 resource blocks; initial $C_s=8$ |
| Terminal | $16\times16$ half-wavelength array, one RF chain, 4-bit phases; vary array size and RF count |
| Time scales | Network period 1 s; geometric tracking 0.1 s; horizons 1/5/10/20/60 periods |
| Execution costs | Explicit reporting, command, reservation, synchronization, failure, and recovery times; zero-cost cases only as controls |
| Data | Initially 8,000 training episodes of 600 s; 1,000 validation, 1,000 calibration, at least 2,000 ID test; 500 per initial OOD category |

These are research settings, not commercial specifications. Validate link budgets, feasible post-quantization beam gains, natural interference/competition incidence, and motion relative to beamwidth before learning.

Generate geometry and external traffic/interference first, then simulate action-dependent scheduling, network interference, measurements, and protocol execution. Mix conventional and exploratory legal policies. Counterfactual branches share exogenous traces but recompute controlled outcomes. Split by geographic/scenario groups and orbit passes before windowing; isolate privileged labels. Real ephemerides are not real communication measurements.

### Required comparisons and evidence

Strong baselines include independent predictive handover with admission control; global one-step allocation; deterministic load-aware multistep MPC; classical probabilistic dynamics with the same planner; generic scenario MPC with the proposed model; and an adapted MAPPO/TarMAC policy. Match information, measurement costs, codebooks, execution constraints, supervision, and actual runtime budgets.

| Test | Main evidence |
|---|---|
| Physical necessity | Natural coverage/resource competition, feasible receive-pattern gains, and harmful-interference incidence |
| Main performance | Delivery–low-service–handover/interruption Pareto curves across load and interference |
| Proactive release | A's migration cost versus B's opportunity and incumbent users' losses |
| Local versus network control | Beam-only, association-only, and joint control across angular separation and disturbance duration |
| Reassignment dependencies | Reservation, full-load swaps, failed handovers, chain depth, and per-user consequences |
| Prediction and learning | One-step versus multistep; classical/learned dynamics × independent/joint planning |
| Fairness and scale | Tail service, repeated displacement, regional outcomes, runtime, and larger networks |
| Independent validation | New generators, waveform-level pilot/data simulation, or hardware-in-the-loop evidence |

Negative controls include spare capacity, no harmful interference, unpredictable activity, fresh complete observations, inseparable directions, long delays, and very low/high switching costs. Gains should not require artificial displacement or selectively chosen rare encounters.

Report actual delivery, demand satisfaction, fifth-percentile user service, longest interruption, attempted/successful/failed handovers, reservation waste, and p50/p95/p99 decision latency. Use at least five training seeds and paired scenario-group bootstrap intervals. Do not treat correlated users or slots as independent trials. Include actual runtime in command activation and distinguish expected BLER-based delivery from packet-level outcomes.

## 6. Positioning and decisions for my advisor

Existing work already covers [load-balanced predictive handover](https://ieeexplore.ieee.org/document/10564237/), [GNN association with admission control](https://www.sciencedirect.com/science/article/pii/S2405959525000098), [MARL handover and power allocation](https://ieeexplore.ieee.org/abstract/document/11667348/), and [handover-aware cooperative beamforming/scheduling](https://arxiv.org/abs/2603.07434). Multiuser coordination, switching penalties, and graph learning alone are insufficient novelty.

The distinction to establish is **joint local receive-beam recovery and executable network reassignment under partial interference observations, with future service costs to other users explicitly evaluated**. Unlike the locally reviewed graph-world-model beamforming paper's single-step performance surrogate under fixed association, this proposal includes temporal resource and protocol states. Novelty still requires a fuller comparison.

**Milestones:** validate physical opportunities and capacity; implement the reservation/handover state machine; demonstrate mechanisms with strong classical MPC; isolate learning and search gains; complete nationwide/OOD, fairness, runtime, and independent waveform/hardware tests.

Revise the direction if gains rely on free future CSI, unrealistic delays, forced displacement, weak baselines, or infeasible transitions. Remove unnecessary learned components rather than treating model complexity as a contribution.

**Advisor discussion:**

- Which operator information, pilot access, and control-delay assumptions are defensible?
- How should resource pools and service-beam capacity map to a realistic payload?
- Should the main contribution emphasize the local-beam/migration decision boundary or scalable executable joint planning?
- Which independent waveform or hardware evidence can validate interference observations and handover costs?
