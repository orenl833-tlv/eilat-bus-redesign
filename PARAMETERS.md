# Every number the model uses, and how it was checked

The values live in `eilat/params.py`; this page says where each comes from. **Measured** = from our own
data. **Literature** = published values. **Assumption** = my estimate. Every assumption is either calibrated
against real ridership or varied in the sensitivity runs, which re-evaluate the proposals.

## Time as passengers feel it (in minutes on board)

| What | Value | Source | Tested |
|---|---|---|---|
| A minute on the bus | 1 | definition | |
| A minute walking | 1.6 | Literature: Wardman et al. meta-analyses (UK 2011, multi-country 2026) recommend 1.5-1.75; the old convention of 2 is now considered too high | 1.5, 1.75 |
| A minute waiting | 1.6 | Literature: same range | 1.5, 1.75 |
| Waiting time itself | half the headway (or of the combined headway where several lines serve the same trip) | standard for passengers who don't time their arrival; checked against the timetable-based calculation (ACCESS.md) | |
| A minute walking 12:00-15:00 in the hot seasons | 2.5 | **Assumption**: no published value for desert heat | 2.0, 3.0 |
| A transfer | +5 minutes, plus the real wait for the second bus | Literature: bus-bus transfer ~4.5-5 min (Wardman, Hine and Stradling 2001; TU Delft 2024); planning range 5-15 | 10 |
| Real wait at a transfer in Eilat | ~10 min on average (most lines run every 20 min) | **Measured**: GTFS headways | |
| Walking speed, detour | 4.5 km/h; streets 1.3 × straight line | literature / assumption | |

## Stops

| What | Value | Source |
|---|---|---|
| Average cost of a **scheduled** stop (including stops passed without stopping) | **11 s** in Eilat (IQR 7-16); 33 s nationally (95% CI 30-36) | **Measured**: SIRI speeds of 2,990 Eilat rides; regression on 1,351 urban line-directions nationwide (R² 0.91) |
| Cost of a **real** stop (slow down, doors, pull out, accelerate) | **30 s** (range 25-35) | physics at the measured 32 km/h cruise (about 8 s of deceleration and acceleration) + doors and pulling out (5-15 s) + boarding; consistent with the national figure |
| Saving from passing a stop without stopping | 30 s × the chance the bus would have stopped there (from the model's boardings at that stop) | tested 20 s and 40 s |

You were right that a real stop costs more than its dwell. But a quiet stop saves less to skip, because the
bus often passes it anyway. The model accounts for both.

## Real running times

- Real trips take 1.24 × the planned time (median). On the south-coast lines 15 and 16 it's 1.5-1.7 ×.
  **Measured**: SIRI against GTFS, 7 school-term weekdays.
- The ridership file's trip durations agree with SIRI, not with the timetable.
- Every line, existing or new, runs at the measured speed of its streets and period.

## Cost of service

| What | Value | Source |
|---|---|---|
| An hour of bus service | 360 NIS | **Measured**: the ridership file computes operating cost as exactly 360 NIS × service hours, for every line and quarter |
| An extra bus needed at the peak | ~350k NIS/year: e-bus 2.5-4 M NIS over 12-15 years, plus insurance, maintenance, depot | **Assumption**, from press prices (a diesel bus ~2 M; an e-bus about double) |
| So one peak bus ≈ | 3.2 hours of service every weekday | ratio of the two above; tested 2-5 |

## Budget (today's network, same formula for every proposal)

- **Model:** 35 buses at once at the peak (12:00-15:00) and 395 bus-hours on a weekday.
- **Measured (SIRI):** 36-38 buses and 414 bus-hours. The measurement includes layovers of up to 20 minutes.
- A proposal must not exceed today's values as computed by the **same model formula**.

## Demand

- **Residents:**
  - 55,210 in the 2022 census, spread over the 2011 statistical areas by their 2020 population;
  - households without a car per area from the 2022 census;
  - employed ≈ 55% of residents (census: ~29-33k);
  - secondary students ≈ 6.5% of residents (2015 school sizes).
- **Attractor sizes** (jobs, school places, relative pull for services, leisure and tourists): assumptions in
  `eilat/demand.py`; the calibration scales each purpose.
- **Tourists:** 11,500 rooms × 2 guests × occupancy (winter 65%, spring/autumn 72%, summer 85%) × 0.8 outings
  a day.
- **Calibration** on 2025 Q4 boardings per line (the cleanest quarter):
  - **Fit:** error 13% per line.
  - **Out of sample:** 2026 Q1 error 13%; 2025 Q2 total within 1%.
  - **Purposes can't be separated** from 8 lines, so two versions are kept:
    - A: data-fitted, with no tourists on the bus;
    - B: leaning on the prior mix (38% work, 28% services, 23% leisure, 9% tourists, 2% school; line error 27%).
  - Proposals are scored on both.

## Decisions agreed

| Decision | Value |
|---|---|
| Car-less residents' minutes | count 1.5 × |
| No area worse off by more than | 10% |
| Coverage | every area keeps a stop within ~500 m with a bus every ≤ 30 min in daytime (or at least today's level) |
| Network | one network with frequencies by season: winter (Nov-Mar), spring/autumn (Apr-Jun, Sep-Oct), summer holiday (Jul-Aug) |
| Stops | existing stops only |
| School lines 80-82 | unchanged |
| Weekends | not redesigned |
| Hub | the Star Eilat terminal at the old central station (opening 2027) |
