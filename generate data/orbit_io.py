"""Read frozen CSVs, keeping absent states masked and never interpolating them."""
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import json
import warnings

import numpy as np
import pandas as pd

from config import constellation_name

POSITION_COLUMNS = [f"{a}_ECEF (m)" for a in "xyz"]
VELOCITY_COLUMNS = [f"v{a}_ECEF (m/s)" for a in "xyz"]


def file_hash(path):
    h = sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_times(values, assume_naive_utc=False):
    strings = pd.Series(values, dtype="string")
    if not assume_naive_utc and not strings.str.contains(r"(?:Z|[+-]\d{2}:?\d{2})$", regex=True).all():
        raise ValueError("CSV times require a timezone; explicitly set assume_naive_utc for legacy UTC files.")
    return pd.DatetimeIndex(pd.to_datetime(strings, utc=True, format="mixed", errors="raise"))


@dataclass
class OrbitCube:
    constellation: str
    times: pd.DatetimeIndex
    ids: np.ndarray
    positions: np.ndarray
    velocities: np.ndarray
    valid: np.ndarray
    sources: list


def discover_csvs(root):
    """Show explicit choices; do not silently combine alternative scenarios."""
    rows = []
    for p in sorted(Path(root).rglob("*.csv")):
        if "outputs" not in p.parts:
            continue
        kind = "all_states" if p.name.endswith("_all_states.csv") else "visible" if p.name.endswith("_visible.csv") else None
        if kind is None:
            continue
        meta_path = p.parent / "metadata.json"
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        rows.append({"path": str(p.resolve()), "constellation": meta.get("constellation", "unknown"),
                     "source_type": meta.get("source_type", "unknown"), "coverage": kind,
                     "status": meta.get("status", "unverified"), "size_mb": round(p.stat().st_size/1e6, 2)})
    return pd.DataFrame(rows, columns=["path", "constellation", "source_type", "coverage", "status", "size_mb"])


def _inspect(path, constellation, cfg):
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    header = list(pd.read_csv(path, nrows=0).columns)
    needed = ["Time", *POSITION_COLUMNS, *VELOCITY_COLUMNS]
    missing = set(needed) - set(header)
    if missing:
        raise ValueError(f"{path.name}: missing {sorted(missing)}. Export ECEF all_states CSVs; ENU alone is observer-dependent.")
    id_col = "Satellite ID" if "Satellite ID" in header else "Name"
    if id_col not in header:
        raise ValueError("CSV needs Satellite ID or Name.")
    meta_path = path.parent / "metadata.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    grid, coverage = None, "unverified"
    if meta:
        if meta.get("status") != "complete":
            raise ValueError(f"Upstream export did not complete: {path}")
        if constellation_name(meta["constellation"]) != constellation:
            raise ValueError(f"Wrong constellation CSV for {constellation}: {path}")
        if path.name == meta.get("all_states_csv"):
            coverage = "all_states"
        elif path.name == meta.get("visible_csv"):
            coverage = "visible"
            if file_hash(path) != meta["visible_sha256"]:
                raise ValueError("Upstream visibility checksum mismatch.")
        else:
            raise ValueError("CSV filename is not registered in its upstream metadata.")
        scenario = meta["scenario"]
        start = pd.Timestamp(scenario["start_time_utc"])
        if start.tzinfo is None:
            raise ValueError("Upstream start time must include a timezone.")
        step = int(scenario["interval_sec"])
        duration = int(scenario["duration_sec"])
        if step <= 0 or duration <= 0:
            raise ValueError("Invalid upstream time grid.")
        grid = pd.date_range(start.tz_convert("UTC"), periods=len(range(0, duration, step)), freq=pd.Timedelta(seconds=step))
    if coverage == "visible" and not cfg.allow_partial_catalog:
        raise ValueError("A visible-only CSV omits satellites needed at B and low-elevation interferers at A. "
                         "Set write_all_states=true in generate satellite/scenario.json and rerun its tracker. "
                         "allow_partial_catalog=True is only for explicitly labeled incomplete diagnostics.")
    if coverage == "unverified" and not cfg.allow_unverified_csv:
        raise ValueError("No upstream metadata. Set allow_unverified_csv=True only if ECEF units, native grid and full coverage were verified.")
    info = {"path": str(path), "sha256": file_hash(path), "coverage": coverage,
            "source_type": meta.get("source_type", "unverified"),
            "metadata_sha256": file_hash(meta_path) if meta else None,
            "upstream_scenario": meta.get("scenario")}
    return path, id_col, header, grid, info


