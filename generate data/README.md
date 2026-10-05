# Multi-constellation FSPL dataset generation: version 1

Start with [main.ipynb](main.ipynb). The Python modules provide CSV loading, radio calculations, the handover state machine, scoring, and training views. They read existing orbit CSVs without downloading elements or modifying the inputs.

The implementation follows `literature review/plan.jpg` and the multi-constellation broadband LEO world-model data collection plan, within the requested simplified scope: one victim link, one aggressor link, a single active co-channel interfering downlink, fixed gains and power, FSPL, and thermal noise. Array patterns, background users, multi-beam scheduling, pilot scanning, reporting delays, and a complete handover protocol from the broader plan are outside this version.

## Suitability of the proposed inputs

The proposed inputs are sufficient for the first version. In the diagram, A is the victim ground station and A2 is its serving satellite. Ground station B connects to a B satellite whose downlink interferes at A. The code follows B's active connection instead of hard-coding satellite B1.

Default training inputs include:

- Serving-link SINR, SNR, and INR histories.
- The interference arrival direction as a unit vector in A's ENU frame; logs also retain azimuth and elevation.
- Historical ECEF positions and validity masks for all satellites in the input A/B catalogs.
- The current serving-satellite index, known handover actions and target indices, and missing-data/no-link flags.

Satellite IDs associate positions with actions; they need not be treated as continuous numerical network inputs. Position histories omit velocities by default. Velocities are retained in the public geometry data and can be enabled with `TrainingView(..., include_velocity=True)`. Trigger-window scores and connection age are also saved but excluded from the minimal feature set; enable them with `include_controller_state=True`.

Under a common noise definition:

`SINR_dB = SNR_dB - 10 log10(1 + 10^(INR_dB/10))`.

All three can be recorded for consistency checks, but they are not three independent degrees of freedom. Version 1 assumes accurate, immediate observations. Whether a real receiver can isolate precise INR from aggregate interference belongs to a later measurement model.

**Constant, direction-independent gains remove the mechanism of suppressing interference by steering the receive direction.** Switching A's satellite at the same instant changes the desired signal and subsequent dwell, but not B→A interference power. Direction may still help infer changes in the interference source from orbital geometry, but it does not affect gain. This version validates timing, interfaces, and collection policies; it cannot alone demonstrate learned array-based directional interference avoidance. Fixed power, accurate orbits, and a deterministic B policy also make analytical prediction easier, so retain analytical and rule-based baselines.

## Recommended power and physical model

Use **10 W from each currently active satellite across the entire channel** as the initial research baseline. This matches the nominal per-beam power in the original plan. The model has no multi-beam allocation; 10 W is not total spacecraft power and must not be multiplied by bandwidth again.

| Parameter | Default research value |
|---|---:|
| Center frequency / bandwidth | 20 GHz / 250 MHz |
| Satellite transmit power on both sides | 10 W per active satellite across the channel |
| Fixed transmit gain on both sides | 30 dBi |
| Fixed receive gain at both ground stations | 30 dBi |
| Temperature / noise figure | 290 K / 6 dB |
| A location | 39.95697°N, −105.16033°E, 1660 m |
| B location | Approximately 1 km east of A, at the same ellipsoidal height |

