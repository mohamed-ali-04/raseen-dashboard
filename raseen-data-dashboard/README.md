# RASEEN data dashboard

Replays runs of the RASEEN Suez Canal simulation (Gazebo Harmonic + the team's
RASEEN hydrodynamics plugin) and turns them into labelled data for AI training.

The data comes from the plugin only. When a run starts, the plugin
(`libraseen_hydrodynamics.so`, built from `hydro/plugin` in the team's Gazebo package)
writes a CSV of the ship's state and forces, plus a small `.identity.json` file that
names the parameter set, the vessel and the plugin build. This folder only reads
those files; it never changes the plugin or its output.

## Try it

Open `viewer/raseen_dashboard.html` in a browser and click **Try the example run**,
or **Open CSV files…** and pick `examples/run_0001.csv.gz`.

Any CSV the plugin writes works, from anyone's machine: drop it on the page.
Nothing is uploaded; the files are read in the browser only.

| Button | What it does |
|---|---|
| **Watch a folder…** | Chrome / Edge. Pick the folder runs are recorded into, once. Every run in it is listed, new runs appear on their own, and a run that is still recording keeps growing. The page remembers the folder. |
| **Open CSV files…** | Pick one or more `.csv` / `.csv.gz` files, plus their `.identity.json` files to show the parameter set and plugin build. Dropping files on the page does the same. |

What the page shows: the track from above, speed, heading, rudder, propeller,
clearance under the keel, bank force, the rudder and propeller commands read back
from the data, where and why the run ended, and which parameter set and plugin build
recorded it.

## Record a run

Needs the team's Gazebo package with the plugin built (`hydro/plugin/build/libraseen_hydrodynamics.so`).

One time, in Ubuntu (WSL):

    mkdir -p /mnt/d/raseen_runs          # D:\raseen_runs, where runs are saved
    chmod +x tools/*.sh

Each run:

1. **Tab 1:** `tools/new_run.sh` names the run (`run_0001`, `run_0002`, ...), tells the
   plugin to save into `D:\raseen_runs`, and opens Gazebo. Press Play in Gazebo.
2. **Dashboard:** **Watch a folder…** → `D:\raseen_runs` (only the first time).
3. **Tab 2:** drive the ship:

       tools/drive.sh rpm 60        # propeller
       tools/drive.sh rudder 10     # rudder, degrees
       tools/drive.sh fast          # 20x faster than real time
       tools/drive.sh stop          # propeller and rudder to 0
       tools/drive.sh watch         # plugin diagnostics

4. Close Gazebo (or Ctrl+C in tab 1) to end the run.

Another folder: `tools/new_run.sh /path/to/folder`. Plugin package somewhere else:
`export RASEEN_HYDRO_DIR=/path/to/.../hydro` first.

Without the script, the plugin is told where to write by one variable:
`export RASEEN_CSV_PATH=/mnt/d/raseen_runs/run_0002.csv` before `gz sim`. It
overwrites that file at every launch, so use a new name each run.

## How a run is read

The page and the Python importer apply the same rules, and a test checks they give
the same result.

- **End of the run:** the first row the plugin marks invalid (`valid` ≠ 1, or
  `validity_state` ≠ `in_domain`); without those columns, the first row with
  `ukc_min` ≤ 0. That row and everything after it are dropped, because the plugin
  switches its canal physics off there. If `exit_reason` mentions ukc, or `ukc_min` ≤ 0,
  the run counts as grounded; otherwise as a domain exit.
- **One row per second:** the latest plugin value at or before each second, plus the last usable row.
- **Commands:** a rudder or propeller value held for at least 0.5 s is a steady value;
  a change between two steady values is a command.
- **Labels for training:** from the end time, `critical` within 60 s, `caution`
  within 180 s, otherwise `normal`. Runs that stay valid are all `normal`.
- **Required columns:** `t, x, y, yaw_deg, u, ukc_min`. Every other plugin column is
  optional, so CSVs from older plugin versions still load; a missing one shows as
  "Not in this file".

## Build the training dataset (Python)

    pip install -r requirements.txt            # or: sudo apt install python3-pandas python3-numpy python3-pytest
    python3 -m raseen_data.gazebo_import --csv /mnt/d/raseen_runs/*.csv --out data_gz
    python3 -m pytest

Writes `data_gz/runs/<run>/data.csv.gz` (one row per second), `meta.json` (outcome,
end point, commands, plugin identity), `data_gz/labelled/<run>.csv.gz` (plus labels)
and `data_gz/index.csv`. A CSV that can't be read is skipped with the reason.

A page with runs built in (opens straight to them):
`python3 -m raseen_data.dashboard --data data_gz --out my_runs.html`

## On GitHub

`.github/workflows/raseen-dashboard.yml` runs on every push and pull request that
changes this folder:

1. the tests, including one that opens the dashboard in Chrome and checks it reads
   a run exactly like the Python importer
2. every CSV in `examples/` is read; a table of them (rows, outcome, end time,
   parameter set, plugin build) appears on the workflow run's **Summary** page.
   A CSV that can't be read fails the check
3. the dashboard and example runs are attached to the workflow run as a download

To check your own run on GitHub: add its `.csv` (or `.csv.gz`) and `.csv.identity.json`
to `examples/` in a pull request, then open the **Actions** tab.

**Web page (optional).** The workflow can also publish the dashboard at
`https://<owner>.github.io/<repo>/`. A repo admin turns it on once: Settings → Pages →
Source: **GitHub Actions**, then Settings → Secrets and variables → Actions →
Variables → `DASHBOARD_PAGES` = `true`. Private repos need a paid GitHub plan for Pages.

## Files

| Path | Job |
|---|---|
| `viewer/raseen_dashboard.html` | The dashboard. One file, no install, no internet |
| `tools/new_run.sh` | Starts a recorded run with the next free name |
| `tools/drive.sh` | Propeller, rudder, speed-up and diagnostics while a run records |
| `raseen_data/gazebo_import.py` | Plugin CSVs → stored runs, metadata and labels |
| `raseen_data/label.py` | Labels each second from how the run ended |
| `raseen_data/dashboard.py` | Builds the dashboard page from `dashboard_template.html` |
| `examples/` | Runs recorded with the plugin. `run_0001`: rudder 10° twice, 60 rpm, grounds at 9:39 |
| `tests/` | Tests |

## Not checked yet

- the plugin's force sign convention (forces are in N and moments in N m: `Z` equals the ship's weight)
- whether `y = 0` is the canal centreline in every world (it is where the ship starts)
- the canal edges are not drawn on the map, because the section shape of this world has not been read
- in run_0001 the plugin's `shallow_status` becomes `out_of_domain` about 14 s before the grounding
  while `validity_state` stays `in_domain`; the end rule follows `valid` / `validity_state` only.
  The page shades that stretch on the charts
- the physics uses KVLCC2 coefficients marked qualitative by the plugin's authors
