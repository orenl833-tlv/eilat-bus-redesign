# Eilat bus network redesign

**Interactive map, today against the proposal (Hebrew):** https://claude.ai/artifact/DJSeiVJX6hTwAZyhMu8nMV · **LinkedIn post:** https://lnkd.in/p/d9rVPwGn

Can a city's buses serve people better with the same fleet and the same drivers? For Eilat, a closed city of
55,000 with ~35 urban buses, the answer from public data is **yes.**

**The recommended network** (`data/net_F2.json`, found by a search that scores every candidate on its timetable
as buses really run: GPS run times per street segment, hour and direction; real delays per line, direction
and hour; demand-weighted trips; every area keeps its 20-min line nearby; checked on unseen leaving times and delays):
- **~5% shorter door-to-door trips in winter, ~10% in summer** (summer headways, `data/net_F2_summer.json`); perceived time improves ~5% in winter and ~11% in summer.
- **Fewer buses:** 32 against today's 34, with 15% terminal recovery; **the same drivers** (91 with overtime).
- **Costs ~NIS 1.2 M a year:** ~3% more bus-hours, mostly evening service to 23:00.
- **Two residential areas lose:** area 33 (+2% in winter) and area 14 (+3% in summer); workplaces lose most (industrial zone +15%, Begin high school +14%).

**What changes:**
- Three new two-way lines on the fastest streets: 7 North Beach hotels – Derech HaBsamim, 8 Big centre –
  Derech HaBsamim, 9 Shahamon – city hall.
- Lines 3 and 5 drop their detours; 15 and 16 pass their quiet stops; 6 stays.
- Lines 1, 1א, 2, 4, 5א and 6א are withdrawn; evening service runs to 23:00.

**Also found:** missed transfers cost today's network ~6 min a trip for a rider who cannot see delays coming (the
proposal ~4); a bus lane on Sderot HaTmarim is the best single fix; a timed-transfer hub (one or several) does not
pay off in Eilat.

**An earlier plan claimed ~16%.** It was chosen with a frequency-based model (wait = half the headway), which
overstated waiting on today's sparse lines. On the timetable it gives ~4%. See REDESIGN.md, "Timetable check".

**Read first:**
- the [decision brief](https://claude.ai/artifact/EhZ6aFgBzyymEFFGG5fVSP) (Hebrew, `web/brief.html`);
- [SUMMARY_HE.md](SUMMARY_HE.md);
- [REDESIGN.md](REDESIGN.md), which also covers the two alternatives checked, the method, the checks and the
  caveats.

**Explore it:**
- the [interactive map](https://claude.ai/artifact/DJSeiVJX6hTwAZyhMu8nMV) (Hebrew): today's lines next to the
  plan's, frequencies by season and time of day, and travel times from every neighbourhood. Source:
  `web/eilat.html`, data built by `scripts/export_page.py`;
- the plan's timetable as GTFS: `exports/gtfs_eilat_proposal.zip`.

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
| Timetables | Lines running per hour, rough driver duties, and the recommended plan as a GTFS feed with vehicle blocks (`exports/gtfs_eilat_proposal.zip`) | `scripts/active_lines.py`, `shifts.py`, `export_gtfs.py`, `exports/` |
| Riders | Example trips planned on the real timetables (today and the plan), as a trip-planner app does | `eilat/timetable.py`, `scripts/journeys_tt.py`, `analysis/timetable_trip.py`, `scripts/build_brief.py` |
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

## Route checks and open items

- **Route checks (OSM roads, OSRM car routing; streets assumed wide enough for a bus):** the 9 stop-to-stop links not
  driven today are direct on main streets, 4-30% longer than straight (`data/new_links_osrm.json`); every end of lines
  7-9 has a legal turnaround without a U-turn, 243-605 m around a block (`data/new_terminals_osrm.json`).
- **Line 9** is a loop (out via Argaman, the central station, the city hall and the hotels; back direct along Eilot).
  Two-way alternatives ending at the city hall or the central station were checked and are worse
  (`analysis/line9_variant.py`, `data/line9_variant_*.json`).
- **For the operator:** a layover spot at each end. Common practice (NZTA, Transport for NSW guidance): kerb space away
  from the stop itself, for one bus at a time here, sized on site by swept-path analysis, with driver facilities nearby.
- **Re-runs on the updated demand** (students and campus dorms, more beach trips in summer, 35% of tourists by bus):
  `scripts/rerun.sh`, outputs in `data/rerun/`.
- **LinkedIn post (Hebrew):** https://lnkd.in/p/d9rVPwGn

## Honest limits

- **The model compares networks.** It doesn't forecast ridership exactly.
- **Purposes:** the purpose mix isn't identifiable from 8 lines, so the plan must win under two
  calibrations (it does).
- **Who travels where is assumed** (sizes of the key places, by distance); only line totals are measured.
  Full Rav-Kav tap data would replace the assumption.
- **Timed transfers:** today lines 1 and 2 meet line 15 at Mall HaYam; the plan's timetable has to
  rebuild such connections.
- **Summer** (July-August) has no ridership data.
- **Not modelled:** a full driver roster (a rough duty check only), depot capacity and charging. The blocks show that e-bus charging is
  already needed today.
- **Shifolei HaHar:** its streets aren't available, so its spur is an assumption.
