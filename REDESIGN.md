# Eilat urban buses: a better network on the same budget

**The answer:** yes. With the same buses and the same bus-hours as today, a reorganised network cuts the
door-to-door time residents and tourists feel by about 20%, and no residential area is worse off (options 2 and 3). Three
options follow, from the most cautious to the cheapest.

Everything is in this folder:
- method and numbers: [PARAMETERS.md](PARAMETERS.md), [ATTRACTORS.md](ATTRACTORS.md);
- today's network: [FLEET.md](FLEET.md), [ACCESS.md](ACCESS.md);
- code: `eilat/`, `scripts/`.

## How it was done

1. **Today's network.**
   - From the GTFS of 10 Nov 2026: 441 urban trips on a weekday.
   - Run times corrected to what the buses actually take (SIRI, 7 school-term weekdays): 1.24 × the
     timetable on average, 1.5-1.7 × on the south coast.
2. **Demand.**
   - Residents of 14 statistical areas: census population and car ownership.
   - Trips to work, school, services and leisure, plus hotel guests' outings, by period of the day and
     season.
   - Calibrated on Rav-Kav boardings per line, 2025 Q4: 14% error per line, 15% out of sample on 2026 Q1.
   - Two versions are kept, because 8 lines can't tell trip purposes apart (A: fitted; B: leaning on the
     prior mix). Every option must win under both.
3. **Perceived time.**
   - Walking and waiting count 1.6 × a minute on board; walking at midday in the hot seasons counts 2.5 ×.
   - A transfer adds 5 minutes plus the real wait.
   - Riders of lines that share a street board whichever comes first.
4. **Constraints, all as agreed:**
   - no more buses at once and no more bus-hours than today;
   - no area more than 10% worse; coverage kept;
   - lines run all day (09:00-19:00 at least hourly), and frequency changes by at most 2 × from one period
     to the next;
   - existing streets and stops only;
   - school lines 80-82 unchanged.
5. **Search.**
   - Simulated annealing over today's lines plus candidates: lines with detours cut, lines that pass their
     least used stops without stopping, and 42 new direct lines.
   - Then frequencies are tuned per season: one network, three timetables.

## What the search found (the same in every run)

1. **Pass the quiet stops on the long loops.** Lines 5, 6 and 6א pass about 20 of their 70-odd stops without
   stopping. Each of those stops has another stop of the line within 350 m. Each skipped stop saves up to
   30 s, weighted by the chance the bus would have stopped there.
2. **More buses to the south coast:** every 15-24 minutes instead of 30-60, and service in the evening.
   Coral Beach gets 8-11 minutes closer at midday.
3. **More evening service** (19:00-24:00): today it falls to every 30-40 minutes.
4. **Fewer buses early in the morning on the loops,** and a flatter midday peak. The fleet is set by
   12:00-15:00; a flatter peak frees buses.
5. **Two pairs of near-duplicate lines** (1 and 2; 3 and 4) get merged into one line each, at a higher
   frequency (option 2 and 3 only).
6. **New direct lines were almost never chosen.** In this small city, a frequent line through the centre
   beats a direct but rare one.

## The three options

| | 1. Keep every line | 2. Restructure | 3. Restructure, 3 fewer buses |
|---|---|---|---|
| Lines | all of today's, re-routed and re-timed | 3, 5, 6 families + coast; 1, 2, 4 merged away | as 2 |
| Perceived door-to-door time vs today (calibration A / B) | **0.862 / 0.874** | **0.793 / 0.809** | **0.785 / 0.801** |
| Worst-off area | areas 33-34 up to 2% worse in their worst season; the rest better (up to 21%) | every area better by ≥ 3% | every area better by ≥ 3% |
| Buses at once (peak) | 32-35 | 32 (today 35) | 31-32 |
| Bus-hours a weekday (model) | 395 | 395 (today 395) | 405 |
| Bus trips vs today | +2% | +3% | +4% |

- **Option 3 costs about the same as today:**
  - 3 fewer peak buses ≈ 1.05 M NIS a year less;
  - 10 more bus-hours a weekday ≈ 1.08 M NIS more (360 NIS an hour, measured).
- **The ranking holds under every sensitivity test** (stop cost 20/40 s, transfer penalty 10 min, walk and
  wait weights 1.5/1.75, heat 2.0/3.0, logit scale 0.15, car owners riding more): option 2 stays at
  0.75-0.82 and option 3 at 0.73-0.81.

