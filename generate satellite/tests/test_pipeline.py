"""Offline numerical and data-integrity tests; never run a full constellation study."""
import json
from pathlib import Path
import shutil
import sys
from datetime import timedelta

import numpy as np
import pandas as pd
import pytest
import requests
from sgp4.exporter import export_omm, export_tle
from skyfield.api import wgs84

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import satellite_pipeline as sp
import synthetic_orbits as so


@pytest.fixture
def workspace(tmp_path):
    shutil.copy(sp.ROOT / "scenario.json", tmp_path / "scenario.json")
    shutil.copytree(sp.ROOT / "orbit_info", tmp_path / "orbit_info", ignore=shutil.ignore_patterns("generated", "official_documents"))
    cfg = json.loads((tmp_path / "scenario.json").read_text())
    cfg.update(start_time_utc="2026-10-05T12:00:00Z", duration_sec=120, interval_sec=60,
               elev_min_deg=-90, max_slant_km=30000, write_all_states=True, snapshot_manifest=None)
    sp.write_json(tmp_path / "scenario.json", cfg)
    return tmp_path


def sample_row(altitude=630, name="KUIPER-TEST", inc=51.9):
    return dict(epoch_utc="2026-10-05T12:00:00Z", altitude_km=altitude, inclination_deg=inc,
                eccentricity=0, arg_perigee_deg=0, raan_deg=35, mean_anomaly_deg=60,
                mean_motion_rev_per_day=float(np.sqrt(398600.8 / (6378.135 + altitude)**3) * 86400 / (2 * np.pi)),
                name=name)


def real_record(altitude=630, name="KUIPER-TEST", identity="real:123456", constellation="kuiper", inc=51.9):
    sat = so._satellite_from_elements(sample_row(altitude, name, inc))
    sat.model.intldesg = "26001A"
    sat.model.classification = "U"
    return sp.Satellite(sat, constellation, identity, identity.removeprefix("real:"))


def test_velocity_is_derivative_in_rotating_frames(workspace):
    cfg, _ = sp.read_scenario(workspace)
    rec = real_record()
    center = sp.utc(cfg["start_time_utc"])
    dt = .2
    times = [center + timedelta(seconds=x) for x in (-dt, 0, dt)]
    frame, valid = sp.state_frame(rec, times, cfg)
    assert valid.all()
    for positions, velocities in [
        ([f"{a}_ECEF (m)" for a in "xyz"], [f"v{a}_ECEF (m/s)" for a in "xyz"]),
        (["x_East (m)", "y_North (m)", "z_Up (m)"], ["vx_East (m/s)", "vy_North (m/s)", "vz_Up (m/s)"]),
    ]:
        numerical = (frame.loc[2, positions].to_numpy(float) - frame.loc[0, positions].to_numpy(float)) / (2 * dt)
        np.testing.assert_allclose(numerical, frame.loc[1, velocities].to_numpy(float), atol=.15, rtol=0)
    numerical_rate = (frame.loc[2, "Slant km"] - frame.loc[0, "Slant km"]) * 1000 / (2 * dt)
    assert abs(numerical_rate - frame.loc[1, "Range Rate (m/s)"]) < .15


def test_geometry_matches_skyfield_topocentric(workspace):
    cfg, times = sp.read_scenario(workspace)
    rec = real_record()
    frame, _ = sp.state_frame(rec, times, cfg)
    ground = wgs84.latlon(cfg["lat_deg"], cfg["lon_deg"], cfg["elev_m"])
    elev, az, distance = (rec.sat - ground).at(sp.TS.from_datetimes(times)).altaz()
    np.testing.assert_allclose(frame["Elevation (°)"], elev.degrees, atol=1e-8)
    np.testing.assert_allclose(frame["Azimuth (°)"], az.degrees, atol=1e-8)
    np.testing.assert_allclose(frame["Slant km"], distance.km, atol=1e-8)


def test_filters_dtc_low_altitude_and_zero_counts(workspace):
    records = [real_record(), real_record(400, "KUIPER-LOW", "real:2"),
               real_record(630, "KUIPER-DTC [DTC]", "real:3")]
    result = sp.export_tracks(records, "kuiper", root=workspace)
    frame = pd.read_csv(result["visible_csv"])
    assert list(frame.columns) == sp.COLUMNS
    assert set(frame["Name"]) == {"KUIPER-TEST"}
    assert len(frame) == 2
    audit = pd.read_csv(result["audit_csv"]).set_index("Satellite ID")
    assert audit.loc["real:2", "low_altitude_samples"] == 2
    assert audit.loc["real:3", "excluded_reason"] == "dtc_name_marker"
    cfg = json.loads((workspace / "scenario.json").read_text())
    cfg["elev_min_deg"] = 90
    sp.write_json(workspace / "scenario.json", cfg)
    result = sp.export_tracks(records, "kuiper", root=workspace)
    assert pd.read_csv(result["visible_csv"]).empty
    counts = pd.read_csv(result["counts_csv"])
    assert len(counts) == 2 and counts["Visible Count"].sum() == 0


