# Eilat: demand model inputs (draft for review)

Goal: propose a better urban bus network for Eilat with the same fleet (maximum buses running at once)
and the same total vehicle-hours. This file covers the demand side: who travels, to where, when, and
how much each attractor weighs. Nothing has been computed on the network yet.

## Data found (steps 1-3)

| What | Source | What it gives | Status |
|---|---|---|---|
| **Ridership per line** | data.gov.il `ridership` (National Public Transport Authority clearing house, Rav-Kav validations) | Daily and weekly boardings per line and direction, per quarter: 2022 Q4, 2023 Q1-Q2, 2024 Q1-Q2-Q4, 2025 Q2-Q4, 2026 Q1. Also run time, speed, trips/day, cost per passenger | `data/ridership_eilat.csv` |
| Population by statistical area | CBS census 2022 (data.gov.il `2022`) | 17 areas: population, age, **share of households without a car**, employment, work outside the city | `data/census2022_eilat.csv` |
| Schools, active now | Education Ministry `mosdot_edu` (Oct 2026) | 21 active schools with location | `data/mosdot_now_eilat.csv` |
| School sizes | Education Ministry `mosdot` (last year published: 2015) | Students per school | `data/schools_eilat.csv` |
| Depot | GTFS stop 50286 "חניון אגד" | 29.5742 N, 34.9612 E, northern industrial area; first stop of lines 3, 4, 6 | confirmed |
| Network, timetable | GTFS 7 Nov 2026 | Routes, stops, trips | `data/raw/gtfs_20261107` (not committed, 900 MB) |
| Actual run times, fleet in use | Open Bus Stride SIRI | Vehicles running at once, vehicle-hours, segment speeds | to fetch |
| Cellular trip matrices 2018-19 | data.gov.il `tripscelular_1819` | All-mode trips between 1,270 national zones, trips over 1.5 km | not yet checked: may have only a few zones in Eilat |
| Hotels | press, Hotel Association | ~11,000-12,000 rooms; ~8,000 hotel workers (2020); ~2,000-2,500 Jordanian daily workers | rough, to verify against CBS hotel tables |

**The ridership file changes the approach:** the weights do not have to stay guesses. A demand model
assigned to today's network predicts boardings per line; these can be compared with the real boardings
of 23 line-directions over 9 quarters, and the weights fitted. Guesses become starting values.

## What the data already says

- **Total: about 10,400 boardings a day** on Eilat lines in 2026 Q1, up from 7,600 in 2022 Q4.
- **Four long loops carry two thirds of it.** Lines 1, 2, 5, 6 (23-26 km, 60-70 minutes per trip) have
  1,500-1,750 boardings a day each; the short lines 3 and 4 have 400-540 per direction.
- **Line 30 to Ramon airport: ~720 a day.** The airport is a major attractor that was missing from the list.
- **South coast (lines 15, 16, toward Taba): ~670 a day in winter** (Q1). There is no summer quarter in the
  file (no Q3 in any year), so summer beach demand must come from tourism statistics.
- **School lines 80-82: ~190 a day.** Most students who ride use the regular lines.
- **Night lines 10, 11: about 2 boardings a night.** So late-night hotel shifts are probably served by
  employer shuttles, not by city buses. This lowers the weight of hotel night shifts.
- **The city is closed:** only 5% of employed residents work outside Eilat (census).
- **Car ownership varies 7×:** households without a car range from 8% to 56% between statistical
  areas (which areas are where still has to be mapped). This is probably the strongest single predictor of where riders
  come from, stronger than population.
- **The network changed recently:** in the Nov 2026 GTFS, lines 3-6 run between the depot / fire
  station and a park-and-ride terminal at the city entrance (חנה וסע מבואות אילת). The old central
  station is a construction site (Star Eilat, opening planned for 2027). The ridership quarters reflect
  older layouts, so line-by-line comparisons have to use the timetable of each quarter.

## Attractors, revised

The weight of an attractor = its size × trips it generates per unit × the share of those trips made by
bus. The last factor matters most and differs a lot between groups.

