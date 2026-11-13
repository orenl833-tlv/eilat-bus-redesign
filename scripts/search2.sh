#!/bin/bash
# Search again on the updated demand (students, dorms, tourists 35% by bus, summer beaches, new-line delays from
# today's late lines): two chains (from net_F2 and from net_H), then check both against net_F2 on unseen draws.
cd "$(dirname "$0")/.."
export MODE=design OD=demand FREQ_RULE=1 PYTHONPATH=.:scripts:analysis
o=data/rerun
python3 scripts/optimize_tt.py data/net_F2.json 1500 51 > $o/search_F2.log 2>&1 &
python3 scripts/optimize_tt.py data/net_H.json 1500 52 > $o/search_H.log 2>&1 &
wait
SEASON=winter python3 scripts/check_tt.py data/net_F2.json data/opt_tt_net_F2_s51_design_demand_freq.json \
  data/opt_tt_net_H_s52_design_demand_freq.json > $o/check_search2.log 2>&1 && cp data/check_tt.json $o/check_search2.json
echo "== search2 done $(date +%T)"
