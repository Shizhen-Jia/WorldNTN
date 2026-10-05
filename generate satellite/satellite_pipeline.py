"""Archived GP inputs and common real/synthetic satellite CSV generation.

All velocities are derivatives in the stated frame, including Earth rotation.
No network access occurs outside download_snapshot().
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
import json
import re
import warnings

import numpy as np
import pandas as pd
import requests
from sgp4.exporter import export_tle
from skyfield.api import EarthSatellite, load, wgs84
from skyfield.framelib import itrs

ROOT = Path(__file__).resolve().parent
CONSTELLATIONS = ("starlink", "kuiper", "oneweb")
BASE_URL = "https://celestrak.org/NORAD/elements/gp.php"
TS = load.timescale(builtin=True)
LEGACY_COLUMNS = [
    "Time", "Name", "Azimuth (°)", "Elevation (°)", "Orbit Altitude (km)",
    "Slant km", "x_East (m)", "y_North (m)", "z_Up (m)",
    "vx_East (m/s)", "vy_North (m/s)", "vz_Up (m/s)",
]
COLUMNS = LEGACY_COLUMNS + [
    "TimeIndex", "Satellite ID", "NORAD ID", "Constellation", "Source Type",
    "Is Synthetic", "Is DTC", "Shell ID", "Latitude (°)", "Longitude (°)",
    "x_ECEF (m)", "y_ECEF (m)", "z_ECEF (m)",
    "vx_ECEF (m/s)", "vy_ECEF (m/s)", "vz_ECEF (m/s)",
    "Speed ECEF (m/s)", "Speed GCRS (m/s)", "Range Rate (m/s)",
    "Element Epoch UTC", "Element Age (days)", "Source File", "Source SHA256",
]


def utc(value=None):
    if value is None:
        return datetime.now(timezone.utc)
    dt = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if dt.tzinfo is None:
        raise ValueError("A timezone is required; use an ISO UTC time ending in Z.")
    return dt.astimezone(timezone.utc)


def stamp():
    return utc().strftime("%Y%m%dT%H%M%S_%fZ")


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    temp.replace(path)


def is_dtc(name):
    return bool(re.search(r"\[DTC\]|\bDTC\b|DIRECT[ -]?TO[ -]?CELL", name, re.I))


@dataclass
class Satellite:
    sat: EarthSatellite
    constellation: str
    satellite_id: str
    norad_id: str = ""
    source_type: str = "real_gp"
    shell_id: str = ""
    source_file: str = ""
    source_sha256: str = ""

    @property
    def synthetic(self):
        return self.source_type != "real_gp"


def parse_omm(data):
    if not isinstance(data, list) or not data:
        raise ValueError("Expected a nonempty OMM JSON list, not an error page.")
    sats = []
    numeric = ("MEAN_MOTION", "ECCENTRICITY", "INCLINATION", "RA_OF_ASC_NODE",
               "ARG_OF_PERICENTER", "MEAN_ANOMALY", "BSTAR", "MEAN_MOTION_DOT", "MEAN_MOTION_DDOT")
    for item in data:
        if not isinstance(item, dict) or not item.get("OBJECT_NAME"):
            raise ValueError("Invalid OMM object/name.")
        if not np.isfinite([float(item[k]) for k in numeric]).all():
            raise ValueError("Nonfinite OMM elements.")
        if not (0 <= float(item["ECCENTRICITY"]) < 1 and float(item["MEAN_MOTION"]) > 0
                and 0 <= float(item["INCLINATION"]) <= 180 and int(item["NORAD_CAT_ID"]) > 0):
            raise ValueError("Invalid OMM orbit.")
        sat = EarthSatellite.from_omm(TS, dict(item))
        if not np.isfinite(sat.epoch.tt):
            raise ValueError("Invalid element epoch.")
        sats.append(sat)
    return _deduplicate(sats)


def _deduplicate(sats):
    unique = {}
    for sat in sats:
        key = sat.model.satnum
        if key not in unique or sat.epoch.tt > unique[key].epoch.tt:
            unique[key] = sat
    return list(unique.values())


def parse_tle(text):
    lines = [s.rstrip() for s in text.splitlines() if s.strip()]
    sats, i = [], 0
    while i < len(lines):
        name = ""
        if not lines[i].startswith("1 "):
            name = lines[i].removeprefix("0 ").strip()
            i += 1
        if i + 1 >= len(lines):
            raise ValueError("Incomplete TLE record.")
        l1, l2 = lines[i:i + 2]
        for number, line in ((1, l1), (2, l2)):
            if not line.startswith(f"{number} ") or len(line) != 69 or not line[-1].isdigit():
                raise ValueError("Invalid TLE format, possibly an HTTP error page.")
            checksum = sum(int(c) if c.isdigit() else int(c == "-") for c in line[:68]) % 10
            if checksum != int(line[-1]):
                raise ValueError("TLE checksum mismatch.")
        if l1[2:7] != l2[2:7]:
            raise ValueError("TLE catalog identifiers do not match.")
        sat = EarthSatellite(l1, l2, name or f"NORAD-{l1[2:7].strip()}", TS)
        if not np.isfinite([sat.model.no_kozai, sat.model.ecco, sat.epoch.tt]).all():
            raise ValueError("Nonfinite TLE elements.")
        sats.append(sat)
        i += 2
    if not sats:
        raise ValueError("No valid TLE records.")
    return _deduplicate(sats)


def _http_get(session, url):
    response = session.get(url, timeout=(15, 60), headers={"User-Agent": "WorldNTN-research/1.0"})
    response.raise_for_status()
    return response


def save_derived_tle(omm_path, destination, root=ROOT):
    """Export representable OMM records to TLE, explicitly labeled as converted.

    Never truncate six-digit NORAD IDs or claim that this is an HTTP TLE response.
    """
    root, omm_path, destination = Path(root), Path(omm_path), Path(destination)
    sats = parse_omm(json.loads(omm_path.read_text()))
    text, skipped = [], []
    for sat in sats:
        if sat.model.satnum > 99999:
            skipped.append(sat.model.satnum)
            continue
        l1, l2 = export_tle(sat.model)
        text.extend((sat.name, l1, l2))
    result = {"status": "derived_from_omm", "source_path": str(omm_path.relative_to(root)),
              "source_sha256": digest(omm_path), "skipped_six_digit_ids": skipped, "count": len(text) // 3}
    if text:
        content = "\n".join(text) + "\n"
        parse_tle(content)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
        result.update(path=str(destination.relative_to(root)), sha256=digest(destination))
    return result


def download_snapshot(root=ROOT, mode="auto", max_cache_hours=2.0, session=None):
    """Archive both original TLE and OMM JSON; JSON is required for completeness.

    auto reuses a recent complete snapshot; local never connects; refresh makes
    one request per constellation/format. HTTP failures are recorded, not hidden.
    """
    if mode not in {"auto", "local", "refresh"}:
        raise ValueError("mode must be auto, local, or refresh")
    root = Path(root)
    folder = root / "tle"
    folder.mkdir(parents=True, exist_ok=True)
    prior = []
    for p in sorted(folder.glob("snapshot_*.json"), reverse=True):
        info = json.loads(p.read_text())
        if info.get("complete"):
            prior.append((p, info))
    if prior:
        p, info = prior[0]
        age = (utc() - utc(info["fetched_at_utc"])).total_seconds() / 3600
        if mode == "local" or (mode == "auto" and age <= max_cache_hours):
            for c in CONSTELLATIONS:
                load_snapshot(c, p, root)
            if mode == "local" and age > max_cache_hours:
                warnings.warn(f"Using explicitly requested local snapshot, {age:.1f} hours old.")
            return p
    if mode == "local":
        raise FileNotFoundError("No complete local snapshot; run download_tle.ipynb in auto/refresh mode.")

    session = session or requests.Session()
    tag = stamp()
    manifest = {"fetched_at_utc": utc().isoformat(), "complete": False, "constellations": {}}
    for constellation in CONSTELLATIONS:
        records, parsed = {}, {}
        dest = folder / constellation
        dest.mkdir(exist_ok=True)
        for fmt, suffix in (("json", "omm.json"), ("tle", "tle")):
            url = f"{BASE_URL}?GROUP={constellation}&FORMAT={fmt.upper()}"
            rec = {"url": url, "requested_at_utc": utc().isoformat()}
            try:
                response = _http_get(session, url)
                sats = parse_omm(response.json()) if fmt == "json" else parse_tle(response.text)
                p = dest / f"{constellation}_{tag}.{suffix}"
                p.write_bytes(response.content)
                rec.update(status="ok", path=str(p.relative_to(root)), sha256=digest(p),
                           count=len(sats), epoch_min_utc=min(s.epoch.utc_iso() for s in sats),
                           epoch_max_utc=max(s.epoch.utc_iso() for s in sats))
                parsed[fmt] = {s.model.satnum for s in sats}
            except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
                rec.update(status="failed", error=f"{type(exc).__name__}: {exc}")
                warnings.warn(f"{constellation} {fmt}: {exc}")
            records[fmt] = rec
        records["omm_ids_absent_from_tle"] = sorted(parsed.get("json", set()) - parsed.get("tle", set()))
        if records["tle"]["status"] != "ok" and records["json"]["status"] == "ok":
            records["derived_tle"] = save_derived_tle(
                root / records["json"]["path"], dest / f"{constellation}_{tag}_derived_from_omm.tle", root)
        manifest["constellations"][constellation] = records
    manifest["complete"] = all(manifest["constellations"][c]["json"]["status"] == "ok" for c in CONSTELLATIONS)
    path = folder / f"snapshot_{tag}.json"
    write_json(path, manifest)
    if not manifest["complete"]:
        raise RuntimeError(f"Incomplete GP download; see {path}. Existing snapshots were preserved.")
    return path


def initialize_scenario(snapshot_manifest, root=ROOT, reset_start=False):
    root = Path(root)
    path = root / "scenario.json"
    cfg = json.loads(path.read_text())
    manifest = Path(snapshot_manifest).resolve()
    if not json.loads(manifest.read_text()).get("complete"):
        raise ValueError("Cannot select an incomplete snapshot.")
    cfg["snapshot_manifest"] = str(manifest.relative_to(root.resolve()))
    if cfg["start_time_utc"] is None or reset_start:
        cfg["start_time_utc"] = utc().replace(microsecond=0).isoformat()
    write_json(path, cfg)
    return cfg


def read_scenario(root=ROOT):
    cfg = json.loads((Path(root) / "scenario.json").read_text())
    if cfg.get("start_time_utc") is None:
        raise ValueError("Run download_tle.ipynb first, or set start_time_utc in scenario.json.")
    start = utc(cfg["start_time_utc"])
    duration, interval = cfg["duration_sec"], cfg["interval_sec"]
    if not (isinstance(duration, int) and isinstance(interval, int) and duration > 0 and interval > 0):
        raise ValueError("duration_sec and interval_sec must be positive integers.")
    if not (-90 <= cfg["lat_deg"] <= 90 and -180 <= cfg["lon_deg"] <= 180
            and -90 <= cfg["elev_min_deg"] <= 90 and cfg["max_slant_km"] > 0
            and cfg["max_element_age_days"] > 0):
        raise ValueError("Invalid observer, visibility, or element-age settings.")
    if len(cfg["az_range_deg"]) != 2:
        raise ValueError("az_range_deg requires two endpoints.")
    times = [start + timedelta(seconds=s) for s in range(0, duration, interval)]
    return cfg, times


def load_snapshot(constellation, manifest=None, root=ROOT):
    root = Path(root)
    if constellation not in CONSTELLATIONS:
        raise ValueError(f"Unknown constellation: {constellation}")
    if manifest is None:
        value = json.loads((root / "scenario.json").read_text()).get("snapshot_manifest")
        if not value:
            raise ValueError("Run download_tle.ipynb to select an archived snapshot.")
        manifest = root / value
    manifest = Path(manifest)
    if not manifest.is_absolute():
        manifest = root / manifest
    entry = json.loads(manifest.read_text())["constellations"][constellation]["json"]
    if entry["status"] != "ok":
        raise ValueError("Selected snapshot has no complete OMM JSON.")
    path = root / entry["path"]
    if digest(path) != entry["sha256"]:
        raise ValueError(f"Snapshot checksum mismatch: {path}")
    sats = parse_omm(json.loads(path.read_text()))
    if len(sats) != entry["count"]:
        raise ValueError("Snapshot count does not match manifest.")
    return [Satellite(s, constellation, f"real:{s.model.satnum}", str(s.model.satnum),
                      source_file=entry["path"], source_sha256=entry["sha256"]) for s in sats]


def load_tle_file(path, constellation):
    """Explicit offline legacy input; completeness is the caller's responsibility."""
    path = Path(path)
    warnings.warn("TLE-only input can omit satellites with six-digit NORAD IDs.")
    return [Satellite(s, constellation, f"real:{s.model.satnum}", str(s.model.satnum),
                      source_file=str(path), source_sha256=digest(path))
            for s in parse_tle(path.read_text())]


