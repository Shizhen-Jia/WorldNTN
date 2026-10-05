"""Write reproducible logs and expose a training view with an explicit allowlist."""
from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import importlib.metadata
import json

import numpy as np
import pandas as pd

from orbit_io import file_hash, load_pair
from physics import noise_power_w, power_w
from simulation import simulate

ROOT = Path(__file__).resolve().parent
FEATURES = ["sinr_db", "snr_db", "inr_db", "interferer_los_east", "interferer_los_north", "interferer_los_up"]
CONTROLLER_FEATURES = ["connection_age_s", "quality_points", "window_points", "window_count"]


def write_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def link_budget_table(radio, distances_km=(550, 600, 1000, 1500, 2000)):
    distances = np.array(distances_km, float)
    p = power_w(distances*1000, radio)
    noise = noise_power_w(radio)
    return pd.DataFrame({"range_km": distances, "received_dbm": 10*np.log10(p)+30,
                         "noise_dbm": 10*np.log10(noise)+30, "snr_db": 10*np.log10(p/noise)})


def window_index(length, history, prediction, stride, group_id, split):
    rows = []
    for anchor in range(history-1, length-prediction, stride):
        rows.append({"sample_id": len(rows), "scenario_group_id": group_id, "split": split,
                     "history_start": anchor-history+1, "history_end_exclusive": anchor+1,
                     "action_index": anchor, "label_start": anchor+1,
                     "label_end_exclusive": anchor+1+prediction})
    return pd.DataFrame(rows, columns=["sample_id", "scenario_group_id", "split", "history_start",
                                       "history_end_exclusive", "action_index", "label_start", "label_end_exclusive"])


def quality_report(result, step_s):
    obs = result.observations
    finite = obs.sinr_db[np.isfinite(obs.sinr_db)]
    segments = result.link_segments
    return {"samples": len(obs), "sample_interval_s": step_s,
            "observed_duration_s": (len(obs)-1)*step_s,
            "link_valid_fraction": float(obs.link_valid.mean()),
            "interference_present_fraction": float(obs.interference_present.mean()),
            "sinr_db_quantiles": {str(q): float(finite.quantile(q)) for q in (0, .1, .5, .9, 1)} if len(finite) else {},
            "quality_point_counts": {str(k): int(v) for k, v in obs.quality_points.value_counts().items()},
            "actions": {str(k): int(v) for k, v in result.actions.action.value_counts().items()},
            "executed_handovers_or_acquisitions": int(result.executions.success.sum()),
            "completed_score_labels": int(segments.score_label_valid.sum()),
            "right_censored_segments": int(segments.right_censored.sum())}


def run_dataset(victim_paths, aggressor_paths, cfg, output_root=ROOT / "outputs"):
    a, b = load_pair(victim_paths, aggressor_paths, cfg)
    sources = a.sources + b.sources
    # Seed, collection policy and RF variants of the same base geometry share a group.
    grouping = {"source_hashes": sorted(s["sha256"] for s in sources),
                "ground_sites": sorted([asdict(cfg.ground_a), asdict(cfg.ground_b)], key=lambda x: (x["lat_deg"], x["lon_deg"], x["height_m"]))}
    group_id = cfg.scenario_group_id or "world-" + sha256(json.dumps(grouping, sort_keys=True).encode()).hexdigest()[:16]
    output_root = Path(output_root)
    for prior in output_root.glob("*/manifest.json"):
        old = json.loads(prior.read_text())
        if old["scenario_group_id"] == group_id and old["split"] != cfg.split:
            raise ValueError("This base world already belongs to a different split. Keep related runs/windows together.")
    tag = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    dest = output_root / f"{a.constellation}_vs_{b.constellation}_{tag}_seed{cfg.random_seed}"
    for folder in (dest, dest / "public", dest / "labels", dest / "private"):
        folder.mkdir(parents=True, exist_ok=False)
    manifest = {"schema_version": "fspl-v1", "status": "running", "created_at_utc": datetime.now(timezone.utc).isoformat(),
                "scenario_group_id": group_id, "split": cfg.split, "victim": a.constellation,
                "aggressor": b.constellation, "input_sources": sources,
                "incomplete_catalog": any(s["coverage"] != "all_states" for s in sources),
                "data_origin": "CSV orbit geometry plus synthetic identical-gain, same-channel downlinks; no commercial RF measurements",
                "policy_geometry_assumption": "Exact forecasts from the supplied frozen orbit grid; no future measured interference in target selection",
                "source_code_sha256": {p.name: file_hash(p) for p in sorted(ROOT.glob("*.py"))},
                "packages": {p: importlib.metadata.version(p) for p in ("numpy", "pandas")}}
    write_json(dest / "manifest.json", manifest)
    write_json(dest / "private" / "simulation_config.json", asdict(cfg))
    try:
        result = simulate(a, b, cfg)
        result.observations.to_csv(dest / "public" / "observations.csv", index=False)
        result.actions.to_csv(dest / "public" / "actions.csv", index=False)
        result.executions.to_csv(dest / "public" / "executions.csv", index=False)
        result.link_segments.to_csv(dest / "labels" / "link_segments.csv", index=False)
        result.aggressor_trace.to_csv(dest / "private" / "aggressor_trace.csv", index=False)
        result.power_truth.to_csv(dest / "private" / "power_truth.csv", index=False)
        public_config = {"ground_a": asdict(cfg.ground_a), "radio": asdict(cfg.radio),
                         "trigger": asdict(cfg.trigger), "min_snr_db": cfg.min_snr_db,
                         "min_elevation_deg": cfg.min_elevation_deg, "feature_allowlist": FEATURES,
                         "coordinate_frame": "ECEF/ITRS in m and m/s; source direction is ENU at A",
                         "nan_meaning": "Unavailable link/direction or undefined zero-power dB. Always use the masks."}
        write_json(dest / "public" / "config.json", public_config)
        np.savez_compressed(dest / "public" / "geometry.npz", time_ns=a.times.as_unit("ns").asi8,
                            a_ids=a.ids, b_ids=b.ids, a_position_m=a.positions, b_position_m=b.positions,
                            a_velocity_mps=a.velocities, b_velocity_mps=b.velocities,
                            a_valid=a.valid, b_valid=b.valid)
        index = window_index(len(a.times), cfg.history_samples, cfg.prediction_samples, cfg.window_stride, group_id, cfg.split)
        index.to_csv(dest / "window_index.csv", index=False)
        next_rows = result.observations.iloc[1:].reset_index(drop=True)
        transitions = result.actions[["action_id", "issued_index", "execute_index"]].copy()
        transitions["next_sinr_db"] = next_rows.sinr_db
        transitions["next_snr_db"] = next_rows.snr_db
        transitions["next_inr_db"] = next_rows.inr_db
        transitions["next_link_valid"] = next_rows.link_valid
        transitions.to_csv(dest / "labels" / "transitions.csv", index=False)
        report = quality_report(result, (a.times[1]-a.times[0]).total_seconds())
        report["training_windows"] = len(index)
        write_json(dest / "quality_report.json", report)
        manifest.update(status="complete", sample_count=len(a.times), victim_satellites=len(a.ids), aggressor_satellites=len(b.ids),
                        output_sha256={str(p.relative_to(dest)): file_hash(p) for p in dest.rglob("*") if p.is_file() and p.name != "manifest.json"})
    except Exception as exc:
        manifest.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        write_json(dest / "manifest.json", manifest)
        raise
    write_json(dest / "manifest.json", manifest)
    return dest


