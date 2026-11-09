# Eilat urban buses: a better network on the same budget

**Answer: yes.**
- **No extra cost:** no more buses than today and about the same bus-hours, on existing streets and stops.
- **Shorter trips:** a reorganised network cuts the door-to-door time residents and tourists feel by
  **12-18%**, depending on how far the city wants to go.
- **No real losers:** no neighbourhood loses more than 3%.
- **Kept stops:** every hotel, the hospital, the campus, the malls and the terminals keep a stop.

Three options follow, from the most cautious to the most far-reaching. The interactive comparison is in
`web/eilat.html`. The method and every number are documented here:
- [PARAMETERS.md](PARAMETERS.md): the assumptions, with sources and tests;
- [ATTRACTORS.md](ATTRACTORS.md): the demand data and its weights;
- [FLEET.md](FLEET.md) and [ACCESS.md](ACCESS.md): today's network.

## How it was done

1. **Today's network.**
   - 441 urban trips on a weekday (GTFS, 10 Nov 2026).
   - Real run times from SIRI: trips take 1.24 × the timetable, and 1.5-1.7 × on the south coast.
2. **Demand.**
   - Residents of 14 census areas, with their car ownership; trips to work, school, services and leisure;
     hotel guests' outings. By period and season.
   - Calibrated on Rav-Kav boardings per line (2025 Q4): 14% error per line, 15% out of sample.
   - Two calibrations are kept (A fitted, B leaning on the prior purpose mix). Every option must win under
     both.
3. **Perceived time.**
   - Walk and wait count 1.6 × a minute on board; midday walking in the hot seasons counts 2.5 ×.
   - A transfer adds 5 min plus the real wait.
   - Lines sharing a street share riders.
4. **Rules.**
   - Budget: no more buses at once and no more bus-hours than today.
   - Equity and coverage: no area more than 10% worse, coverage kept.
   - Usable lines: every line runs 09:00-19:00 at least hourly; frequency changes ≤ 2 × between periods.
   - Protected stops: 27 stops for luggage, the hospital and the campus are never passed or cut, and must
     keep a line all day.
   - Existing stops only; school lines 80-82 unchanged.
5. **Search.**
   - Simulated annealing over today's lines plus candidates: detours cut, quiet stops passed, 42 new direct
     lines.
   - Then frequencies are tuned per season: one network, three timetables (winter, spring/autumn, summer
     holiday).

## What the search found

- **Pass the quiet stops on the long loops.** Lines 5, 6 and 6א pass 16-17 of their ~70 stops without stopping.
  Every one of them has another stop of the line close by.
- **More frequent service where it pays:** the hotel axis, the south coast in the evening, and evenings in
  general.
- **A flatter midday peak.** The fleet is set by 12:00-15:00.
- **Near-duplicate lines merged** (options 2 and 3): lines 1 and 2, and 3 and 4, each become one line at a
  higher frequency.
- **New direct lines were not chosen.** In a city this size a frequent line through the centre beats a rare
  direct one.

## The three options

| | 1. Keep every line | 2. Restructure | 3. Restructure, fewer buses |
|---|---|---|---|
| Perceived door-to-door time vs today (calibration A / B) | **0.870 / 0.883** | **0.829 / 0.847** | **0.815 / 0.830** |
| With measured bus bunching (waits × 1.19) | 0.862 / 0.874 | 0.821 / 0.838 | 0.807 / 0.821 |
| Range over all sensitivity tests | 0.84-0.89 | 0.79-0.85 | 0.77-0.84 |
| Worst-off neighbourhood | up to +3% (areas 33-34, mostly car owners) | every area better | every area better |
| Buses at once (model, by season) | 34-35 (today 35) | 31-34 | 31-32 |
| Buses needed when trips are assigned to buses | 31-33 (today 35) | 30-34 | 30-34 |
| Bus-hours a weekday incl. layovers and depot runs | 508-534 (today 504) | 521-547 | 526-551 |
| Bus trips vs today (model elasticity) | +1% | +3% | +3% |

