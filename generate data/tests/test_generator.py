"""Numerical, causal and input-integrity checks on tiny diagnostic geometries."""
from dataclasses import replace
from pathlib import Path
import json
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import SimulationConfig, GroundStation, RadioConfig, TriggerConfig, constellation_name
from physics import fspl_db, noise_power_w, power_w, ratios_db, ground_ecef
from orbit_io import OrbitCube, POSITION_COLUMNS, VELOCITY_COLUMNS, load_orbits, load_pair
from simulation import simulate, remaining_runs, quality_points
from dataset import run_dataset, TrainingView


def config(**changes):
    base = SimulationConfig(ground_a=GroundStation(0, 0, 0), ground_b=GroundStation(0, .01, 0),
                            history_samples=2, prediction_samples=1, max_steps=None)
    return replace(base, **changes)


def cube(constellation, heights_km, mask=None):
    heights = np.asarray(heights_km, float)
    if heights.ndim == 1:
        heights = np.tile(heights, (8, 1))
    t, n = heights.shape
    positions = np.zeros((t, n, 3))
    positions[..., 0] = 6378137 + heights*1000
    velocities = np.gradient(positions, axis=0)
    valid = np.ones((t, n), bool) if mask is None else np.asarray(mask, bool)
    return OrbitCube(constellation, pd.date_range("2026-10-05T12:00:00Z", periods=t, freq="s"),
                     np.array([f"{constellation}:{i}" for i in range(n)]), positions, velocities, valid, [])


def write_cube(root, c, coverage="all_states"):
    folder = root / c.constellation
    folder.mkdir(parents=True, exist_ok=True)
    rows = []
    for k, time in enumerate(c.times):
        for j, sat_id in enumerate(c.ids):
            if not c.valid[k, j]:
                continue
            row = {"Time": time.isoformat(), "Satellite ID": sat_id, "Constellation": c.constellation}
            row.update(dict(zip(POSITION_COLUMNS, c.positions[k, j])))
            row.update(dict(zip(VELOCITY_COLUMNS, c.velocities[k, j])))
            rows.append(row)
    path = folder / f"fixture_{coverage}.csv"
    pd.DataFrame(rows, columns=["Time", "Satellite ID", "Constellation", *POSITION_COLUMNS, *VELOCITY_COLUMNS]).to_csv(path, index=False)
    from orbit_io import file_hash
    meta = {"status": "complete", "constellation": c.constellation, "source_type": "real_gp",
            "all_states_csv": path.name if coverage == "all_states" else None,
            "visible_csv": path.name if coverage == "visible" else None, "visible_sha256": file_hash(path),
            "scenario": {"start_time_utc": c.times[0].isoformat(), "duration_sec": len(c.times), "interval_sec": 1}}
    (folder / "metadata.json").write_text(json.dumps(meta))
    return path


def fixture_pair(tmp_path):
    a, b = cube("starlink", [600, 700]), cube("kuiper", [600])
    return write_cube(tmp_path, a), write_cube(tmp_path, b)


def test_fspl_and_recommended_power_budget():
    radio = RadioConfig()
    assert fspl_db(600000, 20e9) == pytest.approx(174.031408, abs=1e-5)
    assert 10*np.log10(power_w(600000, radio)/noise_power_w(radio)) == pytest.approx(9.964379, abs=1e-5)
    assert fspl_db(1200000, 20e9) - fspl_db(600000, 20e9) == pytest.approx(6.0205999)
    np.testing.assert_allclose(ground_ecef(GroundStation(0, 0, 0)), [6378137, 0, 0])


def test_sinr_linear_addition_and_no_interference():
    sinr, snr, inr = ratios_db(10.0, 3.0, 1.0)
    assert sinr == pytest.approx(10*np.log10(2.5))
    assert sinr == pytest.approx(snr - 10*np.log10(1 + 10**(inr/10)))
    sinr, snr, inr = ratios_db(10, 0, 1)
    assert sinr == snr and np.isnan(inr)
    assert np.isnan(ratios_db(0, 1, 1)[0])


def test_trigger_boundaries_and_two_fives_execute_next_sample():
    trigger = TriggerConfig()
    assert [quality_points(x, trigger) for x in [-.01, 0, 2.99, 3, 5.99, 6, np.nan]] == [5, 3, 3, 2, 2, 1, 5]
    result = simulate(cube("starlink", [600, 700]), cube("kuiper", [600]), config())
    assert result.observations.quality_points.iloc[:2].tolist() == [5, 5]
    assert result.actions.iloc[0].action == "hold"
    assert result.actions.iloc[1].action == "handover"
    assert result.executions.iloc[0].execute_index == 2
    assert result.observations.iloc[1].a_satellite_id == "starlink:0"
    assert result.observations.iloc[2].a_satellite_id == "starlink:1"
    assert result.observations.iloc[2].window_points == 5


