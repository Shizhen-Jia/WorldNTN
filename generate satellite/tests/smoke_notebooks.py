"""Execute all notebooks on two times and eight propagated satellites in /tmp.

The complete archived catalog is still used for approved-shell accounting.
Run after download_tle.ipynb has downloaded an actual snapshot. No network is used.
"""
from pathlib import Path
import json
import shutil
import tempfile

import nbformat
from nbclient import NotebookClient

ROOT = Path(__file__).resolve().parents[1]


def main():
    work = Path(tempfile.mkdtemp(prefix="worldntn-notebook-smoke-"))
    for filename in ("satellite_pipeline.py", "synthetic_orbits.py", "scenario.json"):
        shutil.copy(ROOT / filename, work / filename)
    shutil.copytree(ROOT / "tle", work / "tle")
    shutil.copytree(ROOT / "orbit_info", work / "orbit_info", ignore=shutil.ignore_patterns("generated"))
    cfg = json.loads((work / "scenario.json").read_text())
    cfg.update(duration_sec=240, interval_sec=120, elev_min_deg=-90, max_slant_km=30000,
               write_all_states=True)
    (work / "scenario.json").write_text(json.dumps(cfg))
    results = []
    for path in sorted(ROOT.glob("*.ipynb")):
        nb = nbformat.read(path, as_version=4)
        for cell in nb.cells:
            if cell.cell_type != "code":
                continue
            cell.source = cell.source.replace('MODE = "auto"', 'MODE = "local"')
            if "satellites = load_snapshot" in cell.source:
                cell.source += "\nsatellites = satellites[:4] + satellites[-4:]\n"
            if "virtual, orbit_meta = build_virtual" in cell.source:
                cell.source += "\nvirtual = virtual[:4] + virtual[-4:] if len(virtual) >= 8 else virtual\n"
        NotebookClient(nb, timeout=180, kernel_name="python3", resources={"metadata": {"path": str(work)}}).execute()
        nbformat.write(nb, work / path.name)
        results.append({"notebook": path.name, "status": "passed"})
        print("PASS", path.name, flush=True)
    report = {"scope": "two timestamps; at most eight propagated satellites per notebook; full catalog shell accounting",
              "workspace": str(work), "results": results}
    (work / "validation.json").write_text(json.dumps(report, indent=2))
    print("Artifacts:", work, flush=True)
    return report


if __name__ == "__main__":
    main()
