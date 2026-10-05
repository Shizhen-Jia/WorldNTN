"""Execute main.ipynb on an eight-second artificial geometry in a temporary copy."""
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile

import nbformat
from nbclient import NotebookClient

ROOT = Path(__file__).resolve().parents[1]


def main():
    work = Path(tempfile.mkdtemp(prefix="worldntn-data-smoke-"))
    for p in ROOT.glob("*.py"):
        shutil.copy(p, work / p.name)
    spec = importlib.util.spec_from_file_location("generator_test_fixtures", ROOT / "tests" / "test_generator.py")
    fixtures = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixtures)
    pa, pb = fixtures.fixture_pair(work / "fixture_csvs")
    nb = nbformat.read(ROOT / "main.ipynb", as_version=4)
    for cell in nb.cells:
        if cell.cell_type == "code":
            cell.source = cell.source.replace("VICTIM_CSVS = None", f"VICTIM_CSVS = [{str(pa)!r}]")
            cell.source = cell.source.replace("AGGRESSOR_CSVS = None", f"AGGRESSOR_CSVS = [{str(pb)!r}]")
            cell.source = cell.source.replace("lat_deg=39.95697, lon_deg=-105.16033, height_m=1660.0",
                                              "lat_deg=0, lon_deg=0, height_m=0")
            cell.source = cell.source.replace("history_samples=10", "history_samples=2")
    NotebookClient(nb, timeout=180, kernel_name="python3", resources={"metadata": {"path": str(work)}}).execute()
    nbformat.write(nb, work / "executed_main.ipynb")
    runs = list((work / "outputs").glob("*/manifest.json"))
    assert len(runs) == 1
    manifest = json.loads(runs[0].read_text())
    assert manifest["status"] == "complete" and manifest["sample_count"] == 8
    report = json.loads((runs[0].parent / "quality_report.json").read_text())
    assert report["training_windows"] > 0 and report["executed_handovers_or_acquisitions"] > 0
    print(json.dumps({"status": "passed", "scope": "eight artificial samples; all main notebook cells", "workspace": str(work), "report": report}, indent=2))


if __name__ == "__main__":
    main()