def test_no_interference_good_link_does_not_accumulate_forever():
    cfg = config(radio=replace(RadioConfig(), interference_enabled=False))
    result = simulate(cube("starlink", [600, 700]), cube("kuiper", [600]), cfg)
    np.testing.assert_allclose(result.observations.sinr_db, result.observations.snr_db)
    assert result.observations.window_points.max() == 5
    assert result.executions.empty
    assert result.observations.inr_linear.eq(0).all()
    assert result.observations.inr_db.isna().all()


def test_falling_snr_without_interference_can_trigger():
    cfg = config(victim_initial_policy="max_snr", radio=replace(RadioConfig(), interference_enabled=False))
    a = cube("starlink", [[600, 1500], [2000, 1500], [2000, 1500], [2000, 1500], [2000, 1500]])
    b = cube("kuiper", np.full((5, 1), 600))
    result = simulate(a, b, cfg)
    assert result.observations.iloc[1].sinr_db < 0
    assert result.observations.iloc[2].sinr_db < 0
    assert result.executions.iloc[0].execute_index == 3
    assert result.observations.iloc[3].a_satellite_id == "starlink:1"


def test_longest_remaining_counts_consecutive_not_disjoint_coverage():
    eligibility = np.array([[True, True], [False, True], [True, True]])
    assert remaining_runs(eligibility)[0].tolist() == [1, 3]
    a = cube("starlink", np.full((3, 2), 600), eligibility)
    b = cube("kuiper", np.full((3, 1), 600))
    assert simulate(a, b, config()).observations.iloc[0].a_satellite_id == "starlink:1"


def test_no_candidate_is_blocked_and_current_satellite_not_reselected():
    result = simulate(cube("starlink", [600]), cube("kuiper", [600]), config())
    assert result.executions.empty
    assert "blocked_no_candidate" in result.actions.action.values
    assert result.actions.target_satellite_id.eq("").all()


def test_candidate_must_survive_execution_boundary():
    mask = np.array([[True, True], [True, True], [True, False], [True, False]])
    result = simulate(cube("starlink", np.full((4, 2), 600), mask),
                      cube("kuiper", np.full((4, 1), 600)), config())
    assert result.actions.iloc[1].action == "blocked_no_candidate"


def test_geometry_loss_uses_window_unless_emergency_mode_enabled():
    a = cube("starlink", [600, 700])
    a.valid[1:, 0] = False
    b = cube("kuiper", [600])
    base = config(victim_initial_policy="max_snr", radio=replace(RadioConfig(), interference_enabled=False))
    normal = simulate(a, b, base)
    assert normal.observations.iloc[1].window_points == 6
    assert normal.actions.iloc[1].action == "hold"
    assert normal.executions.iloc[0].execute_index == 3
    emergency = simulate(a, b, replace(base, trigger=replace(base.trigger, force_on_geometry_loss=True)))
    assert emergency.executions.iloc[0].execute_index == 2


def test_no_initial_candidates_preserves_outage_and_empty_events():
    a = cube("starlink", [600])
    a.valid[:] = False
    result = simulate(a, cube("kuiper", [600]), config())
    assert not result.observations.link_valid.any()
    assert result.observations.sinr_db.isna().all()
    assert result.observations.a_satellite_index.eq(-1).all()
    assert result.executions.empty
    assert not result.link_segments.score_label_valid.any()


def test_below_horizon_b_cannot_interfere():
    cfg = config(ground_b=GroundStation(0, 180, 0))
    b = cube("kuiper", [600])
    b.positions[..., 0] *= -1
    result = simulate(cube("starlink", [600]), b, cfg)
    assert result.aggressor_trace.b_satellite_id.eq("kuiper:0").all()
    assert result.observations.interference_present.eq(False).all()
    np.testing.assert_allclose(result.observations.sinr_db, result.observations.snr_db)


def test_b_schedule_and_interference_are_exogenous_to_a_policy():
    a, b = cube("starlink", [600, 700, 800]), cube("kuiper", [600, 650])
    first = simulate(a, b, config(random_seed=1))
    second = simulate(a, b, config(victim_handover_policy="max_snr", random_seed=90))
    pd.testing.assert_frame_equal(first.aggressor_trace, second.aggressor_trace)
    np.testing.assert_equal(first.power_truth.interference_w.to_numpy(), second.power_truth.interference_w.to_numpy())


def test_reproducible_random_actions():
    a, b = cube("starlink", [600, 700, 800]), cube("kuiper", [600])
    pd.testing.assert_frame_equal(simulate(a, b, config()).actions, simulate(a, b, config()).actions)


