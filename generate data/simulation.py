"""One active A downlink and one exogenous B downlink on a shared channel."""
from collections import deque
from dataclasses import dataclass

import numpy as np
import pandas as pd

from physics import link_geometry, noise_power_w, ratios_db


def remaining_runs(eligible):
    """Consecutive available native samples, capped at the supplied CSV horizon."""
    runs = np.zeros(eligible.shape, np.int32)
    if len(runs):
        runs[-1] = eligible[-1]
    for k in range(len(runs)-2, -1, -1):
        runs[k] = np.where(eligible[k], runs[k+1] + 1, 0)
    return runs


def select_satellite(policy, candidates, snr, remaining, rng):
    candidates = np.asarray(candidates, dtype=int)
    if not len(candidates):
        return None, 0.0
    if policy == "random":
        return int(rng.choice(candidates)), 1 / len(candidates)
    if policy == "longest_remaining":
        return int(candidates[np.argmax(remaining[candidates])]), 1.0
    if policy == "max_snr":
        return int(candidates[np.argmax(snr[candidates])]), 1.0
    raise ValueError(f"Unknown policy: {policy}")


def quality_points(sinr_db, trigger):
    if not np.isfinite(sinr_db) or sinr_db < trigger.sinr_min_db:
        return trigger.bin_points[0]
    if sinr_db < trigger.middle_start_db:
        return trigger.bin_points[1]
    if sinr_db < trigger.highest_start_db:
        return trigger.bin_points[2]
    return trigger.bin_points[3]


@dataclass
class SimulationResult:
    observations: pd.DataFrame
    actions: pd.DataFrame
    executions: pd.DataFrame
    link_segments: pd.DataFrame
    aggressor_trace: pd.DataFrame
    power_truth: pd.DataFrame


def aggressor_schedule(cube, geometry, cfg):
    eligible = cube.valid & (geometry.elevation_deg >= cfg.min_elevation_deg) & (geometry.snr_db >= cfg.min_snr_db)
    remaining = remaining_runs(eligible)
    active = np.full(len(cube.times), -1, dtype=int)
    rows, current = [], None
    for k, time in enumerate(cube.times):
        reason = "hold"
        if current is None or not eligible[k, current]:
            old = current
            current, _ = select_satellite("longest_remaining", np.flatnonzero(eligible[k]),
                                         geometry.snr_db[k], remaining[k], None)
            reason = "initial" if k == 0 else "snr_or_visibility_lost" if old is not None else "reacquire"
        if current is not None:
            active[k] = current
        n = int(remaining[k, current]) if current is not None else 0
        rows.append({"time": time.isoformat(), "b_satellite_id": cube.ids[current] if current is not None else "",
                     "b_link_snr_db": float(geometry.snr_db[k, current]) if current is not None else np.nan,
                     "reason": reason, "remaining_samples_within_csv": n,
                     "remaining_horizon_censored": bool(current is not None and k+n == len(cube.times))})
    return active, pd.DataFrame(rows)


def score_segments(observations, starts, times, cfg):
    """Integrate left-endpoint sample quality over observed intervals only."""
    dt = (times[1] - times[0]).total_seconds()
    rows = []
    for i, (start, sat_id, action_id) in enumerate(starts):
        censored = i == len(starts)-1
        end = len(times)-1 if censored else starts[i+1][0]
        segment = observations.iloc[start:end]
        sinr = segment.sinr_db.to_numpy(float)
        finite = np.isfinite(sinr) & segment.link_valid.to_numpy(bool)
        usable = finite & (sinr >= cfg.trigger.sinr_min_db)
        spectral_eff = np.zeros(len(segment))
        spectral_eff[finite] = np.logaddexp(0, sinr[finite] * np.log(10)/10) / np.log(2)
        dwell = (end-start) * dt
        outage = float((~usable).sum()) * dt
        integral = float(spectral_eff.sum()) * dt
        reward = cfg.reward
        cost = reward.handover_cost if action_id else 0.0
        score = (reward.dwell_weight*dwell + reward.quality_weight*integral
                 - reward.outage_weight*outage) / reward.time_scale_s - cost
        rows.append({"segment_id": i, "satellite_id": sat_id, "origin_action_id": action_id,
                     "is_action_outcome": bool(action_id),
                     "start_index": start, "end_index_exclusive": end,
                     "start_time": times[start].isoformat(), "end_time": times[end].isoformat(),
                     "dwell_seconds": dwell, "usable_service_seconds": float(usable.sum())*dt,
                     "outage_seconds": outage, "spectral_efficiency_integral_seconds": integral,
                     "mean_sinr_db": float(np.mean(sinr[finite])) if finite.any() else np.nan,
                     "score": score, "right_censored": censored,
                     "score_label_valid": bool(not censored and sat_id),
                     "quality_success": bool(score >= reward.success_score_threshold) if not censored and sat_id else None,
                     "end_reason": "csv_horizon" if censored else "next_connection_change"})
    return pd.DataFrame(rows)


