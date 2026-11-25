#!/usr/bin/env bash
# Start a new recorded run of the RASEEN canal world.
#
#   tools/new_run.sh            records into /mnt/d/raseen_runs (D:\raseen_runs in Windows)
#   tools/new_run.sh  DIR       records into DIR
#
# Picks the next free name (run_0001.csv, run_0002.csv, ...), tells the plugin to
# write there, and opens Gazebo. The plugin also writes <name>.csv.identity.json.
# Point the dashboard's "Watch a folder" at the same folder to see the run live.
#
# Settings you may need to change (or set before running):
#   RASEEN_HYDRO_DIR  the plugin package's hydro folder
set -euo pipefail

RUNS_DIR="${1:-${RASEEN_RUNS_DIR:-/mnt/d/raseen_runs}}"
HYDRO="${RASEEN_HYDRO_DIR:-$HOME/raseen/RASEEN_SuezCanal_GazeboVRX_HYDRODYNAMICS_FINAL_ACCEPTED_v2/hydro}"
WORLD="worlds/hydro/suez_ever_given_hydrodynamics.sdf"

[ -d "$HYDRO" ] || { echo "Plugin package not found at $HYDRO. Set RASEEN_HYDRO_DIR to its hydro folder."; exit 1; }
[ -f "$HYDRO/plugin/build/libraseen_hydrodynamics.so" ] || { echo "Plugin not built: $HYDRO/plugin/build has no libraseen_hydrodynamics.so"; exit 1; }
command -v gz >/dev/null || { echo "gz not found. Open a new Ubuntu tab, or run: source /opt/ros/jazzy/setup.bash"; exit 1; }

mkdir -p "$RUNS_DIR"
n=1
while [ -e "$RUNS_DIR/$(printf 'run_%04d.csv' "$n")" ]; do n=$((n + 1)); done
NAME="$(printf 'run_%04d' "$n")"

cd "$HYDRO"
export GZ_SIM_SYSTEM_PLUGIN_PATH="$PWD/plugin/build${GZ_SIM_SYSTEM_PLUGIN_PATH:+:$GZ_SIM_SYSTEM_PLUGIN_PATH}"
export GZ_SIM_RESOURCE_PATH="$PWD/models:$PWD/../RASEEN_SuezCanal_GazeboVRX_Assets/models${GZ_SIM_RESOURCE_PATH:+:$GZ_SIM_RESOURCE_PATH}"
export RASEEN_CSV_PATH="$RUNS_DIR/$NAME.csv"

echo "=================================================================="
echo " Recording $NAME"
echo " CSV: $RASEEN_CSV_PATH"
echo " Press Play (bottom left in Gazebo), then drive from another tab:"
echo "   tools/drive.sh rpm 60      tools/drive.sh rudder 10"
echo " Close Gazebo or press Ctrl+C here to end the run."
echo "=================================================================="
exec gz sim -v 4 "$WORLD"