| # | Attractor | Size measure | Bus share (assumption) | Time profile | Season | Starting weight |
|---|---|---|---|---|---|---|
| 1 | **Residential areas** (origin) | population × (1 + k × no-car share) | high where no car | out 06:30-09:00, back 13:00-19:00 | flat | **highest** (~60-70% of all boardings) |
| 2 | **Secondary schools** (4 comprehensives, ~1,000-1,200 each) | students in grades 7-12 | medium, higher in summer heat | in 07:15-08:00; out staggered 12:30-16:00 by grade | Sep-Jun, school days | **high**, concentrated in time |
| 3 | Primary schools (~14, 120-500 each) | students | low (walk, parents) | 07:30-08:00, 12:00-14:00 | Sep-Jun | low |
| 4 | **City centre and services**: municipality, National Insurance, banks, post, clinics | staff + visits | medium; elderly ride more | 08:00-13:00 weekdays | flat | medium |
| 5 | **Shopping**: Big centre (industrial zone), malls by the North Beach, the old centre | retail floor area | medium for residents, high for tourists without a car | 10:00-21:00 | rises with tourism | medium-high |
| 6 | **Hotel strip, North Beach**: as origin (guests) and destination (workers) | rooms × occupancy; workers | guests low-medium; workers high but partly employer shuttles | workers 06:00-07:00, 14:00-15:00; guests 09:00-23:00 | guests: summer and holidays (Israelis), winter (foreigners) | **high** |
| 7 | **South coast**: Coral Beach reserve, Dolphin Reef, Underwater Observatory, diving centres, hotels toward Taba | visitors (tourism stats) | high: 5-10 km from hotels, little parking | 09:00-18:00 out, sunset back | strong summer peak | **high in summer**, medium in winter |
| 8 | **Ramon airport** (18 km north) | flights × passengers | high for tourists without a car | follows the flight schedule | holidays, winter charters | **medium-high** (~720 a day today) |
| 9 | **City entrance / park-and-ride / intercity terminal** | intercity arrivals | high (arrivals without a car) | Sun morning, Thu-Fri afternoon | holidays | medium |
| 10 | Hospital (Yoseftal) | beds, outpatient visits | medium-high (elderly, no car) | 07:30-14:00 | flat | medium |
| 11 | Higher education: university campus, teacher training | students | high (young, no car) | 08:00-18:00 | academic year | low-medium |
| 12 | Industrial zone and port: jobs other than hotels | employees | low-medium | 06:30-08:00, 15:00-17:30 | flat | low-medium |
| 13 | Youth and leisure: community centres, sports, pools, country club | members | medium (teens without a licence) | 14:00-20:00 | school year; summer camps | low-medium |
| 14 | Army: soldiers' home, the Navy base | soldiers | high, but mostly intercity | Sunday morning, Thursday | flat | low for the urban network |
| 15 | Border crossings: Taba (Egypt), Yitzhak Rabin / Arava (Jordan) | crossings | Taba: tourists; Arava: daily Jordanian hotel workers, probably on employer buses | morning and evening | holidays | low |
| 16 | Evening leisure: promenade, restaurants, bars | seats / floor area | medium for tourists, low for residents | 19:00-24:00 | tourism | medium in the evening |

New compared with the first list: the airport (8), the city-entrance terminal (9), shopping as its
own category (5), army (14), border crossings (15), evening leisure (16), youth (13), and car
ownership as the main modifier of residential demand.

## Where the assumptions are weakest

1. **Hotel workers.** About 8,000 workers is a big number, but the night lines carry almost no one. Many
   probably use employer shuttles or live in staff housing near the hotels. The model should let the
   data decide: if workers rode city buses, the morning lines to the hotel strip would show it.
2. **Tourists' bus share.** Israeli tourists mostly arrive by car; foreign tourists mostly don't. The
   share of each changes by season. The winter quarters (Q1, Q4) against Q2 will help here, but there
   is no summer quarter.
3. **School sizes** are from 2015. Total students can be scaled by population growth, and the new
   Ariel Sharon high school has no count.
4. **Saturday service** in Eilat needs checking from the SIRI data before building weekly totals.

## Calibration plan

- Free parameters: one bus-share factor per group (residents by car ownership, students, tourists,
  workers, airport) and one distance-decay parameter: about 6-8 numbers.
- Targets: boardings per line and direction, per quarter (23 × 9 values), plus the totals.
- If the fit is poor for a line, that points to a missing attractor or a wrong assumption, which is
  itself a finding.
