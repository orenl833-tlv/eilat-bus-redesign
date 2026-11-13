#!/bin/bash
# Re-run of the final checks with students, dorm workers, campus staff 80, new-line delays from today's late
# lines and the rarest trips trimmed; then the same check under 3 perturbed demand guesses. Outputs: data/rerun/
cd "$(dirname "$0")/.."
export MODE=design OD=demand PYTHONPATH=.:scripts:analysis
o=data/rerun
step() { local n=$1; [ -f "$o/$n.done" ] && return; echo "== $n $(date +%T)"; shift; "$@" && touch "$o/$n.done"; }
run_check() { SEASON=$1 DEMAND_PERTURB=$3 python3 scripts/check_tt.py $2 > $o/check_$4.log 2>&1 && cp data/check_tt.json $o/check_$4.json; }
run_app() { SEASON=$1 python3 analysis/app_rider.py $2 > $o/app_$1.log 2>&1 && cp data/app_rider_$1.json $o/app_$1.json; }
step check_winter run_check winter data/net_F2.json "" winter
step check_summer run_check summer data/net_F2_summer.json "" summer
for s in 1 2 3; do step check_perturb$s run_check winter data/net_F2.json $s perturb$s; done
step app_winter run_app winter data/net_F2.json
step app_summer run_app summer data/net_F2_summer.json
# what moved the result: each of the new changes undone alone (winter, timetable check)
run_env() { env $1 SEASON=winter python3 scripts/check_tt.py data/net_F2.json > $o/check_$2.log 2>&1 && cp data/check_tt.json $o/check_$2.json; }
step undo_delay run_env NEW_LINE_DELAY=all undo_delay
step undo_tourist run_env TOURIST_BUS_SHARE=1 undo_tourist
step undo_students run_env UNI_STUDENTS=0 undo_students
step undo_trim run_env OD_TRIM=0 undo_trim
echo "== all done $(date +%T)"
