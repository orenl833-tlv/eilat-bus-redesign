# For the next re-run (agreed, not yet run)

- **New lines' delays (done in code):** lines with no history of their own (7-9) now draw delays from the late half of
  today's lines, not the all-lines average (`eilat/timetable.py` DelaySampler; `NEW_LINE_DELAY=all` restores the old pool).
- **Campus:** about 80 staff instead of 300 jobs. Add students: 700-800 enrolled, about 450-500 on campus on a weekday.
  - 10-30% live in the campus dorms and walk to class. The rest live across the city, by population.
  - Arrive 06-09 25%, 09-12 30%, 12-15 15%, 15-19 25%, 19-24 5%. Leave 09-12 10%, 12-15 30%, 15-19 30%, 19-24 30%.
  - Some dorm residents work in the city (hotels, restaurants): add work trips from the dorms to the hotels and centre.
- **Demand robustness:** re-score net_F2 against today with perturbed attractor sizes (e.g. hotel jobs +-50%), a flat
  PROFILE and other BETA values, not only new leaving times and delays.
- Keep the 2-min transfer time.

# Route checks done (OSM roads, OSRM car routing; streets assumed wide enough for a bus)
- The 9 stop-to-stop links not driven today are direct on main streets (4-30% longer than straight): `data/new_links_osrm.json`.
- Every end of lines 7-9 has a legal turnaround without a U-turn, 243-605 m around a block: `data/new_terminals_osrm.json`.
- Still for the operator: a layover spot at each end. Common practice (NZTA, Transport for NSW guidance): kerb space
  away from the stop itself, for one bus at a time here (layover shorter than the headway), sized on site by
  swept-path analysis, with driver facilities (toilet) nearby.

## Links
- Repository linked from the map page and the brief (done).
- When the LinkedIn post is published: link it from the map page (web/eilat.html footer) and the README, and republish the map.
