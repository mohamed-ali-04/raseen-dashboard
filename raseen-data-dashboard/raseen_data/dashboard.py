"""Make the replay page for Gazebo runs.

Empty viewer (for the repo): open it and drop plugin CSVs on it.

    python3 -m raseen_data.dashboard --empty --out viewer/raseen_dashboard.html

With runs already inside (to send someone a page that opens straight to a run):

    python3 -m raseen_data.dashboard --data data_gz --out gazebo_replay.html

Either way it is one HTML file. It needs no server and no internet.
"""
import argparse
import json
import math
from pathlib import Path

import pandas as pd

SHOW = {"t": 2, "x": 2, "y": 3, "heading_deg": 2, "u": 4, "drift_deg": 2, "rudder_deg": 2, "rpm": 1,
        "thrust": 0, "ukc_min": 4, "bank_force_y": 0}
TEXT = ["ukc_status", "shallow_status", "risk"]
TEMPLATE = Path(__file__).parent / "dashboard_template.html"


def _clean(v):
    """JSON has no NaN: missing numbers become null."""
    if isinstance(v, float) and not math.isfinite(v):
        return None
    if isinstance(v, dict):
        return {k: _clean(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_clean(x) for x in v]
    return v


def render(runs: list) -> str:
    payload = _clean({"runs": runs})
    data = json.dumps(payload, separators=(",", ":"), allow_nan=False).replace("</", "<\\/")
    return TEMPLATE.read_text().replace("__DATA__", data)


def make_dashboard(data_dir, out_path, run_ids=None) -> list[str]:
    data_dir = Path(data_dir)
    index = pd.read_csv(data_dir / "index.csv")
    run_ids = run_ids or list(index["run_id"])
    runs = []
    for rid in run_ids:
        table = pd.read_csv(data_dir / "labelled" / f"{rid}.csv.gz")
        meta = json.loads((data_dir / "runs" / rid / "meta.json").read_text())
        meta.setdefault("file", Path(meta.get("source_csv", "")).name)
        cols = {c: table[c].round(d).tolist() for c, d in SHOW.items()}
        cols.update({c: table[c].fillna("").astype(str).tolist() for c in TEXT})
        cols["meta"] = meta
        runs.append(cols)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(render(runs))
    return run_ids


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default="data_gz")
    ap.add_argument("--out", default="gazebo_replay.html")
    ap.add_argument("--runs", default="", help="comma-separated run ids; default: all")
    ap.add_argument("--empty", action="store_true", help="write the viewer with no runs inside")
    args = ap.parse_args()
    if args.empty:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(render([]))
        print(f"wrote {args.out} (empty viewer: open it and drop plugin CSVs on it)")
        return
    ids = make_dashboard(args.data, args.out, [r for r in args.runs.split(",") if r] or None)
    print(f"wrote {args.out} with runs: {', '.join(ids)}")


if __name__ == "__main__":
    main()
