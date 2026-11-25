"""The replay page reads plugin CSVs itself, in JavaScript. This checks that it
ends, resamples and labels a run exactly like gazebo_import.py.

Needs Playwright and a Chrome/Chromium; skipped when they are not installed,
unless RASEEN_REQUIRE_BROWSER=1 (as on GitHub), where a missing browser is a failure.
"""
import asyncio
import os
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from raseen_data.dashboard import render
from raseen_data.gazebo_import import import_run

REQUIRE = os.environ.get("RASEEN_REQUIRE_BROWSER") == "1"
if REQUIRE:
    import playwright.async_api as playwright
else:
    playwright = pytest.importorskip("playwright.async_api")
CHROME = next((c for c in ("google-chrome", "chromium", "chromium-browser") if shutil.which(c)), None)
REAL = Path(__file__).parent.parent / "examples" / "run_0001.csv.gz"


async def _browser_runs(page_path, files, extra=()):
    async with playwright.async_playwright() as p:
        kw = {"executable_path": shutil.which(CHROME)} if CHROME else {}
        b = await p.chromium.launch(args=["--no-sandbox"], **kw)
        pg = await b.new_page()
        errors = []
        pg.on("pageerror", lambda e: errors.append(str(e)))
        await pg.goto(page_path.as_uri())
        await pg.set_input_files("#file", [str(f) for f in files] + [str(f) for f in extra])
        await pg.wait_for_function(f"RUNS.length >= {len(files)}", timeout=20000)
        runs = await pg.evaluate("RUNS.map(r => ({file: r.meta.file, t: r.t, risk: r.risk, y: r.y, "
                                 "ukc: r.ukc_min, meta: r.meta}))")
        runs = sorted(runs, key=lambda r: [str(f.name) for f in files].index(r["file"]))
        await b.close()
        assert not errors, errors
        return runs


def test_viewer_matches_python(tmp_path):
    full = pd.read_csv(REAL)
    files = [REAL, tmp_path / "minimal.csv", tmp_path / "safe.csv"]
    full[["t", "x", "y", "yaw_deg", "u", "ukc_min"]].to_csv(files[1], index=False)
    full.iloc[:3000].to_csv(files[2], index=False)
    page = tmp_path / "viewer.html"
    page.write_text(render([]))
    try:
        runs = asyncio.run(_browser_runs(page, files, [REAL.parent / "run_0001.csv.identity.json"]))
    except Exception as err:                      # no usable browser on this machine
        if REQUIRE:
            raise
        pytest.skip(f"browser not available: {err}")
    assert runs[0]["meta"]["plugin"]["parameter_set_id"] == "KVLCC2_FORM_PROXY_QUALITATIVE"   # identity file matched to the .gz
    for r, f in zip(runs, files):
        m = import_run(f, "cmp", tmp_path / "out")
        py = pd.read_csv(tmp_path / "out" / "labelled" / "cmp.csv.gz")
        assert len(py) == len(r["t"]), f
        assert np.allclose(py["t"], r["t"]) and list(py["risk"]) == r["risk"]
        assert np.allclose(py["y"], r["y"], atol=1e-3) and np.allclose(py["ukc_min"], r["ukc"], atol=1e-4)
        assert m["outcome"] == r["meta"]["outcome"] and m["commands"] == r["meta"]["commands"]
        assert m["end"]["end_t"] == pytest.approx(r["meta"]["end"]["end_t"])