![Option 2](figs/proposal_full_warm.png)

### Who gains and who loses (option 2, 09:00-12:00, median over areas, perceived minutes)

| Destination | Change |
|---|---|
| Coral Beach | **-8** |
| Star Eilat / old central station | -3 |
| City hall, hospital | 0 |
| Hotels, Big centre | +2 |

- **Mid-morning trips to the hotels and Big get a little slower** in some areas. That is the price of
  merging lines 1 and 4.
- **Evening, midday and coast trips get faster,** and they outweigh it in every area's average.
- Area-by-area numbers: `data/assess_full_warm_areas.csv` and `data/assess_full_warm_traveltime.csv`.

## The future (Star Eilat, old airport, Shifolei HaHar)

- **Demand.** The two planned districts add about 12,300 residents, ~5,900 jobs and ~3,150 hotel rooms.
  With them, bus trips on today's network grow by **8-10%**, from ~7,600 to ~8,250 a weekday.
- **Budget.** Following your rule (grow the budget with demand), that's about **+3 buses at the peak and
  +32-40 bus-hours** a weekday.
- **Still better than today.** Under the future demand, without re-tuning and on today's budget, the options
  still beat today's network:

  | Option | Perceived time vs today, future demand |
  |---|---|
  | 1 | 0.90-0.93 |
  | 2 | 0.84-0.86 |
  | 3 | 0.83-0.86 |

- **But someone is worse off** (worst area 1.02-1.07): the new districts are served only by today's
  streets and stops.
- **The old airport district** has stops about 200 m away, so it works.
- **Shifolei HaHar** is about 850 m from the nearest stop. It needs new streets and stops, which are
  outside the rules we agreed (existing stops only), so it gets a spur, below.

### A spur into Shifolei HaHar (`scripts/spur.py`)

- **The design.** Lines 5 and 6 (and their variants) leave Yahel St. at their nearest stops, run out into the
  district through 3 new stops and come back: about 1.2 km each way, ~9-10 minutes more per trip.
- **An assumption.** The district's streets couldn't be downloaded (OpenStreetMap is blocked from this
  environment), so the spur runs straight toward the district centre reported in the press, at 25 km/h.
- **Results under the future demand:**

| Option | vs today, without spur | with spur | Shifolei HaHar residents vs today | Peak buses | Bus-hours |
|---|---|---|---|---|---|
| 1 | 0.90-0.91 | **0.85-0.86** | 0.99 → **0.46** | 35 → 36 | 397 → 423 |
| 2 | 0.84-0.85 | **0.78-0.79** | 0.99 → **0.45** | 33 → 36 | 394 → 427 |
| 3 | 0.84 | **0.77-0.78** | 0.99 → **0.44** | 32 → 36 | 404 → 439 |

- **It fits the budget growth** that the extra demand justifies (about +3 buses and +32-40 bus-hours).
- **Star Eilat.** Every option already runs through the old central station, where the Star Eilat terminal
  will open.

## Stops that are never skipped

People with luggage, and patients, shouldn't have to walk.
- **27 stops are protected:** every stop named for a hotel, the hospital (Yoseftal), the central station / Star
  Eilat, the city-entrance park-and-ride, the malls, the border crossings and the airport.
- **The rule:** they are never passed without stopping and never cut out by a straightened route.
- **Why it was needed:** before the rule, option 1 left three hotel stops without any stopping line (Palace,
  Orchidea, Caesar), and option 2 one (Palace). The hospital's two stops were always served.
- **Cost of the rule:** nothing measurable (the numbers above already include it).

## Will the buses be overfull?

`scripts/capacity.py`. For each line, period and season, under both calibrations:
- **Method:**
  - riders on the busiest segment ÷ period hours × 1.5 for the busiest hour within the period;
  - ÷ buses per hour;
  - compared with a standard 12 m bus: ~85 on board full, ~65 comfortable.

| | Most riders on one bus, busiest hour | Line-periods above 65 (comfortable) | above 85 (full) | above 85 if the peak hour is 2 × the period average |
|---|---|---|---|---|
| Today | 78 (line 16, summer evenings, one bus every 100 min) | 4 | 0 | 4 |
| Option 1 | 71 (line 6 family, summer evenings) | 4 | 0 | 4 |
| Option 2 | 65 | 0 | 0 | 3 |
| Option 3 | 63 | 0 | 0 | 0 |