def enu_rotation(lat, lon):
    p, l = np.deg2rad([lat, lon])
    return np.array([[-np.sin(l), np.cos(l), 0],
                     [-np.sin(p)*np.cos(l), -np.sin(p)*np.sin(l), np.cos(p)],
                     [np.cos(p)*np.cos(l), np.cos(p)*np.sin(l), np.sin(p)]])


def azimuth_mask(az, bounds):
    lo, hi = np.asarray(bounds, dtype=float) % 360
    if lo == hi:
        return np.ones(np.shape(az), dtype=bool)
    return ((az >= lo) & (az < hi)) if lo < hi else ((az >= lo) | (az < hi))


def state_frame(record, times, cfg, sky_times=None, observer_state=None):
    """Vectorize all times for one satellite; do not finite-difference sparse CSVs."""
    t = sky_times if sky_times is not None else TS.from_datetimes(times)
    ground = wgs84.latlon(cfg["lat_deg"], cfg["lon_deg"], elevation_m=cfg["elev_m"])
    obs_p, obs_v = observer_state if observer_state is not None else ground.at(t).frame_xyz_and_velocity(itrs)
    geo = record.sat.at(t)
    p, v = geo.frame_xyz_and_velocity(itrs)
    pos, vel = p.m.T, v.m_per_s.T
    rot = enu_rotation(cfg["lat_deg"], cfg["lon_deg"])
    enu = (p.m - obs_p.m).T @ rot.T
    venu = (v.m_per_s - obs_v.m_per_s).T @ rot.T
    slant_m = np.linalg.norm(enu, axis=1)
    az = np.rad2deg(np.arctan2(enu[:, 0], enu[:, 1])) % 360
    elev = np.rad2deg(np.arctan2(enu[:, 2], np.hypot(enu[:, 0], enu[:, 1])))
    llh = wgs84.geographic_position_of(geo)
    data = {
        "Time": [dt.isoformat().replace("+00:00", "Z") for dt in times],
        "Name": record.sat.name, "Azimuth (°)": az, "Elevation (°)": elev,
        "Orbit Altitude (km)": llh.elevation.km, "Slant km": slant_m / 1000,
        "TimeIndex": np.arange(1, len(times) + 1), "Satellite ID": record.satellite_id,
        "NORAD ID": record.norad_id, "Constellation": record.constellation,
        "Source Type": record.source_type, "Is Synthetic": record.synthetic,
        "Is DTC": is_dtc(record.sat.name), "Shell ID": record.shell_id,
        "Latitude (°)": llh.latitude.degrees, "Longitude (°)": llh.longitude.degrees,
        "Speed ECEF (m/s)": np.linalg.norm(vel, axis=1),
        "Speed GCRS (m/s)": np.linalg.norm(geo.velocity.m_per_s.T, axis=1),
        "Range Rate (m/s)": np.sum(enu * venu, axis=1) / slant_m,
        "Element Epoch UTC": record.sat.epoch.utc_iso(places=6),
        "Element Age (days)": t.tt - record.sat.epoch.tt,
        "Source File": record.source_file, "Source SHA256": record.source_sha256,
    }
    for index, axis in enumerate(("East", "North", "Up")):
        data[f"{'xyz'[index]}_{axis} (m)"] = enu[:, index]
        data[f"v{'xyz'[index]}_{axis} (m/s)"] = venu[:, index]
    for index, axis in enumerate("xyz"):
        data[f"{axis}_ECEF (m)"] = pos[:, index]
        data[f"v{axis}_ECEF (m/s)"] = vel[:, index]
    frame = pd.DataFrame(data, columns=COLUMNS)
    valid = np.isfinite(frame.select_dtypes(include="number")).all(axis=1).to_numpy().copy()
    if geo.message is not None:
        messages = np.broadcast_to(np.asarray(geo.message, dtype=object), (len(times),))
        valid &= np.array([not bool(m) for m in messages])
    return frame, valid


