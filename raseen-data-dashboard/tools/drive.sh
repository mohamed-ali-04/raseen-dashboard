#!/usr/bin/env bash
# Send commands to the ship while a run is recording. Run from any Ubuntu tab.
#
#   tools/drive.sh rpm 60        propeller to 60 rpm
#   tools/drive.sh rudder 10     rudder to 10 degrees (the plugin turns it gradually)
#   tools/drive.sh fast          run the simulation 20x faster than real time
#   tools/drive.sh fast 5        ... or another factor
#   tools/drive.sh stop          propeller 0 and rudder 0
#   tools/drive.sh watch         print the plugin's live diagnostics (Ctrl+C to stop)
set -euo pipefail
WORLD_NAME="suez_ever_given_hydro"
T="/model/vessel/hydro"

send() { gz topic -t "$T/$1" -m gz.msgs.Double -p "data: $2" && echo "$1 -> $2"; }

case "${1:-}" in
  rpm)    send prop_rpm   "${2:?give a value, e.g. tools/drive.sh rpm 60}" ;;
  rudder) send rudder_deg "${2:?give a value, e.g. tools/drive.sh rudder 10}" ;;
  stop)   send prop_rpm 0; send rudder_deg 0 ;;
  fast)   f="${2:-20}"
          gz service -s "/world/$WORLD_NAME/set_physics" --reqtype gz.msgs.Physics --reptype gz.msgs.Boolean \
            --timeout 3000 --req "max_step_size: 0.01, real_time_factor: $f" && echo "speed -> ${f}x real time" ;;
  watch)  gz topic -e -t "$T/diagnostics" ;;
  *)      sed -n '2,10p' "$0"; exit 1 ;;
esac
