"""Separate approved-shell augmentation from wholly user-defined constellations."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import json
import warnings

import numpy as np
import pandas as pd
from sgp4.api import Satrec, WGS72, jday
from skyfield.api import EarthSatellite

from satellite_pipeline import ROOT, TS, Satellite, digest, is_dtc, stamp, utc, write_json

ELEMENT_COLUMNS = ["satellite_id", "name", "constellation", "source_type", "shell_id", "epoch_utc",
                   "altitude_km", "inclination_deg", "eccentricity", "raan_deg", "arg_perigee_deg",
                   "mean_anomaly_deg", "mean_motion_rev_per_day", "plane_index", "slot_index",
                   "raan_span_deg", "walker_f", "seed", "source_url"]


def validate_shells(shells, constellation, approved=False):
    if not shells:
        raise ValueError(f"No shells for {constellation}.")
    if len({s["shell_id"] for s in shells}) != len(shells):
        raise ValueError("Duplicate shell IDs.")
    for s in shells:
        if s["constellation"] != constellation:
            raise ValueError("Mixed constellation shells.")
        for key in ("planes", "satellites_per_plane", "satellite_count"):
            value = s[key]
            if isinstance(value, bool) or int(value) != value or value <= 0:
                raise ValueError(f"{key} must be a positive integer.")
        if s["satellite_count"] != s["planes"] * s["satellites_per_plane"]:
            raise ValueError("Satellite count must equal planes × satellites per plane.")
        if not (200 <= s["altitude_km"] <= 2000 and 0 <= s["inclination_deg"] <= 180):
            raise ValueError("Expected finite LEO altitude (200–2000 km) and inclination (0–180 deg).")
        if approved and s.get("authorization_status") != "approved":
            raise ValueError("An application/proposal cannot be used as an approved shell.")
        if not 0 < s.get("raan_span_deg", 360) <= 360:
            raise ValueError("RAAN span must be in (0, 360].")
        f = s.get("walker_f", 1 if s["planes"] > 1 else 0)
        if int(f) != f or not 0 <= f < s["planes"]:
            raise ValueError("Walker F must be an integer in [0, planes).")


def approved_shells(constellation, root=ROOT):
    table = pd.read_csv(Path(root) / "orbit_info" / "approved_shells.csv")
    shells = table.loc[table.constellation == constellation].to_dict("records")
    validate_shells(shells, constellation, approved=True)
    return shells


def custom_shells(constellation, root=ROOT):
    data = json.loads((Path(root) / "orbit_info" / "custom_shells.json").read_text())
    shells = [s for s in data["shells"] if s["constellation"] == constellation]
    validate_shells(shells, constellation)
    return shells


def estimate_deficits(shells, records, epoch_utc, inclination_tolerance_deg=1.0, max_age_days=14.0):
    """Conservative shell counts, NOT identification of actual unlaunched spacecraft.

    Count the full catalog before observer, operational-height or DTC filtering.
    DTC-marked objects are excluded; raising satellites and spares still count.
    A shell assignment uses inclination, then nearest nominal mean altitude.
    """
    if not records:
        raise ValueError("Approved augmentation requires a nonempty real GP snapshot.")
    constellation = shells[0]["constellation"]
    if any(r.synthetic or r.constellation != constellation for r in records):
        raise ValueError("Deficit estimation requires real data from this constellation only.")
    if len({r.satellite_id for r in records}) != len(records):
        raise ValueError("Deduplicate NORAD IDs before deficit estimation.")
    epoch = TS.from_datetime(utc(epoch_utc))
    ages = [abs(float(epoch.tt - r.sat.epoch.tt)) for r in records]
    if min(ages) > max_age_days:
        raise ValueError("Entire catalog is stale relative to the scenario epoch; refresh or choose matching archived data.")
    counts = {s["shell_id"]: 0 for s in shells}
    assignments = []
    for rec, age in zip(records, ages):
        model = rec.sat.model
        inc = float(np.rad2deg(model.inclo))
        altitude = float((model.a - 1) * model.radiusearthkm)
        candidates = [s for s in shells if abs(inc - s["inclination_deg"]) <= inclination_tolerance_deg
                      and 200 <= altitude <= s["altitude_km"] + 150]
        chosen = None if is_dtc(rec.sat.name) or not candidates else min(
            candidates, key=lambda s: (abs(inc - s["inclination_deg"]), abs(altitude - s["altitude_km"])))
        shell_id = chosen["shell_id"] if chosen else ""
        if chosen:
            counts[shell_id] += 1
        assignments.append({"Satellite ID": rec.satellite_id, "Name": rec.sat.name,
                            "shell_id": shell_id, "mean_altitude_km": altitude, "inclination_deg": inc,
                            "element_age_days": age, "stale": age > max_age_days,
                            "reason": "counted_including_raising_and_spares" if chosen else "unmatched_or_dtc"})
    if any(a > max_age_days for a in ages):
        warnings.warn("Some catalog elements are stale; conservatively counted when assignable. Inspect real_assignments.csv.")
    summary = []
    for s in shells:
        n, target = counts[s["shell_id"]], int(s["satellite_count"])
        summary.append({"shell_id": s["shell_id"], "approved_target": target, "catalog_assigned": n,
                        "synthetic_deficit": max(0, target - n), "catalog_above_target": max(0, n - target)})
    return pd.DataFrame(summary), pd.DataFrame(assignments)


def _satellite_from_elements(row):
    dt = utc(row["epoch_utc"])
    jd, fr = jday(dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second + dt.microsecond / 1e6)
    satrec = Satrec()
    # The internal number is a propagator placeholder, never exported as a NORAD ID.
    satrec.sgp4init(WGS72, "i", 1, (jd - 2433281.5) + fr, 0.0, 0.0, 0.0,
                   row["eccentricity"], np.deg2rad(row["arg_perigee_deg"]),
                   np.deg2rad(row["inclination_deg"]), np.deg2rad(row["mean_anomaly_deg"]),
                   row["mean_motion_rev_per_day"] * 2 * np.pi / 1440, np.deg2rad(row["raan_deg"]))
    sat = EarthSatellite.from_satrec(satrec, TS)
    sat.name = row["name"]
    return sat


def build_virtual(constellation, mode, epoch_utc, records=None, seed=20261005,
                  root=ROOT, shells_override=None, max_age_days=14.0):
    """Return synthetic records plus archived shell, phase and population assumptions.

    mode=approved_missing subtracts global catalog shell counts.
    mode=custom generates every configured custom satellite as additional objects.
    """
    if mode not in {"approved_missing", "custom"}:
        raise ValueError("mode must be approved_missing or custom")
    root = Path(root)
    epoch_utc = utc(epoch_utc).isoformat()
    if mode == "approved_missing":
        if shells_override is not None:
            raise ValueError("Approved values come from the cited CSV; use custom mode for arbitrary shells.")
        shells = approved_shells(constellation, root)
        summary, assignments = estimate_deficits(shells, records or [], epoch_utc, max_age_days=max_age_days)
        source_type = "approved_shell_synthetic"
    else:
        shells = custom_shells(constellation, root) if shells_override is None else shells_override
        validate_shells(shells, constellation)
        summary = pd.DataFrame([{"shell_id": s["shell_id"], "synthetic_deficit": s["satellite_count"]} for s in shells])
        assignments = None
        source_type = "custom_synthetic"
    dest = root / "orbit_info" / "generated" / source_type / constellation / stamp()
    dest.mkdir(parents=True, exist_ok=False)
    summary.to_csv(dest / "population.csv", index=False)
    if assignments is not None:
        assignments.to_csv(dest / "real_assignments.csv", index=False)
    rows = []
    realization = sha256(json.dumps({"shells": shells, "seed": seed, "epoch": epoch_utc}, sort_keys=True).encode()).hexdigest()[:12]
    for shell in shells:
        shell_key = shell["shell_id"]
        rng = np.random.default_rng(int.from_bytes(sha256(f"{seed}:{shell_key}".encode()).digest()[:8], "big"))
        count = int(summary.set_index("shell_id").loc[shell_key, "synthetic_deficit"])
        planes, spp, total = (int(shell[k]) for k in ("planes", "satellites_per_plane", "satellite_count"))
        # Select distributed template slots rather than filling only the first planes.
        slots = np.sort(rng.choice(total, size=count, replace=False))
        raan0, phase0 = rng.uniform(0, 360, 2)
        span = shell.get("raan_span_deg", 180 if 80 <= shell["inclination_deg"] <= 100 else 360)
        walker_f = shell.get("walker_f", 1 if planes > 1 else 0)
        # WGS72 constants match the SGP4 propagator; height here defines mean a-R.
        motion = np.sqrt(398600.8 / (6378.135 + shell["altitude_km"])**3) * 86400 / (2 * np.pi)
        for slot in slots:
            plane, in_plane = divmod(int(slot), spp)
            identifier = f"{source_type}:{constellation}:{realization}:{shell_key}:p{plane:04d}:s{in_plane:03d}"
            rows.append({"satellite_id": identifier,
                         "name": f"SYN-{constellation.upper()}-{shell_key}-P{plane:04d}-S{in_plane:03d}",
                         "constellation": constellation, "source_type": source_type, "shell_id": shell_key,
                         "epoch_utc": epoch_utc, "altitude_km": shell["altitude_km"],
                         "inclination_deg": shell["inclination_deg"], "eccentricity": 0.0,
                         "raan_deg": (raan0 + span * plane / planes) % 360, "arg_perigee_deg": 0.0,
                         "mean_anomaly_deg": (phase0 + 360 * in_plane / spp + 360 * walker_f * plane / total) % 360,
                         "mean_motion_rev_per_day": float(motion), "plane_index": plane, "slot_index": in_plane,
                         "raan_span_deg": span, "walker_f": walker_f, "seed": seed, "source_url": shell.get("source_url", "user_defined")})
    elements = pd.DataFrame(rows, columns=ELEMENT_COLUMNS)
    elements_path = dest / "synthetic_mean_elements.csv"
    elements.to_csv(elements_path, index=False, float_format="%.15g")
    assumptions = {
        "mode": mode, "source_type": source_type, "epoch_utc": epoch_utc, "seed": seed, "shells": shells,
        "official_fields": ["altitude_km", "inclination_deg", "planes", "satellites_per_plane", "satellite_count"] if mode == "approved_missing" else [],
        "assumed_fields": ["RAAN origin and uniform spacing", "mean anomaly and Walker F", "circular mean orbit", "zero drag", "template slot subset"],
        "population_method": "max(approved count - full GP catalog shell count, 0)" if mode == "approved_missing" else "all configured objects, additional to real catalog",
        "inclination_assignment_tolerance_deg": 1.0,
        "height_assignment_window_km": "200 <= mean altitude <= shell altitude + 150",
        "limitations": "Catalog deficits are not verified unlaunched satellite counts. Template slots are not known vacant operator slots. No launch schedule, mission status, stationkeeping or collision avoidance is inferred.",
        "source_snapshots": sorted({(r.source_file, r.source_sha256) for r in (records or [])}),
        "elements_sha256": digest(elements_path), "synthetic_count": len(elements),
    }
    write_json(dest / "assumptions.json", assumptions)
    # Reload rounded archived values so the CSV is exactly the propagation input.
    virtual = load_virtual_elements(elements_path)
    return virtual, {"orbit_directory": str(dest.relative_to(root)), "assumptions": assumptions}


def load_virtual_elements(path):
    path = Path(path)
    table = pd.read_csv(path)
    checksum = digest(path)
    records = []
    for row in table.to_dict("records"):
        if row["source_type"] not in {"approved_shell_synthetic", "custom_synthetic"}:
            raise ValueError("Invalid synthetic source label.")
        records.append(Satellite(_satellite_from_elements(row), row["constellation"], row["satellite_id"],
                                 source_type=row["source_type"], shell_id=row["shell_id"],
                                 source_file=str(path), source_sha256=checksum))
    return records