- **The fleet holds in every option.** Even when every trip is assigned to a real bus, no option needs more
  than today's 35.
- **Option 3's saving mostly disappears in real blocks.** It needs 30-34 buses, not 31-32, so its money
  advantage over option 2 is uncertain.
- **Paid bus-hours come out 1-9% above today** once real layovers are counted. The budget formula counts
  service time only. Aligning timetables between lines should absorb part of it; this has to be checked
  before claiming equal cost.

![Option 2](figs/proposal_full_warm.png)

### Who gains and who loses (winter, 09:00-12:00, median change over areas, perceived minutes)

| Destination | Option 1 | Option 2 | Option 3 |
|---|---|---|---|
| Hotels, North Beach | +3 | **-6** | **-8** |
| Star Eilat / old central station | 0 | -4 | -7 |
| City hall | +1 | -2 | -4 |
| Hospital | +1 | 0 | -1 |
| Big centre | +4 | +4 | 0 |
| Coral Beach | +3 | -2 | +4 |

- **Option 1 at mid-morning is a little slower** to most places. Its gains come in the evening, at midday
  and on the coast.
- **Options 2 and 3 are faster to the hotels, the centre and Star Eilat,** but trips to Big are slower in
  option 2.
- Area-by-area numbers: `data/assess_<option>_areas.csv`, `data/assess_<option>_traveltime.csv`, and the
  interactive page.

## Stops

- **Protected (never passed, never cut, always served):** every stop named for a hotel, the hospital, the
  central station / Star Eilat, the city-entrance park-and-ride, the malls, the border crossings, the
  airport and the campus.
- **Why the coverage rule was added:** without it, the first runs dropped the Caesar hotel stop (~350
  boardings and alightings a day) and the campus stops.
- **Stops that lose all service** (full lists: `data/stops_<option>.csv`):

| | Stops no longer served | Their riders today (model) | Nearest served stop: median / max |
|---|---|---|---|
| Option 1 | 33 | ~400 a day | 73 m / 288 m |
| Option 2 | 31 | ~780 a day | 110 m / 268 m |
| Option 3 | 33 | ~680 a day | 40 m / 336 m |

- **Stops that some line passes:** another line still stops at every one of them.
- **The busiest stop dropped carries ~130 a day,** with another stop 67 m away.

## Will buses be overfull?

- **The busiest bus in the busiest hour** (1.5 × the period average):

  | | Riders on the busiest bus |
  |---|---|
  | Today | 78 (line 16, summer evenings) |
  | Option 1 | 78 |
  | Option 2 | 69 |
  | Option 3 | 71 |

- **None is over a full 12 m bus** (~85). Today and options 1-2 each have 4 line-periods above the
  comfortable 65; option 3 has 2.