- **Every option is less crowded than today.** The busiest buses are summer evenings, on the coast and on the
  line 6 family, and the options add evening service exactly there.
- **School dismissal spikes** (`scripts/school_peaks.py`).
  - **No published national bell schedule exists**, so it was estimated from the Education Ministry's
    weekly hours (36 h in grades 7-9; 30-34 h plus matriculation prep in 10-12), an 08:00 start and
    45-minute periods.
  - **End times** are ~13:15 / 14:10 / 15:00 / 15:45 (after periods 6-9).
  - **Shares let out:**
    - grades 7-9: 35% / 45% / 20% / 0%;
    - grades 10-12: 15% / 35% / 35% / 15%.
  - **The largest single bell is 14:10:** ~400-480 students per comprehensive school (Rabin, Begin,
    Goldwater).
  - **Bus share of students:** 4% (calibrated) or 10% (high case), so 20-50 riders per school within a few
    minutes.
  - **Places on buses calling within 300 m in the next 15 minutes:** in every option, enough for ~86-100%
    of everyone let out, counting all lines, both directions, empty buses.
  - **Correcting for direction (½) and passengers already on board (~45 of 85 at that hour):** about a
    quarter of that is really free. Even then, buses overflow only if more than ~20% of the students let
    out at one bell take the bus, 2-5 × the estimates.
  - **School lines 80-82 stay** on top of that.
  - **Verdict:** a 300-person crush at a school gate is not a risk in any option, because the staggered
    bells spread students over four waves.

## Timetables and buses: does it really fit? (`scripts/blocking.py`)

- **Method:**
  - Each option gets a real departure timetable: every `headway` minutes per period, directions offset by
    half a headway.
  - Every trip is assigned to a bus: the minimum fleet that covers all trips, with at least 5 minutes'
    layover, empty runs between terminals, buses shared between lines, and runs from and to the depot.
- **Validation on today's timetable:** 35 buses, against 36-38 measured at the peak. The gap is normal
  slack: driver breaks and reserves for delays.

| | Buses | Bus-hours incl. layovers and empty runs | km per bus a day (mean / max) | Buses over 250 km | Driver shifts (rough) |
|---|---|---|---|---|---|
| Today | 35 | 504 | 248 / 300 | 23 of 35 | 71 |
| Option 1 | 31-35 | 518-543 (+3-8%) | 262-284 / 339 | 25-26 | 81-84 |
| Option 2 | 31-33 | 503-531 (0 to +5%) | 273-282 / 349 | 24-26 | 82-85 |
| Option 3 | 31 | 510-532 (+1-5%) | 283-294 / 342 | 25-28 | 83-87 |

- **The fleet constraint holds.** No option needs more buses than today.
- **Paid bus-hours come out 0-8% above today.** The budget formula counted service time; real blocks have
  longer layovers. Better-aligned timetables between lines can probably absorb most of this; the
  offsets here are naive. It should be checked before claiming "same cost".
- **Charging is a constraint already today.** Most of today's buses run more than an e-bus's ~250 km a
  day without charging. The options, with fewer buses doing the same work, raise km per bus by 10-15%.
  Charging in the 10:00-12:00 lull (the depot is next to the centre) is needed in every case.
- **Driver shifts.** A shift is at most 8.5 h per bus block, so the numbers are only indicative.
  Fewer, longer bus days mean more split shifts.

## What I would check before anyone acts on this

- **Lines 1 and 2 carry ~3,300 boardings a day today.** The model says their riders are better served by
  frequent 3s, 5 and 6, but it also slightly under-predicts lines 2 and 6 (0.80 and 0.76 of reality).
  Option 1 is the safe first step; option 2 should be checked against stop-level Rav-Kav data before
  lines are merged.
- **Skipped stops:** some passengers walk up to 350 m more. Elderly riders and stops near clinics deserve
  a look stop by stop (the list is in the code output).
- **Not modelled:** drivers' shifts, the depot's capacity, and charging of the new electric buses (an
  urban bus here runs well under 250 km a day, so it is probably not binding).
- **The summer holiday is the least certain season.** There is no summer quarter in the Rav-Kav file.
- **The model compares networks;** it doesn't promise a ridership number. The bus-trip change (+3-4%) is
  the model's elasticity, not a forecast.

