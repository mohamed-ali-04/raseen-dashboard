"""Turn CSVs written by the RASEEN hydrodynamics plugin into stored, labelled runs.

    python3 -m raseen_data.gazebo_import --csv /mnt/d/raseen_runs/*.csv --out data_gz

What it does, per CSV:
  1. checks the CSV has the plugin's columns (t, x, y, yaw_deg, u, ukc_min at least)
  2. finds where the run left the plugin's valid range (first row with valid != 1 or
     validity_state != in_domain). That row and everything after it are dropped, because
     the plugin switches its canal physics off there; its time is kept for the labels
  3. puts the plugin rows on a 1 s grid (last value at or before each second)
  4. reads the rudder and propeller command timeline from the data itself
  5. stores the run (table + meta.json, with the plugin's .identity.json) and a labelled copy
  6. rewrites the folder's index.csv
The dashboard page applies the same rules in the browser.

Sign conventions are taken from the data and not yet checked against the plugin
source: forces in N and moments in N m (Z equals the ship's weight), yaw_deg in
degrees. The plugin reports body-frame forces; their sign convention is recorded
as unverified in meta.json.
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import __version__
from .label import label_run

# Only these must be present. Everything else is optional, so CSVs from older
# plugin versions still import; a missing column is stored empty.
PLUGIN_REQUIRED = ["t", "x", "y", "yaw_deg", "u", "ukc_min"]
PLUGIN_OPTIONAL_NUM = ["v", "r", "beta_deg", "rudder_deg", "rpm", "thrust", "X", "Y", "N",
                       "YbankA", "Nbank", "d2b_inv", "ukc_fp", "valid"]
PLUGIN_OPTIONAL_TEXT = ["ukc_status", "shallow_status", "bank_status", "validity_state", "exit_reason"]

# column in the run table <- plugin column, with unit
GZ_COLUMNS = {
    "t": ("t", "s"),
    "x": ("x", "m"),
    "y": ("y", "m"),
    "heading_deg": ("yaw_deg", "deg"),
    "u": ("u", "m/s"),
    "v": ("v", "m/s"),
    "r": ("r", "rad/s"),
    "drift_deg": ("beta_deg", "deg"),
    "rudder_deg": ("rudder_deg", "deg"),
    "rpm": ("rpm", "1/min"),
    "thrust": ("thrust", "N"),
    "force_x": ("X", "N"),
    "force_y": ("Y", "N"),
    "moment_n": ("N", "N m"),
    "bank_force_y": ("YbankA", "N"),
    "bank_moment_n": ("Nbank", "N m"),
    "bank_proximity": ("d2b_inv", "1/m (plugin d2b_inv)"),
    "ukc_min": ("ukc_min", "m"),
    "ukc_fp": ("ukc_fp", "m"),
    "ukc_status": ("ukc_status", "text"),
    "shallow_status": ("shallow_status", "text"),
    "bank_status": ("bank_status", "text"),
    "valid": ("valid", "0/1"),
    "validity_state": ("validity_state", "text"),
}
TEXT_COLUMNS = {"ukc_status", "shallow_status", "bank_status", "validity_state"}


def read_plugin_csv(path) -> pd.DataFrame:
    """Read a plugin CSV. df.attrs["has"] records which optional columns were really there."""
    df = pd.read_csv(path, low_memory=False)
    missing = [c for c in PLUGIN_REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"{path}: not a RASEEN plugin CSV, missing columns {missing}")
    for c in PLUGIN_REQUIRED:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=PLUGIN_REQUIRED)
    if len(df) < 2:
        raise ValueError(f"{path}: fewer than 2 complete rows")
    has = set(df.columns)
    for c in PLUGIN_OPTIONAL_NUM:
        df[c] = pd.to_numeric(df[c], errors="coerce") if c in has else np.nan
    for c in PLUGIN_OPTIONAL_TEXT:
        df[c] = df[c].fillna("").astype(str) if c in has else ""
    df = df.sort_values("t", kind="stable").reset_index(drop=True)
    df.attrs["has"] = sorted(has & set(PLUGIN_OPTIONAL_NUM + PLUGIN_OPTIONAL_TEXT))
    return df


def find_end(df: pd.DataFrame) -> dict:
    """Where the usable part of the run ends, and why.

    The end is the first row the plugin marks invalid: valid != 1, or a
    validity_state other than in_domain. A CSV with neither column falls back to
    the first row with no clearance under the keel (ukc_min <= 0).
    """
    has = set(df.attrs.get("has", df.columns))
    mask = pd.Series(False, index=df.index)
    if "valid" in has:
        mask |= df["valid"].fillna(0) != 1
    if "validity_state" in has:
        mask |= df["validity_state"] != "in_domain"
    if "valid" not in has and "validity_state" not in has:
        mask |= df["ukc_min"] <= 0
    bad = df.index[mask]
    if len(bad) == 0:
        return {"outcome": "safe", "end_index": len(df) - 1, "end_t": float(df["t"].iloc[-1]),
                "exit_reason": "", "rows_dropped": 0}
    i = int(bad[0])
    if i == 0:
        raise ValueError("the run is outside the plugin's valid range from its first row")
    reason = df.at[i, "exit_reason"] or ("ukc_min_reached_zero" if df.at[i, "ukc_min"] <= 0 else "marked_invalid")
    grounded = "ukc" in reason or float(df.at[i, "ukc_min"]) <= 0
    return {"outcome": "grounded" if grounded else "domain_exit", "end_index": i - 1,
            "end_t": float(df.at[i, "t"]), "exit_reason": reason, "rows_dropped": int(len(df) - i)}


def command_timeline(df: pd.DataFrame, col: str, min_hold_s: float = 0.5) -> list[dict]:
    """Rudder or RPM commands, read back from the data.

    The plugin ramps the rudder at a fixed rate, so a command shows as a ramp
    between two steady values. A steady value is one held for at least min_hold_s.
    Each command is reported as: when the ramp started, from which value, to which.
    """
    t, val = df["t"].to_numpy(), df[col].to_numpy(dtype=float)
    if np.isnan(val).all():
        return []
    val = pd.Series(val).ffill().bfill().to_numpy()
    plateaus = []                     # (t_start, t_end, value)
    start = 0
    for i in range(1, len(val) + 1):
        if i == len(val) or abs(val[i] - val[start]) > 1e-9:
            if t[i - 1] - t[start] >= min_hold_s or start == 0 or i == len(val):
                plateaus.append((float(t[start]), float(t[i - 1]), float(val[start])))
            start = i
    out = []
    for (s0, e0, v0), (s1, _, v1) in zip(plateaus, plateaus[1:]):
        if abs(v1 - v0) > 1e-6:
            out.append({"t_command": round(e0, 2), "t_reached": round(s1, 2),
                        "from": round(v0, 3), "to": round(v1, 3)})
    return out


def to_run_table(df: pd.DataFrame, end_index: int, step_s: float = 1.0) -> pd.DataFrame:
    """Usable rows only, on a fixed grid of step_s seconds, plugin names mapped to run-table names."""
    use = df.iloc[: end_index + 1]
    t0, t_end = float(use["t"].iloc[0]), float(use["t"].iloc[-1])
    grid = np.arange(np.ceil(t0), np.floor(t_end) + 1e-9, step_s)
    if grid.size == 0 or grid[-1] < t_end - 1e-9:
        grid = np.append(grid, t_end)          # keep the exact end row
    src = use[[p for p, _ in GZ_COLUMNS.values()]].copy()
    out = pd.merge_asof(pd.DataFrame({"t_grid": grid}), src, left_on="t_grid", right_on="t",
                        direction="backward")
    out = out.drop(columns=["t"]).rename(columns={"t_grid": "t"})
    out = out.rename(columns={p: name for name, (p, _) in GZ_COLUMNS.items() if p != "t"})
    out = out[list(GZ_COLUMNS)]
    required = [name for name, (p, _) in GZ_COLUMNS.items() if p in PLUGIN_REQUIRED]
    if out[required].isna().any().any():
        raise ValueError("gaps after resampling in the required columns")
    return out


def write_index(out_dir: Path) -> pd.DataFrame:
    rows = []
    for meta_path in sorted((out_dir / "runs").glob("*/meta.json")):
        m = json.loads(meta_path.read_text())
        rows.append({"run_id": m["run_id"], "source": m["source"], "outcome": m["outcome"],
                     "ended_at_s": m["duration_s"], "n_rows": m["n_rows"],
                     "parameter_set": m.get("plugin", {}).get("parameter_set_id", ""),
                     "note": m.get("note", "")})
    index = pd.DataFrame(rows)
    index.to_csv(out_dir / "index.csv", index=False)
    return index


def import_run(csv_path, run_id: str, out_dir, note: str = "", critical_s: float = 60.0,
               caution_s: float = 180.0) -> dict:
    csv_path, out_dir = Path(csv_path), Path(out_dir)
    df = read_plugin_csv(csv_path)
    end = find_end(df)
    table = to_run_table(df, end["end_index"])

    run_dir = out_dir / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    table.to_csv(run_dir / "data.csv.gz", index=False, float_format="%.6g", compression="gzip")

    identity = {}
    id_path = identity_path(csv_path)
    if id_path:
        identity = json.loads(id_path.read_text())

    exit_i = end["end_index"] + (0 if end["outcome"] == "safe" else 1)
    end_row = df.iloc[exit_i]
    meta = {
        "run_id": run_id,
        "source": "gazebo",
        "schema": "gazebo_plugin_v1",
        "code_version": __version__,
        "data_file": "data.csv.gz",
        "n_rows": int(len(table)),
        "duration_s": float(table["t"].iloc[-1]),
        "outcome": end["outcome"],
        "end": {**end, "x": float(end_row["x"]), "y": float(end_row["y"]),
                "heading_deg": float(end_row["yaw_deg"]), "u": float(end_row["u"])},
        "source_csv": str(csv_path),
        "source_rows": int(len(df)),
        "source_period_s": float(np.median(np.diff(df["t"].to_numpy()))),
        "commands": {"rudder_deg": command_timeline(df, "rudder_deg"),
                     "rpm": command_timeline(df, "rpm")},
        "plugin": identity,
        "columns": {name: {"from": p, "unit": unit} for name, (p, unit) in GZ_COLUMNS.items()},
        "optional_columns_present": df.attrs.get("has", []),
        "conventions_checked": False,
        "note": note,
    }
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2))

    outcome_for_labels = "grounded" if end["outcome"] in ("grounded", "domain_exit") else "safe"
    labelled = label_run(table, outcome_for_labels, critical_s, caution_s, end_t=end["end_t"])
    labelled.insert(0, "run_id", run_id)
    (out_dir / "labelled").mkdir(parents=True, exist_ok=True)
    labelled.to_csv(out_dir / "labelled" / f"{run_id}.csv.gz", index=False, float_format="%.6g",
                    compression="gzip")
    write_index(out_dir)
    return meta


def identity_path(csv_path):
    """The plugin writes <name>.csv.identity.json next to <name>.csv; also accept it beside <name>.csv.gz."""
    p = Path(str(csv_path) + ".identity.json")
    if not p.exists() and str(csv_path).endswith(".gz"):
        p = Path(str(csv_path)[:-3] + ".identity.json")
    return p if p.exists() else None


def write_summary_md(metas: list, failed: list, path) -> None:
    """A Markdown table of the imported runs (used by the GitHub check)."""
    lines = ["| Run | Plugin rows | Seconds kept | Outcome | Ended at | Commands | Parameter set | Plugin build |",
             "|---|---|---|---|---|---|---|---|"]
    for m in metas:
        e, cmds = m["end"], sum(len(v) for v in m["commands"].values())
        lines.append(f"| {m['run_id']} | {m['source_rows']} | {m['n_rows']} | {m['outcome']} | {e['end_t']:.1f} s"
                     f"{' (' + e['exit_reason'] + ')' if e['exit_reason'] else ''} | {cmds} | "
                     f"{m['plugin'].get('parameter_set_id', 'no identity file')} | "
                     f"{Path(m['plugin'].get('plugin_lib', '')).name or '-'} |")
    for path_, err in failed:
        lines.append(f"| {Path(path_).name} | could not be read: {err} | | | | | | |")
    Path(path).write_text("\n".join(lines) + "\n")


def run_id_from(path) -> str:
    name = Path(path).name
    for ext in (".csv.gz", ".csv"):
        if name.endswith(ext):
            name = name[: -len(ext)]
    return name


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", required=True, nargs="+",
                    help="one or more CSVs written by the plugin (RASEEN_CSV_PATH); .csv or .csv.gz")
    ap.add_argument("--run-id", default="", help="name for the run; default: the file name. Only with one CSV")
    ap.add_argument("--out", default="data_gz", help="dataset folder for Gazebo runs")
    ap.add_argument("--note", default="", help="free text: what was done in this run")
    ap.add_argument("--summary-md", default="", help="also write a Markdown table of the runs to this file")
    ap.add_argument("--strict", action="store_true", help="exit with an error if any CSV could not be read")
    args = ap.parse_args()
    if args.run_id and len(args.csv) > 1:
        ap.error("--run-id only works with a single CSV; with several, each run is named after its file")
    metas, failures, used = [], [], set()
    for path in args.csv:
        rid = args.run_id or run_id_from(path)
        base, k = rid, 2
        while rid in used:                     # same file name from two folders
            rid, k = f"{base}_{k}", k + 1
        used.add(rid)
        try:
            m = import_run(path, rid, args.out, args.note)
        except (ValueError, OSError) as err:
            failures.append((path, str(err)))
            print(f"SKIPPED {path}: {err}")
            continue
        metas.append(m)
        e = m["end"]
        print(f"{m['run_id']}: {m['source_rows']} plugin rows -> {m['n_rows']} rows at 1 s; "
              f"{m['outcome']} at t = {e['end_t']:.1f} s"
              + (f" ({e['exit_reason']}), {e['rows_dropped']} rows from that point on dropped" if e['exit_reason'] else ""))
        for name, cmds in m["commands"].items():
            for c in cmds:
                print(f"    {name}: {c['from']:g} -> {c['to']:g} at t = {c['t_command']:.1f} s")
    print(f"done: {len(metas)} imported, {len(failures)} skipped, into {args.out}")
    if args.summary_md:
        write_summary_md(metas, failures, args.summary_md)
    if args.strict and failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