def load_orbits(paths, constellation, cfg):
    """Two passes over CSV chunks avoid concatenating full multi-million-row tables."""
    constellation = constellation_name(constellation)
    if not paths:
        raise ValueError(f"Select at least one {constellation} CSV in main.ipynb.")
    inspected = [_inspect(p, constellation, cfg) for p in paths]
    if len({x[0] for x in inspected}) != len(inspected):
        raise ValueError("Duplicate CSV path.")
    synthetic_types = {x[4]["source_type"] for x in inspected} & {"approved_shell_synthetic", "custom_synthetic"}
    if len(synthetic_types) > 1:
        raise ValueError("Choose approved or custom synthetic augmentation, not both.")
    grid = None
    ids, observed_ns = set(), set()
    start = pd.Timestamp(cfg.start_time_utc) if cfg.start_time_utc else None
    if start is not None and start.tzinfo is None:
        raise ValueError("start_time_utc must include a timezone.")
    for path, id_col, header, source_grid, info in inspected:
        if source_grid is not None:
            if grid is not None and not grid.equals(source_grid):
                raise ValueError("Selected CSVs have different upstream grids; regenerate on one common grid.")
            grid = source_grid
        columns = ["Time", id_col] + (["Constellation"] if "Constellation" in header else [])
        for chunk in pd.read_csv(path, usecols=columns, dtype={id_col: "string"}, chunksize=100000):
            if "Constellation" in chunk and any(constellation_name(x) != constellation for x in chunk["Constellation"].dropna().unique()):
                raise ValueError("Mixed or incorrectly selected constellation CSV.")
            if chunk[id_col].isna().any() or chunk[id_col].str.strip().eq("").any():
                raise ValueError("Empty satellite identifier.")
            times = read_times(chunk["Time"], cfg.assume_naive_utc)
            ids.update(chunk[id_col].astype(str))
            observed_ns.update(times.as_unit("ns").asi8.tolist())
    if grid is None:
        grid = pd.to_datetime(sorted(observed_ns), utc=True, unit="ns")
        warnings.warn("Unverified CSV: complete grid inferred from observed timestamps; wholly absent end intervals cannot be recovered.")
    if observed_ns and not observed_ns.issubset(set(grid.as_unit("ns").asi8.tolist())):
        raise ValueError("CSV contains timestamps outside its declared grid.")
    if start is not None:
        grid = grid[grid >= start]
    if cfg.max_steps is not None:
        grid = grid[:cfg.max_steps]
    if len(grid) < 2:
        raise ValueError("At least two time samples are required.")
    deltas = np.diff(grid.as_unit("ns").asi8)
    if not np.all(deltas == deltas[0]) or deltas[0] <= 0:
        raise ValueError("Native grid must be uniformly spaced with no gaps; no automatic interpolation.")
    ids = np.array(sorted(ids), dtype=str)
    positions = np.full((len(grid), len(ids), 3), np.nan, dtype=np.float64)
    velocities = np.full_like(positions, np.nan)
    valid = np.zeros(positions.shape[:2], bool)
    index = pd.Index(ids)
    for path, id_col, header, _, info in inspected:
        columns = ["Time", id_col, *POSITION_COLUMNS, *VELOCITY_COLUMNS]
        for chunk in pd.read_csv(path, usecols=columns, dtype={id_col: "string"}, chunksize=100000):
            ti = grid.get_indexer(read_times(chunk["Time"], cfg.assume_naive_utc))
            keep = ti >= 0
            if not keep.any():
                continue
            chunk = chunk.loc[keep]
            ti = ti[keep]
            si = index.get_indexer(chunk[id_col].astype(str))
            flat = ti * len(ids) + si
            if len(np.unique(flat)) != len(flat) or valid[ti, si].any():
                raise ValueError("Duplicate (Time, Satellite ID); remove overlapping exports instead of double counting.")
            p, v = chunk[POSITION_COLUMNS].to_numpy(float), chunk[VELOCITY_COLUMNS].to_numpy(float)
            if not np.isfinite(p).all() or not np.isfinite(v).all():
                raise ValueError("Nonfinite CSV state. Missing records should be absent, not malformed rows.")
            radius = np.linalg.norm(p, axis=1)
            if np.any((radius < 6.3e6) | (radius > 9e6)) or np.any(np.linalg.norm(v, axis=1) > 12000):
                raise ValueError("Expected LEO ECEF position in metres and velocity in metres/second.")
            positions[ti, si], velocities[ti, si], valid[ti, si] = p, v, True
        if file_hash(path) != info["sha256"]:
            raise ValueError("Input CSV changed while it was being read.")
    return OrbitCube(constellation, grid, ids, positions, velocities, valid, [x[4] for x in inspected])


def load_pair(victim_paths, aggressor_paths, cfg):
    cfg.validate()
    a = load_orbits(victim_paths, cfg.victim, cfg)
    b = load_orbits(aggressor_paths, cfg.aggressor, cfg)
    if not a.times.equals(b.times):
        raise ValueError("A and B require exactly matching UTC sampling grids.")
    step_s = (a.times[1] - a.times[0]).total_seconds()
    if step_s > 10:
        warnings.warn(f"Native sampling is {step_s:g} s. Two bad samples take about {2*step_s:g} s; "
                      "regenerate upstream at 1–5 s for fine handover experiments.")
    return a, b