def export_tracks(records, constellation, source_type="real_gp", root=ROOT, extra_metadata=None):
    """Save visibility CSV, optional global states, per-time counts and filter audit."""
    root = Path(root)
    cfg, times = read_scenario(root)
    if any(r.constellation != constellation or r.source_type != source_type for r in records):
        raise ValueError("Mixed constellation/source input; export separately.")
    if len({r.satellite_id for r in records}) != len(records):
        raise ValueError("Duplicate satellite IDs in input.")
    tag = stamp()
    dest = root / "outputs" / source_type / constellation / tag
    dest.mkdir(parents=True, exist_ok=False)
    visible_path = dest / f"{constellation}_{source_type}_{tag}_visible.csv"
    states_path = dest / f"{constellation}_{source_type}_{tag}_all_states.csv"
    pd.DataFrame(columns=COLUMNS).to_csv(visible_path, index=False)
    if cfg["write_all_states"]:
        pd.DataFrame(columns=COLUMNS).to_csv(states_path, index=False)
    counts = np.zeros(len(times), dtype=int)
    audits = []
    t = TS.from_datetimes(times)
    observer = wgs84.latlon(cfg["lat_deg"], cfg["lon_deg"], elevation_m=cfg["elev_m"])
    obs_state = observer.at(t).frame_xyz_and_velocity(itrs)
    excluded_ids = set(map(str, cfg.get("excluded_norad_ids", [])))
    metadata = {"status": "running", "created_at_utc": utc().isoformat(), "constellation": constellation,
                "source_type": source_type, "scenario": cfg, "satellite_count": len(records),
                "time_count": len(times), "sample_interval": "[start, start + duration)",
                "frames": {"ECEF": "ITRS", "inertial_speed": "GCRS", "ENU": "fixed observer, WGS84"},
                "propagator": "Skyfield SGP4; synthetic elements have zero drag",
                "extra": extra_metadata or {}}
    write_json(dest / "metadata.json", metadata)
    try:
        for record in records:
            audit = {"Satellite ID": record.satellite_id, "Name": record.sat.name,
                     "excluded_reason": "", "invalid_samples": 0, "stale_samples": 0,
                     "low_altitude_samples": 0, "retained_samples": 0, "visible_samples": 0}
            if cfg["exclude_dtc"] and is_dtc(record.sat.name):
                audit["excluded_reason"] = "dtc_name_marker"
            elif record.norad_id and record.norad_id in excluded_ids:
                audit["excluded_reason"] = "explicit_norad_exclusion"
            if audit["excluded_reason"]:
                audits.append(audit)
                continue
            frame, valid = state_frame(record, times, cfg, t, obs_state)
            age_ok = np.abs(frame["Element Age (days)"].to_numpy()) <= cfg["max_element_age_days"]
            # Synthetic epoch age is a simulation duration, not a stale measurement.
            if record.synthetic:
                age_ok[:] = True
            height = cfg["min_orbit_altitude_km"].get(constellation)
            high = np.ones(len(times), bool) if height is None else frame["Orbit Altitude (km)"].to_numpy() >= height
            keep = valid & age_ok & high
            visible = (keep & (frame["Elevation (°)"].to_numpy() >= cfg["elev_min_deg"])
                       & azimuth_mask(frame["Azimuth (°)"].to_numpy(), cfg["az_range_deg"])
                       & (frame["Slant km"].to_numpy() <= cfg["max_slant_km"]))
            if cfg["write_all_states"]:
                frame.loc[keep].to_csv(states_path, index=False, header=False, mode="a", float_format="%.9f")
            frame.loc[visible].to_csv(visible_path, index=False, header=False, mode="a", float_format="%.9f")
            counts += visible
            audit.update(invalid_samples=int((~valid).sum()), stale_samples=int((valid & ~age_ok).sum()),
                         low_altitude_samples=int((valid & age_ok & ~high).sum()),
                         retained_samples=int(keep.sum()), visible_samples=int(visible.sum()))
            audits.append(audit)
        audit_frame = pd.DataFrame(audits, columns=["Satellite ID", "Name", "excluded_reason", "invalid_samples",
                                                  "stale_samples", "low_altitude_samples", "retained_samples", "visible_samples"])
        audit_frame.to_csv(dest / "filter_audit.csv", index=False)
        pd.DataFrame({"Time": [x.isoformat().replace("+00:00", "Z") for x in times],
                      "TimeIndex": np.arange(1, len(times) + 1), "Visible Count": counts}).to_csv(dest / "counts.csv", index=False)
        # Visibility data is normally small; sort for compatibility with the reference notebooks.
        visible_df = pd.read_csv(visible_path, dtype={"NORAD ID": "string"})
        visible_df.sort_values(["TimeIndex", "Slant km", "Satellite ID"]).to_csv(visible_path, index=False)
        metadata.update(status="complete", visible_rows=int(counts.sum()),
                        mean_visible_count=float(counts.mean()), visible_csv=visible_path.name,
                        visible_sha256=digest(visible_path),
                        all_states_csv=states_path.name if cfg["write_all_states"] else None,
                        retained_samples=int(audit_frame["retained_samples"].sum()))
        if records and metadata["retained_samples"] == 0:
            warnings.warn("No satellite states survived; inspect filter_audit.csv for stale/low/invalid elements.")
    except Exception as exc:
        metadata.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        write_json(dest / "metadata.json", metadata)
        raise
    write_json(dest / "metadata.json", metadata)
    return {"visible_csv": visible_path, "metadata": dest / "metadata.json",
            "counts_csv": dest / "counts.csv", "audit_csv": dest / "filter_audit.csv"}