class TrainingView:
    """History + issued action -> future observed targets; never reads private/score files."""
    def __init__(self, run_directory, include_velocity=False, include_controller_state=False):
        self.root = Path(run_directory)
        self.include_velocity = include_velocity
        self.features = FEATURES + (CONTROLLER_FEATURES if include_controller_state else [])
        manifest = json.loads((self.root / "manifest.json").read_text())
        if manifest["status"] != "complete":
            raise ValueError("Dataset generation did not complete.")
        self.observations = pd.read_csv(self.root / "public" / "observations.csv")
        self.actions = pd.read_csv(self.root / "public" / "actions.csv", keep_default_na=False)
        self.windows = pd.read_csv(self.root / "window_index.csv")
        self.geometry = np.load(self.root / "public" / "geometry.npz", allow_pickle=False)

    def close(self):
        self.geometry.close()

    def sample(self, index):
        row = self.windows.iloc[index]
        lo, hi = int(row.history_start), int(row.history_end_exclusive)
        target_lo, target_hi = int(row.label_start), int(row.label_end_exclusive)
        history = self.observations.iloc[lo:hi]
        raw = history[self.features].to_numpy(dtype=float)
        measured = self.observations.iloc[target_lo:target_hi][["sinr_db", "snr_db", "inr_db"]].to_numpy(float)
        inputs = {"feature_names": self.features, "history": np.nan_to_num(raw, nan=0).astype(np.float32),
                  "history_mask": np.isfinite(raw),
                  "link_valid": history.link_valid.to_numpy(bool),
                  "interference_present": history.interference_present.to_numpy(bool),
                  "serving_indices": history.a_satellite_index.to_numpy(int),
                  "action": self.actions.iloc[int(row.action_index)].to_dict(),
                  "history_actions": self.actions.iloc[lo:hi].to_dict("records"),
                  "a_ids": self.geometry["a_ids"], "b_ids": self.geometry["b_ids"]}
        for role in ("a", "b"):
            for kind in (("position_m", "velocity_mps") if self.include_velocity else ("position_m",)):
                # Only history slices are exposed; future B activity is never an input.
                data = self.geometry[f"{role}_{kind}"][lo:hi]
                inputs[f"{role}_{kind}"] = np.nan_to_num(data, nan=0)
            inputs[f"{role}_valid"] = self.geometry[f"{role}_valid"][lo:hi]
        labels = {"columns": ["sinr_db", "snr_db", "inr_db"],
                  "values": np.nan_to_num(measured, nan=0).astype(np.float32),
                  "mask": np.isfinite(measured),
                  "link_valid": self.observations.iloc[target_lo:target_hi].link_valid.to_numpy(bool)}
        return {"inputs": inputs, "labels": labels, "scenario_group_id": row.scenario_group_id, "split": row.split}