- **School bells are staggered,** so classes leave over ~13:15, 14:10, 15:00 and 15:45 (estimated from the
  Education Ministry's weekly hours).
  - The biggest wave is 400-480 students per comprehensive school at 14:10.
  - The buses passing within 300 m in the next 15 minutes could take most of them even before
    corrections. After allowing for direction and for riders already on board, they overflow only if
    more than ~20% of the students leaving at one bell ride, 2-5 × the estimate.
  - School lines 80-82 stay.

## Timetables, buses and charging (`scripts/blocking.py`)

| | Buses | Bus-hours | km per bus a day (mean / max) | Buses over 250 km | Driver shifts (rough) |
|---|---|---|---|---|---|
| Today | 35 | 504 | 248 / 300 | 23 | 71 |
| Option 1 | 31-33 | 508-534 | 264-287 / 341 | 21-29 | 76-83 |
| Option 2 | 30-34 | 521-547 | 270-284 / 346 | 24-27 | 84-87 |
| Option 3 | 30-34 | 526-551 | 268-299 / 341 | 24-29 | 86-89 |

- **Most buses already run more than an e-bus's ~250 km a day,** so charging in the 10:00-12:00 lull is
  needed today and in every option. The depot is next to the centre.
- **Driver shifts** (≤ 8.5 h per bus block) are indicative only. Fewer, longer bus days mean more split
  shifts.

## Reliability (SIRI)

- **Gaps between buses vary** (CV 0.43), so a random passenger waits 19% longer than the timetable implies.
- **Lateness at mid-route:**
  - median +3.5 min; 41% of trips more than 5 min late;
  - loops 1, 2 and 6 run 8-9 min late half-way round because their timetables are optimistic.
- **The options use measured run times,** and score slightly better against today once bunching is
  counted.

## Friday and Saturday (`scripts/weekend.py`)

- **The weekend scale is calibrated** on Rav-Kav weekly minus 5 × weekday boardings (2025 Q4).
- **Each option keeps its weekday lines,** with frequencies tuned per day under today's same-day budget, and
  only in hours that have service today: Shabbat hours are a policy, not a model choice.
- **Friday:** 13-15% better in every option, with fewer buses at the peak (23-27 against today's formula
  budget of 33).
- **Saturday:**
  - no better evening timetable was found within today's ~70 bus-hours;
  - options 1-2 overshoot the budget and option 3 stays within it but is a little worse;
  - **recommendation: keep today's Saturday timetable.**

## The future: Star Eilat, the old airport district and Shifolei HaHar

- **Demand.** The planned districts add ~12,300 residents, ~5,900 jobs and ~3,150 hotel rooms. Bus trips
  grow by **8-10%**, which justifies about **+3 buses and +32-40 bus-hours**.
- **On today's budget, without re-tuning,** the options stay better than today's network:
  - option 1: 0.91-0.93;
  - option 2: 0.87-0.90;
  - option 3: 0.86-0.88.
- **The old airport district** has stops ~200 m away.
- **Shifolei HaHar** is ~850 m from the nearest stop and gets a **spur**: lines 5 and 6 leave Yahel St.,
  serve 3 new stops and return (~1.2 km each way, ~9-10 min a trip).
  - The district's streets aren't available here (OpenStreetMap is blocked from this environment), so the
    spur is an assumption.

| Under future demand | Without spur | With spur | Shifolei HaHar residents | Peak buses | Bus-hours |
|---|---|---|---|---|---|
| Option 1 | 0.91 | **0.85-0.86** | 0.99 → **0.47** | 35 → 36 | 394 → 419 |
| Option 2 | 0.87-0.88 | **0.81-0.82** | 1.00 → **0.47** | 34 → 35 | 395 → 422 |
| Option 3 | 0.85-0.86 | **0.79-0.80** | 1.00 → **0.47** | 32 → 34 | 404 → 431 |

The spur fits within the budget growth the extra demand justifies.

## What to check before acting

- **Lines 1, 2 and 4 carry ~5,000 boardings a day today.** Options 2 and 3 merge them away. The model
  under-predicts lines 2 and 6 a little (0.80 and 0.76 of reality). Option 1 is the safe first step;
  merging should wait for stop-level Rav-Kav data.
- **Dropped and passed stops:** check them one by one, especially for elderly riders.
- **Paid bus-hours (+1-9%):** close the gap by aligning timetables before claiming equal cost.
- **Not modelled:** driver rostering, depot capacity, charging infrastructure.
- **The summer holiday** is the least certain season: there is no summer Rav-Kav quarter.
- **What the model does:** it compares networks. The +1-3% bus trips is its elasticity, not a forecast.

## Decisions taken along the way, and errors found and fixed

**Decisions**
- **Stop cost.** A real stop costs ~30 s; passing a stop saves 30 s × the chance the bus would have stopped.
  The average per scheduled stop is only 11 s in Eilat.
- **Calibration quarter.** Only 2025 Q4 is used; 2025 Q2 and 2026 Q1 contain wars and serve as checks only.
- **Usability rules, protected stops and their coverage rule** were added when earlier runs produced
  networks no passenger could use, or that dropped a hotel stop.
- **A conservative option** keeps every line. The best solutions merge big lines, which is a big step.
- **Weekend service only in today's hours**, out of respect for the Shabbat status quo.

**Errors found and fixed**

Each fix was followed by recalibration and new runs. Earlier results are kept in `data/superseded/`.
1. **Common lines.** Riders were assigned to a single line, so lines sharing a street got no riders; now
   they board the first attractive bus. Calibration error fell from 34% to 13%.
2. **Bus trips with no ride.** A "bus" path could contain no ride and earned a 5-min bonus; stops are now
   split into before-ride and after-ride nodes.
3. **Purpose scales applied twice.** They are now applied once.
4. **Protected stops.** They were protected from skipping but not from a dropped line; they must now
   always keep a line.
5. **Penalties too weak.** The protected-stop and weekend-budget penalties were raised so they act as hard
   rules.

## The lines of each option (winter timetable; minutes between buses by period)

Suffix `x` = passes its quietest stops without stopping; `s` = detours cut. School lines 80-82 are unchanged and not shown.


### Option 1: keep every line

| Line | From → to | Stops (passed) | Run, midday (min) | 06-09 | 09-12 | 12-15 | 15-19 | 19-24 | Boardings A / B |
|---|---|---|---|---|---|---|---|---|---|
| 1/0 | ת. מרכזית אילת/רציפים → ת. מרכזית אילת | 71 (0) | 75 | - | 40 | 40 | 40 | 60 | 137 / 126 |
| 15/0 | ת. מרכזית אילת/רציפים → דרך מצרים/מתחם קולוניה  | 33 (0) | 37 | 24 | 30 | 20 | 15 | 30 | 642 / 690 |
| 16/1x | דרך מצרים/מלון הנסיכה → ת. מרכזית אילת | 28 (3) | 39 | - | 24 | 40 | 20 | 20 | 495 / 596 |
| 2/0x | ת. מרכזית אילת/רציפים → ת. מרכזית אילת | 52 (20) | 73 | - | 60 | 30 | 20 | 15 | 768 / 584 |
| 3/0s | ת.כבאות/ששת הימים → חנה וסע מבואות אילת | 27 (0) | 24 | 24 | 20 | 20 | 24 | 30 | 539 / 586 |
| 3/1s | חניון אגד → ששת הימים/שרה אמנו | 27 (0) | 29 | 24 | 20 | 20 | 24 | 30 | 536 / 563 |
| 4/0x | ת.כבאות/ששת הימים → חנה וסע מבואות אילת | 23 (10) | 30 | 24 | 40 | 30 | 15 | 24 | 408 / 409 |
| 4/1x | חניון אגד → ששת הימים/שרה אמנו | 26 (10) | 32 | 24 | 40 | 30 | 15 | 24 | 426 / 431 |
| 5/0s | ת.כבאות/ששת הימים → חנה וסע מבואות אילת | 57 (0) | 60 | 30 | 30 | 15 | 30 | 60 | 1,343 / 1,180 |
| 5א/0s | ת.כבאות/ששת הימים → חנה וסע מבואות אילת | 57 (0) | 60 | 60 | 60 | 60 | 60 | 30 | 717 / 618 |
| 6/1x | חניון אגד → ששת הימים/שרה אמנו | 54 (16) | 75 | 30 | 60 | 40 | 60 | 30 | 914 / 787 |
| 6א/1x | חניון אגד → ששת הימים/שרה אמנו | 56 (17) | 82 | - | 40 | 30 | 20 | 20 | 1,511 / 1,285 |

### Option 2: restructure

| Line | From → to | Stops (passed) | Run, midday (min) | 06-09 | 09-12 | 12-15 | 15-19 | 19-24 | Boardings A / B |
|---|---|---|---|---|---|---|---|---|---|
| 15/0 | ת. מרכזית אילת/רציפים → דרך מצרים/מתחם קולוניה  | 33 (0) | 37 | 40 | 30 | 24 | 20 | 20 | 627 / 647 |
| 16/1 | דרך מצרים/מלון הנסיכה → ת. מרכזית אילת | 31 (0) | 39 | 24 | 40 | 30 | 24 | 15 | 506 / 567 |
| 5/0 | ת.כבאות/ששת הימים → חנה וסע מבואות אילת | 71 (0) | 69 | 20 | 20 | 24 | 40 | 20 | 1,650 / 1,448 |
| 6/1 | חניון אגד → ששת הימים/שרה אמנו | 70 (0) | 76 | - | 40 | 30 | 24 | 20 | 1,358 / 1,139 |
| 6א/1 | חניון אגד → ששת הימים/שרה אמנו | 73 (0) | 82 | 60 | 60 | 40 | 30 | 24 | 1,103 / 919 |
| 2/0x | ת. מרכזית אילת/רציפים → ת. מרכזית אילת | 52 (20) | 73 | 30 | 30 | 30 | 24 | 40 | 292 / 271 |
| 3/0s | ת.כבאות/ששת הימים → חנה וסע מבואות אילת | 27 (0) | 24 | 20 | 15 | 10 | 20 | 30 | 935 / 952 |
| 3/1s | חניון אגד → ששת הימים/שרה אמנו | 27 (0) | 29 | 20 | 15 | 10 | 20 | 30 | 841 / 889 |
| 5א/0x | ת.כבאות/ששת הימים → חנה וסע מבואות אילת | 58 (17) | 74 | 40 | 30 | 30 | 30 | 40 | 1,109 / 957 |
| A14H/0 | קמפוס אילת/המלחה → מלון מג'יק פאלאס/קראון פלאזה | 12 (0) | 14 | 15 | 20 | 20 | 40 | - | 131 / 110 |
| A14H/1 | מלון מג'יק פאלאס/קראון פלאזה → קמפוס אילת/המלחה | 25 (0) | 27 | 15 | 20 | 20 | 40 | - | 259 / 321 |

### Option 3: restructure, fewer buses

| Line | From → to | Stops (passed) | Run, midday (min) | 06-09 | 09-12 | 12-15 | 15-19 | 19-24 | Boardings A / B |
|---|---|---|---|---|---|---|---|---|---|
| 15/0 | ת. מרכזית אילת/רציפים → דרך מצרים/מתחם קולוניה  | 33 (0) | 37 | 30 | 40 | 24 | 15 | 15 | 638 / 658 |
| 16/1 | דרך מצרים/מלון הנסיכה → ת. מרכזית אילת | 31 (0) | 39 | 30 | 40 | 30 | 15 | 24 | 600 / 648 |
| 5/0 | ת.כבאות/ששת הימים → חנה וסע מבואות אילת | 71 (0) | 69 | 12 | 15 | 20 | 24 | 24 | 2,018 / 1,774 |
| 2/0s | ת. מרכזית אילת/רציפים → ת. מרכזית אילת | 58 (0) | 70 | 60 | 30 | 24 | 20 | 30 | 422 / 369 |
| 3/0s | ת.כבאות/ששת הימים → חנה וסע מבואות אילת | 27 (0) | 24 | 10 | 10 | 12 | 15 | 20 | 1,192 / 1,177 |
| 3/1s | חניון אגד → ששת הימים/שרה אמנו | 27 (0) | 29 | 10 | 10 | 12 | 15 | 20 | 1,313 / 1,299 |
| 5א/0x | ת.כבאות/ששת הימים → חנה וסע מבואות אילת | 58 (17) | 74 | - | 30 | 24 | 30 | 20 | 1,040 / 887 |
| 6/1x | חניון אגד → ששת הימים/שרה אמנו | 54 (16) | 75 | - | 30 | 20 | 30 | 15 | 1,603 / 1,320 |
| A14H/0 | קמפוס אילת/המלחה → מלון מג'יק פאלאס/קראון פלאזה | 12 (0) | 14 | 40 | 24 | 40 | 60 | 30 | 32 / 28 |
| A14H/1 | מלון מג'יק פאלאס/קראון פלאזה → קמפוס אילת/המלחה | 25 (0) | 27 | 40 | 24 | 40 | 60 | 30 | 298 / 307 |
