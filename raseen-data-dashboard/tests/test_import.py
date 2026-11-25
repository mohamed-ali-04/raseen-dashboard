"""Checks for the Gazebo importer, using Mo's first recorded run (run_0001, 25 Nov 2026)."""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from raseen_data.gazebo_import import PLUGIN_REQUIRED, find_end, import_run, read_plugin_csv

REAL = Path(__file__).parent.parent / "examples" / "run_0001.csv.gz"


def test_real_run(tmp_path):
    m = import_run(REAL, "gz_0001", tmp_path)
    assert m["outcome"] == "grounded"
    assert m["end"]["exit_reason"] == "ukc_exhausted_keel_below_bed"
    assert m["end"]["end_t"] == pytest.approx(579.55)
    assert m["plugin"]["parameter_set_id"] == "KVLCC2_FORM_PROXY_QUALITATIVE"
    table = pd.read_csv(tmp_path / "runs" / "gz_0001" / "data.csv.gz")
    assert (table["valid"] == 1).all() and (table["validity_state"] == "in_domain").all()
    assert (table["ukc_min"] > 0).all()
    assert np.allclose(np.diff(table["t"].to_numpy()[:-1]), 1.0)
    assert table["t"].iloc[-1] < 579.55
    rud = [(c["from"], c["to"]) for c in m["commands"]["rudder_deg"]]
    assert rud == [(0, 10), (10, 0), (0, 10), (10, 0)]
    assert [(c["from"], c["to"]) for c in m["commands"]["rpm"]] == [(0, 60)]
    lab = pd.read_csv(tmp_path / "labelled" / "gz_0001.csv.gz")
    assert ((lab["risk"] == "critical") == (lab["t"] >= 579.55 - 60)).all()
    assert ((lab["risk"] != "normal") == (lab["t"] >= 579.55 - 180)).all()
    index = pd.read_csv(tmp_path / "index.csv")
    assert list(index["run_id"]) == ["gz_0001"]


def _fake(n=50, exit_at=None):
    df = pd.DataFrame({c: 0.0 for c in PLUGIN_REQUIRED}, index=range(n))
    df["t"] = np.arange(n) * 0.1 + 0.01
    df["ukc_min"] = 5.0
    df["valid"] = 1
    for c in ("ukc_status", "shallow_status", "bank_status"):
        df[c] = "ok"
    df["validity_state"] = "in_domain"
    df["exit_reason"] = ""
    if exit_at is not None:
        df.loc[exit_at:, ["valid", "validity_state", "exit_reason", "ukc_min"]] = [0, "domain_exit", "ukc_exhausted", -0.01]
    return df


def test_safe_run(tmp_path):
    p = tmp_path / "safe.csv"
    _fake().to_csv(p, index=False)
    m = import_run(p, "s1", tmp_path / "out")
    assert m["outcome"] == "safe" and m["end"]["rows_dropped"] == 0
    lab = pd.read_csv(tmp_path / "out" / "labelled" / "s1.csv.gz")
    assert (lab["risk"] == "normal").all()


def test_exit_detected(tmp_path):
    p = tmp_path / "g.csv"
    _fake(exit_at=30).to_csv(p, index=False)
    end = find_end(read_plugin_csv(p))
    assert end["outcome"] == "grounded" and end["end_index"] == 29 and end["rows_dropped"] == 20


def test_rejects_other_csv(tmp_path):
    p = tmp_path / "bad.csv"
    pd.DataFrame({"t": [0, 1], "x": [0, 1]}).to_csv(p, index=False)
    with pytest.raises(ValueError, match="missing columns"):
        read_plugin_csv(p)


def test_rejects_exit_at_start(tmp_path):
    p = tmp_path / "e.csv"
    _fake(exit_at=0).to_csv(p, index=False)
    with pytest.raises(ValueError, match="first row"):
        find_end(read_plugin_csv(p))


def test_minimal_csv_without_validity_columns(tmp_path):
    """An older or stripped CSV: only the required columns. The end falls back to ukc_min <= 0."""
    df = _fake(exit_at=30)[["t", "x", "y", "yaw_deg", "u", "ukc_min"]]
    p = tmp_path / "old.csv"
    df.to_csv(p, index=False)
    m = import_run(p, "old", tmp_path / "out")
    assert m["outcome"] == "grounded" and m["end"]["exit_reason"] == "ukc_min_reached_zero"
    assert m["end"]["end_t"] == pytest.approx(3.01)
    assert m["commands"] == {"rudder_deg": [], "rpm": []}
    assert m["optional_columns_present"] == []
    table = pd.read_csv(tmp_path / "out" / "runs" / "old" / "data.csv.gz")
    assert table["bank_force_y"].isna().all() and (table["ukc_min"] > 0).all()


def test_real_run_without_bank_columns(tmp_path):
    """Drop optional columns from the real run: the result must not change where it ends."""
    df = pd.read_csv(REAL).drop(columns=["YbankA", "Nbank", "d2b_inv", "ukc_status", "shallow_status"])
    p = tmp_path / "trimmed.csv"
    df.to_csv(p, index=False)
    m = import_run(p, "trim", tmp_path / "out")
    assert m["outcome"] == "grounded" and m["end"]["end_t"] == pytest.approx(579.55) and m["n_rows"] == 580


def test_page_with_missing_columns_has_no_nan(tmp_path):
    """Missing optional columns must reach the page as null, not NaN (NaN breaks JSON)."""
    import json, re
    from raseen_data.dashboard import make_dashboard
    df = pd.read_csv(REAL)[["t", "x", "y", "yaw_deg", "u", "ukc_min"]]
    p = tmp_path / "min.csv"
    df.to_csv(p, index=False)
    import_run(p, "min", tmp_path / "out")
    html_path = tmp_path / "page.html"
    make_dashboard(tmp_path / "out", html_path)
    data = re.search(r"const DATA = (.*?);\n", html_path.read_text()).group(1)
    run = json.loads(data)["runs"][0]
    assert run["bank_force_y"][0] is None and run["meta"]["run_id"] == "min"