def simulate(a, b, cfg):
    cfg.validate()
    if not a.times.equals(b.times) or len(a.times) < 2:
        raise ValueError("A/B time grids must match and contain at least two samples.")
    ga = link_geometry(a.positions, a.valid, cfg.ground_a, cfg.radio)
    gb = link_geometry(b.positions, b.valid, cfg.ground_b, cfg.radio)
    gba = link_geometry(b.positions, b.valid, cfg.ground_a, cfg.radio)
    b_active, b_trace = aggressor_schedule(b, gb, cfg)
    admission = a.valid & (ga.elevation_deg >= cfg.min_elevation_deg) & (ga.snr_db >= cfg.min_snr_db)
    remaining = remaining_runs(admission)
    rng = np.random.default_rng(cfg.random_seed)
    current, _ = select_satellite(cfg.victim_initial_policy, np.flatnonzero(admission[0]),
                                 ga.snr_db[0], remaining[0], rng)
    starts = [(0, str(a.ids[current]) if current is not None else "", "")]
    pending, history = None, deque(maxlen=cfg.trigger.window_samples)
    obs, actions, executions, truth = [], [], [], []
    noise = noise_power_w(cfg.radio)
    last_connection_index = 0
    for k, time in enumerate(a.times):
        applied_action = ""
        if pending is not None:
            target, action_id, old_index = pending
            success = bool(admission[k, target])
            executions.append({"action_id": action_id, "execute_index": k, "execute_time": time.isoformat(),
                               "source_satellite_id": str(a.ids[old_index]) if old_index is not None else "",
                               "target_satellite_id": str(a.ids[target]), "success": success,
                               "reason": "executed" if success else "target_unavailable_at_execution"})
            if success:
                current = target
                last_connection_index = k
                starts.append((k, str(a.ids[current]), action_id))
                history.clear()
                applied_action = action_id
            pending = None
        # An attached link may stay below min SNR until its trigger fires.
        connected = bool(current is not None and a.valid[k, current]
                         and ga.elevation_deg[k, current] >= cfg.min_elevation_deg)
        signal = float(ga.power_w[k, current]) if connected else 0.0
        bi = b_active[k]
        interfering = bool(cfg.radio.interference_enabled and bi >= 0 and gba.above_horizon[k, bi])
        interference = float(gba.power_w[k, bi]) if interfering else 0.0
        sinr, snr, inr = (float(x) for x in ratios_db(signal, interference, noise))
        point = quality_points(sinr, cfg.trigger)
        history.append(point)
        total = sum(history)
        forced = bool(not connected and cfg.trigger.force_on_geometry_loss)
        triggered = total >= cfg.trigger.trigger_points or forced
        age = (time - a.times[last_connection_index]).total_seconds() if current is not None else 0.0
        direction = gba.los_enu[k, bi] if interfering else np.full(3, np.nan)
        obs.append({"time_index": k, "time": time.isoformat(),
                    "a_satellite_id": str(a.ids[current]) if current is not None else "",
                    "a_satellite_index": current if current is not None else -1,
                    "link_valid": connected, "sinr_db": sinr, "snr_db": snr, "inr_db": inr,
                    "inr_linear": interference/noise, "interference_present": interfering,
                    "interferer_azimuth_deg": float(gba.azimuth_deg[k, bi]) if interfering else np.nan,
                    "interferer_elevation_deg": float(gba.elevation_deg[k, bi]) if interfering else np.nan,
                    "interferer_los_east": direction[0], "interferer_los_north": direction[1],
                    "interferer_los_up": direction[2], "connection_age_s": age,
                    "quality_points": point, "window_points": total, "window_count": len(history),
                    "triggered": triggered, "applied_action_id": applied_action})
        truth.append({"time_index": k, "signal_w": signal, "interference_w": interference,
                      "noise_w": noise, "b_satellite_id": str(b.ids[bi]) if bi >= 0 else "",
                      "b_visible_at_a": bool(bi >= 0 and gba.above_horizon[k, bi])})
        if k == len(a.times)-1:
            continue
        action_id = f"action-{k:06d}"
        target, probability, candidate_count = None, 1.0, 0
        decision, reason = "hold", "below_trigger"
        if triggered:
            candidates = np.flatnonzero(admission[k] & admission[k+1])
            if current is not None:
                candidates = candidates[candidates != current]
            candidate_count = len(candidates)
            target, probability = select_satellite(cfg.victim_handover_policy, candidates,
                                                   ga.snr_db[k+1], remaining[k+1], rng)
            reason = "geometry_loss" if forced else "window_points"
            if target is None:
                decision = "blocked_no_candidate"
            else:
                decision = "acquire" if current is None else "handover"
                pending = target, action_id, current
        actions.append({"action_id": action_id, "issued_index": k, "issued_time": time.isoformat(),
                        "execute_index": k+1, "execute_time": a.times[k+1].isoformat(),
                        "action": decision, "source_satellite_id": str(a.ids[current]) if current is not None else "",
                        "target_satellite_id": str(a.ids[target]) if target is not None else "",
                        "target_satellite_index": target if target is not None else -1,
                        "reason": reason, "window_points_at_issue": total,
                        "candidate_count": candidate_count, "selection_probability": probability})
    observations = pd.DataFrame(obs)
    execution_columns = ["action_id", "execute_index", "execute_time", "source_satellite_id",
                         "target_satellite_id", "success", "reason"]
    return SimulationResult(observations, pd.DataFrame(actions), pd.DataFrame(executions, columns=execution_columns),
                            score_segments(observations, starts, a.times, cfg), b_trace, pd.DataFrame(truth))