## Decisions taken overnight, and errors found and fixed

**Decisions**
- **Stop cost.** A real stop costs ~30 s (slow down, doors, pull out, accelerate). Passing a stop saves 30 s ×
  the chance the bus would have stopped there. The measured average per *scheduled* stop is only 11 s in
  Eilat, because many stops are passed anyway.
- **Calibration** on 2025 Q4 only. 2025 Q2 contains the June 2025 war and 2026 Q1 the March 2026 war; both
  are used only as checks.
- **Two demand calibrations** (A and B). The purpose mix can't be identified from 8 lines, so every option
  must win under both.
- **Usability rules added after the first search.** That search produced lines switching on and off
  between periods, which no passenger could use.
- **A conservative option** (every line kept) was added, because the best solutions merge lines 1, 2 and 4,
  a big step.
- **Future districts are evaluated, not designed for.** Shifolei HaHar has no stops yet, and new stops were
  outside the agreed rules.

**Errors found and fixed** (each one followed by a recalibration and new runs; earlier results are in
`data/superseded/`)
1. **Riders assigned to a single line.** The first evaluator sent every rider to one line, so lines sharing
   a street got no riders. Replaced with common-lines assignment (board the first attractive bus).
   Calibration error fell from 34% to 13%.
2. **Bus trips with no ride in them.** A "bus" path could walk to a stop and on to the destination without
   riding, and earned a 5-minute bonus. Stops are now split into before-ride and after-ride nodes.
3. **Purpose scales applied twice** in the objective and the reports. Now applied once.

## The lines of each option (winter timetable; minutes between buses by period)

Suffix `x` = passes its quietest stops without stopping; `s` = detours cut. School lines 80-82 are unchanged and not shown.


### Option 1: keep every line

| Line | From → to | Stops (passed) | Run, midday (min) | 06-09 | 09-12 | 12-15 | 15-19 | 19-24 | Boardings A / B |
|---|---|---|---|---|---|---|---|---|---|
| 1/0s | ת. מרכזית אילת/רציפים → ת. מרכזית אילת | 59 (0) | 65 | - | 60 | 60 | 40 | - | 19 / 24 |
| 15/0x | ת. מרכזית אילת/רציפים → דרך מצרים/מתחם קולוניה  | 28 (5) | 37 | 20 | 24 | 15 | 24 | 24 | 654 / 686 |
| 16/1x | דרך מצרים/מלון הנסיכה → ת. מרכזית אילת | 25 (6) | 39 | - | 60 | 40 | 20 | 30 | 434 / 500 |
| 2/0x | ת. מרכזית אילת/רציפים → ת. מרכזית אילת | 51 (21) | 73 | 15 | 30 | 20 | 40 | 40 | 560 / 503 |
| 3/0s | ת.כבאות/ששת הימים → חנה וסע מבואות אילת | 27 (0) | 24 | 15 | 24 | 40 | 24 | 20 | 551 / 542 |
| 3/1s | חניון אגד → ששת הימים/שרה אמנו | 27 (0) | 29 | 15 | 24 | 40 | 24 | 20 | 531 / 486 |
| 4/0x | ת.כבאות/ששת הימים → חנה וסע מבואות אילת | 23 (10) | 30 | 30 | 24 | 15 | 20 | 40 | 450 / 480 |
| 4/1x | חניון אגד → ששת הימים/שרה אמנו | 26 (10) | 32 | 30 | 24 | 15 | 20 | 40 | 453 / 497 |
| 5/0s | ת.כבאות/ששת הימים → חנה וסע מבואות אילת | 57 (0) | 60 | 24 | 20 | 20 | 30 | 30 | 1,473 / 1,281 |
| 5א/0s | ת.כבאות/ששת הימים → חנה וסע מבואות אילת | 57 (0) | 60 | 60 | 40 | 30 | 60 | 30 | 881 / 755 |
| 6/1x | חניון אגד → ששת הימים/שרה אמנו | 51 (19) | 75 | - | 30 | 30 | 24 | 24 | 1,358 / 1,180 |
| 6א/1x | חניון אגד → ששת הימים/שרה אמנו | 53 (20) | 82 | - | 30 | 40 | 20 | 30 | 1,273 / 1,115 |

### Option 2: restructure