def test_stale_elements_are_audited(workspace):
    cfg = json.loads((workspace / "scenario.json").read_text())
    cfg["start_time_utc"] = "2026-12-05T12:00:00Z"
    sp.write_json(workspace / "scenario.json", cfg)
    with pytest.warns(UserWarning, match="No satellite states"):
        result = sp.export_tracks([real_record()], "kuiper", root=workspace)
    assert pd.read_csv(result["audit_csv"]).loc[0, "stale_samples"] == 2
    assert pd.read_csv(result["visible_csv"]).empty


def test_empty_synthetic_export_preserves_headers_and_times(workspace):
    result = sp.export_tracks([], "oneweb", source_type="approved_shell_synthetic", root=workspace)
    assert list(pd.read_csv(result["visible_csv"]).columns) == sp.COLUMNS
    assert pd.read_csv(result["counts_csv"])["Visible Count"].tolist() == [0, 0]
    assert json.loads(result["metadata"].read_text())["status"] == "complete"


def test_six_digit_omm_and_strict_tle():
    model = real_record().sat.model
    omm = export_omm(model, "KUIPER-TEST")
    omm["NORAD_CAT_ID"] = 123456
    omm["OBJECT_ID"] = "2026-001A"
    sats = sp.parse_omm([omm, omm])
    assert len(sats) == 1 and sats[0].model.satnum == 123456
    l1, l2 = export_tle(model)
    assert len(sp.parse_tle(f"TEST\n{l1}\n{l2}\n")) == 1
    assert len(sp.parse_tle(f"{l1}\n{l2}\n")) == 1
    with pytest.raises(ValueError):
        sp.parse_tle("<html>403 Forbidden</html>")
    with pytest.raises(ValueError, match="checksum"):
        sp.parse_tle(f"TEST\n{l1[:-1]}{(int(l1[-1])+1)%10}\n{l2}\n")
    with pytest.raises(ValueError):
        sp.parse_omm([])


def test_approved_counts_and_raising_satellite_accounting(workspace):
    kuiper = so.approved_shells("kuiper", workspace)
    oneweb = so.approved_shells("oneweb", workspace)
    assert sum(s["satellite_count"] for s in kuiper) == 3232
    assert sum(s["satellite_count"] for s in oneweb) == 716
    records = [real_record(400), real_record(630, identity="real:2")]
    summary, assigned = so.estimate_deficits(kuiper, records, "2026-10-05T12:00:00Z")
    row = summary.set_index("shell_id").loc["kuiper_gen1_630_51p9"]
    assert row["catalog_assigned"] == 2 and row["synthetic_deficit"] == 1154
    assert assigned.shell_id.nunique() == 1
    with pytest.raises(ValueError, match="stale"):
        so.estimate_deficits(kuiper, records, "2027-01-01T00:00:00Z")


def test_polar_spares_do_not_reduce_inclined_deficit(workspace):
    shells = so.approved_shells("oneweb", workspace)
    records = [real_record(1200, f"ONEWEB-{i}", f"real:{i}", "oneweb", 87.9) for i in range(600)]
    summary, _ = so.estimate_deficits(shells, records, "2026-10-05T12:00:00Z")
    stats = summary.set_index("shell_id")
    assert stats.loc["oneweb_phase1_1200_87p9", "synthetic_deficit"] == 0
    assert stats.loc["oneweb_phase1_1200_87p9", "catalog_above_target"] == 12
    assert stats.loc["oneweb_phase1_1200_55", "synthetic_deficit"] == 128


def test_custom_reproducible_elements_and_replay(workspace):
    shells = [dict(constellation="kuiper", shell_id="test", altitude_km=630,
                   inclination_deg=51.9, planes=2, satellites_per_plane=3, satellite_count=6)]
    a, ma = so.build_virtual("kuiper", "custom", "2026-10-05T12:00:00Z", root=workspace, shells_override=shells)
    b, mb = so.build_virtual("kuiper", "custom", "2026-10-05T12:00:00Z", root=workspace, shells_override=shells)
    pa = workspace / ma["orbit_directory"] / "synthetic_mean_elements.csv"
    pb = workspace / mb["orbit_directory"] / "synthetic_mean_elements.csv"
    assert pa.read_bytes() == pb.read_bytes()
    assert len(a) == 6 and len({r.satellite_id for r in a}) == 6
    assert all(r.synthetic and r.norad_id == "" for r in a)
    cfg, times = sp.read_scenario(workspace)
    fa, va = sp.state_frame(a[0], times, cfg)
    fb, vb = sp.state_frame(so.load_virtual_elements(pa)[0], times, cfg)
    pd.testing.assert_frame_equal(fa, fb)
    assert va.all() and vb.all()
    assert fa["Orbit Altitude (km)"].between(615, 660).all()