Free-space loss is `L = 20 log10(4πdf/c)`; received power is `P_rx,dBW = 10 log10(P_tx,W) + G_tx + G_rx − L`. See [ITU-R P.525](https://www.itu.int/rec/R-REC-P.525-5-202411-I/en).

Noise is `N = k T B × 10^(NF/10)`, approximately −84.00 dBm for this configuration. Compute `S/(I+N)`, `S/N`, and `I/N` in watts before converting the ratios to dB. See [thermal noise and noise-figure definitions](https://www.mathworks.com/help/phased/ug/receiver-preamp.html).

| Slant range km | Interference-free SNR at 10 W, dB |
|---:|---:|
| 550 | 10.72 |
| 600 | 9.96 |
| 1000 | 5.53 |
| 1500 | 2.01 |
| 2000 | −0.49 |

These values provide an interpretable initial link margin without fitting a particular commercial system. The notebook displays a table from the same formula so frequency, bandwidth, and gains can be adjusted. Increasing both sides' power cannot eliminate co-channel interference; when interference dominates, SINR is primarily limited by S/I.

Only B's current serving satellite transmits; other B satellites contribute no active traffic radiation. A B satellite contributes interference only above A's horizon, but A's 25° access threshold is not applied to this interference path: a low-elevation foreign satellite can still interfere. Transmission depends on the connection at B, so B's location is required simulation configuration even though it is not an A-model input. B does not respond to A's actions in this version.

## Input CSVs and timeline

Use `*_all_states.csv` exports from `generate satellite`. Set `write_all_states=true` in the upstream `scenario.json`, then rerun the required real/synthetic trackers. Inputs must include satellites invisible to A that may be visible to B. Visible-only CSVs are rejected by default. `allow_partial_catalog=True` is only for explicitly labeled incomplete-catalog diagnostics and cannot restore removed trajectories.

Each side may select `[real all_states CSV, one synthetic all_states CSV]`. Duplicate `(Time, Satellite ID)` records raise an error. Do not combine the approved-shell completion and custom alternative for the same constellation. `amazon` and `Amazon Leo` automatically map to `kuiper`.

Required fields are `Time`, `Satellite ID` (or `Name`), three ECEF position columns `x/y/z_ECEF (m)`, and three velocity columns `vx/vy/vz_ECEF (m/s)`. ENU coordinates depend on the original observer and cannot be reused directly for B. The adjacent `metadata.json` is read and validated by default; failed/incomplete exports are rejected. External CSVs without a sidecar require explicit `allow_unverified_csv=True` after checking coordinates, units, and coverage. Legacy timestamps without a timezone require explicit `assume_naive_utc=True`.

Loading uses two chunked passes instead of concatenating a multi-million-row DataFrame. The timeline comes from upstream metadata and preserves timestamps with no satellite records. Missing orbit data uses masks, without interpolation or forward filling. Objects excluded upstream for low altitude or DTC status are not restored. A/B inputs must share exactly the same UTC sample grid; select a subset with `start_time_utc` and `max_steps`.

**Sampling interval determines handover response time.** With a 120-second CSV, the next step is 120 seconds later; it does not represent a second-scale action. Generate a 1–5-second grid upstream for that purpose. Trigger windows count samples: five samples span `4Δt` and represent the latest five quality checks.

## Connection and handover rules

B initially chooses the satellite with the longest remaining consecutive run satisfying `elevation >= min_elevation` and `SNR >= min_snr` at B's location. It stays connected until SNR or visibility becomes ineligible, then reselects at that sample boundary. Only consecutive coverage counts; a later pass is not added. Ties use stable satellite IDs. Remaining durations near the end of the CSV are truncated and flagged in B's log, without extrapolation.

A's initial policy may also use `longest_remaining`, or `random` or `max_snr`. Once connected, A retains the connection and records poor-quality samples when SNR falls below the access threshold, until the handover trigger fires. Candidate admission thresholds do not bypass the two-five-point trigger mechanism.

Default scoring:

| Current SINR | Points |
|---|---:|
| `< sinr_min_db` | 5 |
| `[sinr_min_db, middle_start_db)` | 3 |
| `[middle_start_db, highest_start_db)` | 2 |
| `>= highest_start_db` | 1 |

Default boundaries are 0 / 3 / 6 dB, with a five-sample window and trigger sum **≥10**. The inclusive comparison makes two five-point samples sufficient. Check the sum even before the window fills. Issue the action at the current sample and execute it at the next sample.

When visibility or the connection is lost, SINR is missing and receives five points; it is not recorded as 0 dB. The default still uses the window trigger. Setting `force_on_geometry_loss=True` explicitly enables a comparison policy that immediately issues a next-step switch after loss of geometric eligibility. Without interference, SINR=SNR, so two samples below the minimum SINR threshold suffice; an actual trajectory may leave the access elevation range first. The default SNR access and minimum SINR thresholds are both 0 dB; changing them independently separates these boundaries.

Clear the old window after an actual successful handover, starting the new window with the new satellite's current sample. If no valid alternative exists, record `blocked_no_candidate`, retain the state and scores, and do not reselect the current satellite to claim success. No action is issued at the final sample because it could not execute. There is no extra RF steering pause or random protocol failure. The fixed one-sample action delay is a modeling choice, not a standardized handover latency.

A ten-sample window would reach ten points even with one point per good sample. The code warns about such periodic-switch configurations. Keep the five-sample window or explicitly adjust the highest-quality bin points or total threshold.

## Why start with random handovers

Random selection among valid candidates supports initial action-outcome collection by exploring different alternatives. A candidate must differ from the serving satellite and satisfy access conditions at both the current and next samples. Next-step visibility/SNR comes from public prediction using the fixed orbit inputs. **Target selection does not access future interference or SINR.** The logged choice probability is `1 / candidate count`; a fixed seed reproduces choices.

Two comparison policies are available: `max_snr` favors strong desired signals at selection/execution time, and `longest_remaining` favors continuous dwell. All three share the trigger logic. No policy is claimed globally optimal; random selection supports exploration, and future predictive policies can be compared on the same underlying scenario.

Observing executed actions does not reveal all alternative outcomes. Different seeds sample different connections, but counterfactual scores for every action from the same state require additional branched reruns. Potential SINR for unconnected satellites is not presented as a measurement. For `prediction_samples>1`, labels follow subsequent actions in the recorded trajectory; they do not represent holding the current action fixed in a counterfactual rollout. Start with one-step prediction.

## Scores and success labels after handover

For the observed interval from a connection taking effect until the next connection change, let D be dwell time and O be accumulated time below the minimum SINR threshold or without a link:

`Q = Σ Δt × log2(1 + 10^(SINR_dB(t)/10))`

`score = α D/T_ref + β Q/T_ref − γ O/T_ref − handover_cost`.

Defaults are `T_ref=60 s, α=1, β=1, γ=2, handover_cost=0.05`. Q integrates spectral efficiency monotonically with SINR, avoiding direct summation of negative dB values and dependence on sample count. At fixed bandwidth, it also relates to ideal service volume. Missing/disconnected intervals contribute zero Q. The dwell reward retains the preference for long connections, while the outage penalty discourages high scores for prolonged lack of service.

Integration uses each left endpoint over `[t_k,t_{k+1})`, with no extrapolation beyond the final timestamp. D includes poor-quality periods; `usable_service_seconds` is stored separately. Adjust α, β, and γ for other preferences. The initial connection has a descriptive score but no `origin_action_id`, so it is not a handover-action sample. Filter on `is_action_outcome=True` when training action scores.

For complete connection segments, `score >= success_score_threshold` (default 2) defines quality success. This is a research labeling threshold, separate from a communications standard or handover execution success. If observation stops at the end of the CSV, the final segment has `right_censored=True`, `score_label_valid=False`, and an empty quality-success label. Its partial score must not be used directly as a complete supervised label. Scores are stored only in `labels/`, outside pre-action observations.

## Outputs, training interface, and reproducibility

```text
outputs/<victim>_vs_<aggressor>_<UTC>_seed<seed>/
  manifest.json                 # Completion, input/code hashes, grouping, provenance scope
  quality_report.json           # Score bins, SINR distribution, blocked actions, valid labels
  window_index.csv              # History windows and future-label intervals
  public/
    observations.csv            # Serving-link observations and victim controller state
    actions.csv                 # Current action, target, next-step execution time, probability
    executions.csv              # Actual handover results
    geometry.npz                # All input A/B positions, velocities, IDs, validity masks
    config.json                 # Victim-known settings and minimal feature allowlist
  labels/
    transitions.csv             # Observed one-step outcome labels
    link_segments.csv           # Dwell, integrated quality, outcome scores, censoring flags
  private/
    simulation_config.json      # Complete configuration, including B's location and policy
    aggressor_trace.csv         # B's actual connections and remaining-duration truth
    power_truth.csv             # S, I, N, and the actual active B satellite
```

`TrainingView(run_dir).sample(i)` returns `inputs` and `labels`. Inputs use only history, the currently issued action, and known geometry. Missing values are filled with zero and accompanied by masks. The default view does not read private files or link segments. Linear `INR=0` has no finite dB value, so logs leave `inr_db` empty and use `interference_present=False` and `inr_linear=0` to distinguish absent interference from a valid 0 dB INR.

Overlapping windows, random seeds, and policy variants must not be randomly divided between train and test. By default, identical source CSV hashes and ground stations produce the same group ID. Writing the same group to different splits under one output root raises an error. When different snapshots still cover adjacent dates or similar trajectories, manually assign a shared `scenario_group_id`; automatic hashing does not detect near-duplicates across snapshots. Normalization, model training, and large-scale scenario collection are outside this implementation.

## Running and validation

```bash
cd "/home/shizhen/my_project/WorldNTN/generate data"
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pytest -q tests
.venv/bin/python tests/smoke_main.py
```

Open `main.ipynb` with this Python kernel, set paths and configuration, and run cells in order. If no suitable inputs exist, the notebook prompts for selecting/generating all_states CSVs without creating fabricated production data. `tests/smoke_main.py` uses eight timestamps of artificial geometry in a temporary directory and executes every notebook cell. These coordinates are pipeline diagnostics, not an orbit simulation or commercial data.