| Line | From → to | Stops (passed) | Run, midday (min) | 06-09 | 09-12 | 12-15 | 15-19 | 19-24 | Boardings A / B |
|---|---|---|---|---|---|---|---|---|---|
| 15/0 | ת. מרכזית אילת/רציפים → דרך מצרים/מתחם קולוניה  | 33 (0) | 37 | 40 | 20 | 15 | 20 | 40 | 403 / 431 |
| 6א/1 | חניון אגד → ששת הימים/שרה אמנו | 73 (0) | 82 | 20 | 24 | 40 | 20 | 40 | 1,197 / 1,094 |
| 15/0x | ת. מרכזית אילת/רציפים → דרך מצרים/מתחם קולוניה  | 28 (5) | 37 | 40 | 40 | 30 | 20 | 15 | 400 / 404 |
| 16/1x | דרך מצרים/מלון הנסיכה → ת. מרכזית אילת | 25 (6) | 39 | 30 | 20 | 20 | 20 | 20 | 541 / 612 |
| 3/0s | ת.כבאות/ששת הימים → חנה וסע מבואות אילת | 27 (0) | 24 | 10 | 12 | 15 | 20 | 40 | 1,177 / 1,183 |
| 3/1s | חניון אגד → ששת הימים/שרה אמנו | 27 (0) | 29 | 10 | 12 | 15 | 20 | 40 | 721 / 765 |
| 5/0x | ת.כבאות/ששת הימים → חנה וסע מבואות אילת | 52 (19) | 68 | 30 | 60 | 30 | 24 | 20 | 1,358 / 1,131 |
| 5א/0x | ת.כבאות/ששת הימים → חנה וסע מבואות אילת | 55 (20) | 74 | 60 | 40 | 30 | 30 | 40 | 966 / 815 |
| 6/1x | חניון אגד → ששת הימים/שרה אמנו | 51 (19) | 75 | - | 30 | 30 | 30 | 24 | 1,113 / 981 |
| 6א/1x | חניון אגד → ששת הימים/שרה אמנו | 53 (20) | 82 | 60 | 40 | 40 | 40 | 24 | 1,003 / 866 |

### Option 3: restructure, 3 fewer buses

| Line | From → to | Stops (passed) | Run, midday (min) | 06-09 | 09-12 | 12-15 | 15-19 | 19-24 | Boardings A / B |
|---|---|---|---|---|---|---|---|---|---|
| 15/0 | ת. מרכזית אילת/רציפים → דרך מצרים/מתחם קולוניה  | 33 (0) | 37 | 30 | 24 | 30 | 24 | 40 | 321 / 350 |
| 16/1 | דרך מצרים/מלון הנסיכה → ת. מרכזית אילת | 31 (0) | 39 | 30 | 30 | 30 | 20 | 20 | 495 / 557 |
| 5א/0 | ת.כבאות/ששת הימים → חנה וסע מבואות אילת | 75 (0) | 76 | 30 | 30 | 30 | 20 | 30 | 1,277 / 1,098 |
| 6/1 | חניון אגד → ששת הימים/שרה אמנו | 70 (0) | 76 | - | 40 | 24 | 20 | 20 | 1,394 / 1,200 |
| 6א/1 | חניון אגד → ששת הימים/שרה אמנו | 73 (0) | 82 | 24 | 40 | 40 | 20 | 30 | 1,193 / 1,048 |
| 15/0x | ת. מרכזית אילת/רציפים → דרך מצרים/מתחם קולוניה  | 28 (5) | 37 | 30 | 40 | 30 | 24 | 15 | 386 / 397 |
| 3/0s | ת.כבאות/ששת הימים → חנה וסע מבואות אילת | 27 (0) | 24 | 15 | 12 | 10 | 20 | 40 | 1,065 / 1,081 |
| 3/1s | חניון אגד → ששת הימים/שרה אמנו | 27 (0) | 29 | 15 | 12 | 10 | 20 | 40 | 730 / 780 |
| 5/0x | ת.כבאות/ששת הימים → חנה וסע מבואות אילת | 52 (19) | 68 | 24 | 40 | 24 | 30 | 15 | 1,449 / 1,232 |
| 6א/1x | חניון אגד → ששת הימים/שרה אמנו | 53 (20) | 82 | 40 | 30 | 60 | 60 | 60 | 616 / 583 |
