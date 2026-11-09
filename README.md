# Eilat bus network redesign

Can a city's buses serve people better with the same fleet and the same driving hours? For Eilat, a closed
city of 55,000 with ~42 urban buses, the answer from public data is **yes: 12-18% less perceived
door-to-door time, no neighbourhood more than 3% worse, and no extra buses.**

![Today vs restructured network](figs/proposal_full_warm.png)

**Read first:** [SUMMARY_HE.md](SUMMARY_HE.md) (Hebrew, for decision makers), or [REDESIGN.md](REDESIGN.md), the three options, who gains and who loses, the checks and the
caveats.

**Explore it:** [interactive comparison page](https://claude.ai/artifact/DJSeiVJX6hTwAZyhMu8nMV) (Hebrew),
today's lines next to each option, by season and time of day, with travel times from every neighbourhood.
Source: `web/eilat.html`, data built by `scripts/export_page.py`.

## What's in it

| Step | What | Where |
|---|---|---|
| Supply | Today's lines from the national GTFS; real run times from SIRI vehicle locations (real trips take 1.24 × the timetable) | `scripts/gtfs_eilat.py`, `analysis/runtime_factor.py` |
| Fleet | Buses actually running, measured minute by minute over 21 days: 42 buses, 36-38 at the midday peak | `scripts/fetch_siri.py`, `scripts/fleet.py`, [FLEET.md](FLEET.md) |
| Stops | What a stop costs: SIRI speed decomposition (11 s per scheduled stop) and a national regression (33 s) | `analysis/stop_cost.py`, [PARAMETERS.md](PARAMETERS.md) |
| Demand | Census areas and car ownership, schools, hotels, beaches, jobs; trips by purpose, period and season; logit bus vs walk | `eilat/demand.py`, `eilat/model.py`, [ATTRACTORS.md](ATTRACTORS.md) |
| Calibration | Rav-Kav boardings per line (2025 Q4): 14% error per line; out of sample 15% | `scripts/calibrate.py` |
| Evaluation | Frequency-based assignment with common lines; perceived time with walk, wait, transfer and heat weights | `eilat/evaluate.py` |
| Design | Candidate lines (detours cut, quiet stops passed, new direct lines) + simulated annealing under fleet, bus-hour, equity, coverage and usability constraints; seasonal timetables | `eilat/candidates.py`, `scripts/optimize.py`, `scripts/seasonal.py` |
| Timetables | Lines running per hour, rough driver duties, and each option as a GTFS feed with vehicle blocks | `scripts/active_lines.py`, `shifts.py`, `export_gtfs.py`, `exports/` |
| Checks | Sensitivity of every assumed number, capacity per bus, school dismissal waves, vehicle blocks and e-bus range, reliability, weekends, a future scenario with a new district | `scripts/assess.py`, `capacity.py`, `school_peaks.py`, `blocking.py`, `analysis/reliability.py`, `weekend.py`, `future.py`, `spur.py` |

## Data (all public)

- Ministry of Transport GTFS (via Open Bus Stride's archive)
- SIRI real-time bus locations (Open Bus Stride API, Public Knowledge Workshop)
- Ridership per line, CBS census 2022 and statistical areas, and Education Ministry institutions:
  data.gov.il and cbs.gov.il

Raw files are not committed (`data/raw/`, `data/siri/`). The scripts fetch them again.

## Run it

```bash
pip install -r requirements.txt
PYTHONPATH=. pytest -q tests                      # synthetic-network tests of the evaluator and fleet maths
PYTHONPATH=. python3 scripts/calibrate.py         # needs data/ (see the scripts' docstrings for the fetch steps)
PYTHONPATH=. python3 scripts/optimize.py keep 2000
PYTHONPATH=.:scripts python3 scripts/seasonal.py keep 400 && PYTHONPATH=.:scripts python3 scripts/assess.py keep
```

## Honest limits

- **The model compares networks.** It doesn't forecast ridership exactly.
- **Purposes:** the purpose mix isn't identifiable from 8 lines, so every option must win under two
  calibrations.
- **Summer** (July-August) has no ridership data.
- **Not modelled:** a full driver roster (a rough duty check only), depot capacity and charging. The blocks show that e-bus charging is
  already needed today.
- **Shifolei HaHar:** its streets aren't available, so its spur is an assumption.
