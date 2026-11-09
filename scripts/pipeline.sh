#!/bin/bash
# Everything downstream of the weekday searches, in order. Usage: scripts/pipeline.sh <logdir>
cd "$(dirname "$0")/.."
L=${1:-/tmp}
export PYTHONPATH=.:scripts
python3 scripts/seasonal.py keep 400 > $L/p_s_keep.log 2>&1 &
python3 scripts/seasonal.py full_warm 400 > $L/p_s_full.log 2>&1 &
python3 scripts/seasonal.py full_peak-3_warm 400 -3 > $L/p_s_m3.log 2>&1 &
wait
python3 scripts/assess.py keep > $L/p_a_keep.log 2>&1 &
python3 scripts/assess.py full_warm > $L/p_a_full.log 2>&1 &
python3 scripts/assess.py full_peak-3_warm > $L/p_a_m3.log 2>&1 &
wait
python3 scripts/capacity.py > $L/p_capacity.log 2>&1 &
python3 scripts/blocking.py > $L/p_blocking.log 2>&1 &
python3 scripts/stop_table.py > $L/p_stops.log 2>&1 &
wait
python3 scripts/school_peaks.py > $L/p_school.log 2>&1 &
python3 scripts/spur.py > $L/p_spur.log 2>&1 &
python3 scripts/weekend.py > $L/p_weekend.log 2>&1 &
python3 scripts/active_lines.py > $L/p_active.log 2>&1 &
python3 scripts/shifts.py > $L/p_shifts.log 2>&1 &
python3 scripts/evening.py > $L/p_evening.log 2>&1 &
python3 scripts/shift_trips.py > $L/p_shift_trips.log 2>&1 &
python3 scripts/realism.py > $L/p_realism.log 2>&1 &
wait
python3 scripts/future.py keep full_warm full_peak-3_warm > $L/p_future.log 2>&1
python3 scripts/export_gtfs.py > $L/p_gtfs.log 2>&1
python3 scripts/export_page.py > $L/p_page.log 2>&1
python3 scripts/journeys.py > $L/p_journeys.log 2>&1
python3 scripts/build_brief.py
echo PIPELINE DONE