def preview_export(result):
    info = json.loads(Path(result["metadata"]).read_text())
    print(f"CSV: {result['visible_csv']}")
    print(f"Rows: {info['visible_rows']}; mean visible count (including zero-count times): {info['mean_visible_count']:.3f}")
    return pd.read_csv(result["visible_csv"], nrows=8)


def merge_exports(csv_paths, output):
    """Explicit future merge: require matching scenarios and disjoint satellite IDs."""
    if len(csv_paths) < 2:
        raise ValueError("Supply at least two CSVs.")
    frames, manifests, ids, synthetic_kinds = [], [], set(), {}
    reference = None
    for item in csv_paths:
        p = Path(item)
        meta = json.loads((p.parent / "metadata.json").read_text())
        if meta["status"] != "complete" or p.name != meta["visible_csv"] or digest(p) != meta["visible_sha256"]:
            raise ValueError("Only complete, unchanged visibility exports can be merged.")
        if reference is None:
            reference = meta["scenario"]
        elif meta["scenario"] != reference:
            raise ValueError("Scenario/snapshot mismatch; regenerate on the same observer and time grid.")
        frame = pd.read_csv(p, dtype={"NORAD ID": "string"})
        if list(frame.columns) != COLUMNS:
            raise ValueError("CSV schema mismatch.")
        current = set(pd.read_csv(p.parent / "filter_audit.csv")["Satellite ID"])
        if current & ids:
            raise ValueError("Duplicate satellite identities; do not merge repeated real/synthetic runs.")
        ids |= current
        if meta["source_type"] != "real_gp":
            c = meta["constellation"]
            if c in synthetic_kinds:
                raise ValueError("Choose one synthetic scenario per constellation.")
            synthetic_kinds[c] = meta["source_type"]
        frames.append(frame)
        manifests.append(str(p))
    out = pd.concat(frames, ignore_index=True).sort_values(["TimeIndex", "Slant km", "Satellite ID"])
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(output, index=False)
    write_json(output.with_suffix(".metadata.json"), {"inputs": manifests, "scenario": reference, "rows": len(out)})
    return output