def test_score_intervals_and_censored_tail():
    result = simulate(cube("starlink", [600, 700]), cube("kuiper", [600]), config())
    seg = result.link_segments
    assert seg.iloc[0].dwell_seconds == 2
    assert seg.iloc[0].outage_seconds == 2
    assert seg.iloc[0].score_label_valid
    assert seg.iloc[-1].right_censored and not seg.iloc[-1].score_label_valid
    assert pd.isna(seg.iloc[-1].quality_success)
    assert seg.dwell_seconds.sum() == 7  # Eight timestamps delimit seven observed intervals.
    row = seg.iloc[0]
    expected = (row.dwell_seconds + row.spectral_efficiency_integral_seconds - 2*row.outage_seconds)/60
    assert row.score == pytest.approx(expected)


def test_import_masks_globally_empty_times_and_aliases(tmp_path):
    c = cube("starlink", [600, 700])
    c.valid[3, :] = False
    p = write_cube(tmp_path, c)
    loaded = load_orbits([p], "starlink", config())
    assert len(loaded.times) == 8 and not loaded.valid[3].any()
    assert np.isnan(loaded.positions[3]).all()
    assert constellation_name("Amazon") == "kuiper"


def test_reject_visible_csv_by_default(tmp_path):
    p = write_cube(tmp_path, cube("starlink", [600]), "visible")
    with pytest.raises(ValueError, match="visible-only"):
        load_orbits([p], "starlink", config())
    loaded = load_orbits([p], "starlink", config(allow_partial_catalog=True))
    assert loaded.sources[0]["coverage"] == "visible"


def test_reject_bad_units_and_duplicate_rows(tmp_path):
    p = write_cube(tmp_path, cube("starlink", [600]))
    df = pd.read_csv(p)
    pd.concat([df, df.iloc[:1]]).to_csv(p, index=False)
    with pytest.raises(ValueError, match="Duplicate"):
        load_orbits([p], "starlink", config())
    df[POSITION_COLUMNS] /= 1000
    df.to_csv(p, index=False)
    with pytest.raises(ValueError, match="metres"):
        load_orbits([p], "starlink", config())


def test_reject_mismatched_time_grids(tmp_path):
    pa, pb = fixture_pair(tmp_path)
    meta_path = pb.parent / "metadata.json"
    meta = json.loads(meta_path.read_text())
    meta["scenario"]["duration_sec"] = 9
    meta_path.write_text(json.dumps(meta))
    with pytest.raises(ValueError, match="matching UTC"):
        load_pair([pa], [pb], config())


def test_dataset_training_view_has_no_private_or_future_input(tmp_path):
    pa, pb = fixture_pair(tmp_path)
    run = run_dataset([pa], [pb], config(), tmp_path / "out")
    view = TrainingView(run)
    before = view.sample(0)
    view.close()
    assert before["inputs"]["history"].shape[0] == 2
    assert before["inputs"]["history"].shape[1] == 6
    assert "a_velocity_mps" not in before["inputs"]
    assert before["inputs"]["a_position_m"].shape[0] == 2
    assert before["labels"]["values"].shape == (1, 3)
    assert "b_satellite_id" not in before["inputs"]
    p = run / "public" / "observations.csv"
    obs = pd.read_csv(p)
    obs.loc[2:, "sinr_db"] = 99
    obs.to_csv(p, index=False)
    (run / "private" / "aggressor_trace.csv").write_text("invalid private data that must never be read")
    (run / "labels" / "link_segments.csv").write_text("future rewards must never be read")
    view = TrainingView(run)
    after = view.sample(0)
    view.close()
    np.testing.assert_equal(before["inputs"]["history"], after["inputs"]["history"])
    np.testing.assert_equal(before["inputs"]["a_position_m"], after["inputs"]["a_position_m"])
    assert before["inputs"]["action"] == after["inputs"]["action"]
    assert after["labels"]["values"][0, 0] == 99


def test_group_prevents_seed_variants_across_splits(tmp_path):
    pa, pb = fixture_pair(tmp_path)
    first = run_dataset([pa], [pb], config(), tmp_path / "out")
    second = run_dataset([pa], [pb], config(random_seed=2), tmp_path / "out")
    a = json.loads((first / "manifest.json").read_text())
    b = json.loads((second / "manifest.json").read_text())
    assert a["scenario_group_id"] == b["scenario_group_id"]
    with pytest.raises(ValueError, match="different split"):
        run_dataset([pa], [pb], config(split="test"), tmp_path / "out")


def test_notebook_structure_and_syntax():
    import nbformat
    p = Path(__file__).resolve().parents[1] / "main.ipynb"
    nb = nbformat.read(p, as_version=4)
    nbformat.validate(nb)
    for cell in nb.cells:
        if cell.cell_type == "code":
            compile(cell.source, str(p), "exec")