def test_invalid_shells_and_scenario(workspace):
    shells = so.custom_shells("kuiper", workspace)
    shells[0]["satellite_count"] += 1
    with pytest.raises(ValueError, match="Satellite count"):
        so.validate_shells(shells, "kuiper")
    with pytest.raises(ValueError, match="timezone"):
        sp.utc("2026-10-05")
    cfg = json.loads((workspace / "scenario.json").read_text())
    cfg["interval_sec"] = 0
    sp.write_json(workspace / "scenario.json", cfg)
    with pytest.raises(ValueError, match="positive integers"):
        sp.read_scenario(workspace)
    assert sp.azimuth_mask(np.array([355, 0, 20, 180]), [350, 10]).tolist() == [True, True, False, False]


def test_merge_and_duplicate_mismatch_rejection(workspace):
    a = sp.export_tracks([real_record()], "kuiper", root=workspace)
    b = sp.export_tracks([real_record(1200, "ONEWEB-X", "real:2", "oneweb", 87.9)], "oneweb", root=workspace)
    output = sp.merge_exports([a["visible_csv"], b["visible_csv"]], workspace / "merged.csv")
    assert len(pd.read_csv(output)) == 4
    with pytest.raises(ValueError, match="Duplicate"):
        sp.merge_exports([a["visible_csv"], a["visible_csv"]], workspace / "duplicate.csv")
    info = json.loads(b["metadata"].read_text())
    info["scenario"]["lat_deg"] = 5
    sp.write_json(b["metadata"], info)
    with pytest.raises(ValueError, match="mismatch"):
        sp.merge_exports([a["visible_csv"], b["visible_csv"]], workspace / "bad.csv")


class FakeResponse:
    def __init__(self, data, failure=False):
        self.content = data.encode()
        self.text = data
        self.failure = failure

    def raise_for_status(self):
        if self.failure:
            raise requests.HTTPError("403")

    def json(self):
        return json.loads(self.text)


class FakeSession:
    def __init__(self, fail_json=False):
        self.calls = []
        self.fail_json = fail_json

    def get(self, url, **kwargs):
        self.calls.append(url)
        model = real_record().sat.model
        if "FORMAT=JSON" in url:
            omm = export_omm(model, "KUIPER-TEST")
            omm["OBJECT_ID"] = "2026-001A"
            return FakeResponse(json.dumps([omm]), self.fail_json)
        l1, l2 = export_tle(model)
        return FakeResponse(f"TEST\n{l1}\n{l2}\n")


def test_downloader_archives_cache_and_integrity(workspace):
    session = FakeSession()
    p = sp.download_snapshot(workspace, session=session)
    assert len(session.calls) == 6
    again = sp.download_snapshot(workspace, session=session)
    assert p == again and len(session.calls) == 6
    records = sp.load_snapshot("kuiper", p, workspace)
    assert len(records) == 1
    record_path = workspace / records[0].source_file
    record_path.write_text("[]")
    with pytest.raises(ValueError, match="checksum"):
        sp.load_snapshot("kuiper", p, workspace)


def test_downloader_does_not_accept_failed_json(workspace):
    with pytest.warns(UserWarning):
        with pytest.raises(RuntimeError, match="Incomplete"):
            sp.download_snapshot(workspace, session=FakeSession(fail_json=True))
    with pytest.raises(FileNotFoundError):
        sp.download_snapshot(workspace, mode="local")


def test_tle_failure_uses_labeled_conversion_and_preserves_six_digit_omm(workspace):
    class PartialSession(FakeSession):
        def get(self, url, **kwargs):
            if "FORMAT=TLE" in url:
                return FakeResponse("Forbidden", failure=True)
            response = super().get(url, **kwargs)
            items = response.json()
            extra = dict(items[0], NORAD_CAT_ID=123456)
            return FakeResponse(json.dumps(items + [extra]))

    with pytest.warns(UserWarning, match="403"):
        p = sp.download_snapshot(workspace, session=PartialSession())
    data = json.loads(p.read_text())
    assert data["complete"]
    for c in sp.CONSTELLATIONS:
        entry = data["constellations"][c]
        assert entry["tle"]["status"] == "failed"
        assert entry["json"]["count"] == 2
        derived = entry["derived_tle"]
        assert derived["count"] == 1 and derived["skipped_six_digit_ids"] == [123456]
        assert len(sp.parse_tle((workspace / derived["path"]).read_text())) == 1
        assert len(sp.load_snapshot(c, p, workspace)) == 2


def test_notebooks_have_valid_structure_and_python():
    import nbformat
    for path in sp.ROOT.glob("*.ipynb"):
        nb = nbformat.read(path, as_version=4)
        nbformat.validate(nb)
        for c in nb.cells:
            if c.cell_type == "code":
                compile(c.source, str(path), "exec")
