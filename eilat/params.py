"""Every number the model uses, in one place, with where it comes from.

"Measured" = from our own data (SIRI, GTFS, ridership file, census). "Literature" = published values.
"Assumption" = my estimate, calibrated where the data allows and always tested in the sensitivity runs.
"""

# --- periods of a weekday (Israel time) ---
PERIODS = {  # name: (start hour, end hour)
    "06-09": (6, 9), "09-12": (9, 12), "12-15": (12, 15), "15-19": (15, 19), "19-24": (19, 24),
}

# --- how passengers perceive time (multiples of one in-vehicle minute) ---
W_INVEHICLE = 1.0
W_WALK = 1.6            # literature: Wardman et al. meta-analyses, 1.5-1.75 (the old convention of 2 is too high)
W_WAIT = 1.6            # literature: same range as walking
W_WALK_HEAT = 2.5       # assumption: walking 11:00-16:00 in the hot seasons; tested 2.0-3.0
TRANSFER_PENALTY = 5.0  # literature: bus-bus transfer ~4.5-5 min (Wardman et al. 2001; TU Delft 2024); tested 10
#                         the WAIT at a transfer is computed separately from the headway
WALK_KMH = 4.5          # literature: typical walking speed
DETOUR = 1.3            # assumption: street distance / straight line; tested 1.2-1.4
WALK_MAX_M = 800        # assumption: longest walk to/from a stop considered
TRANSFER_WALK_M = 300   # assumption: longest walk between two stops at a transfer

# --- bus operation ---
COST_PER_SERVICE_HOUR = 360   # measured: the ridership file's operating cost = exactly 360 NIS x service hours, every quarter
BUS_COST_PER_YEAR = 350_000   # assumption: e-bus 2.5-4 M NIS over 12-15 years + insurance, maintenance, depot (range 300-400k)
WEEKDAYS_PER_YEAR = 300
PEAK_BUS_IN_HOURS = BUS_COST_PER_YEAR / (COST_PER_SERVICE_HOUR * WEEKDAYS_PER_YEAR)  # ~3.2 service hours/day; tested 2-5
STOP_COST_S = 30              # measured+physics: one real stop (slow down, doors, pull out, accelerate) ~25-35 s in Eilat
STOP_COST_PER_SCHEDULED_S = 11  # measured (SIRI, Eilat): median 11 s per scheduled stop (IQR 7-16), many are passed without stopping
LAYOVER_SHARE, LAYOVER_MIN = 0.10, 5.0   # assumption: terminal layover per one-way trip = max(10% of run, 5 min)
EBUS_RANGE_KM = 250           # literature/assumption: daily range of an urban e-bus without midday charging

# --- budgets (school-term weekday, measured in SIRI; see FLEET.md) ---
PEAK_BUSES_MEASURED = 38
BUS_HOURS_MEASURED = 414

# --- demand: generation (one-way home-based tours per resident per weekday, all modes; scaled by calibration) ---
EMPLOYED_SHARE = 0.55   # measured-derived: census 2022, ~29-33k employed of 55k residents; 95% work in Eilat
SECONDARY_SHARE = 0.065 # measured-derived: ~3,600 secondary students (2015 school sizes) / 55k residents
TOUR_RATE = {"work": 0.85, "school": 0.95, "services": 0.45, "leisure": 0.25}  # assumption, then calibrated
CAR_PROPENSITY = 0.2    # assumption, calibrated: bus use of residents in car-owning households / car-less ones

# --- tourism ---
HOTEL_ROOMS = 11_500     # press reports 11,000-12,000
GUESTS_PER_ROOM = 2.0    # assumption
OCCUPANCY = {"winter": 0.65, "spring_autumn": 0.72, "summer": 0.85}  # assumption: Eilat leads national occupancy; summer = Israeli holiday peak
TOURIST_TOUR_RATE = 0.8  # assumption: outings from the hotel per guest per day, all modes

# --- mode choice (bus vs walking / car) ---
LOGIT_SCALE = 0.12       # literature range 0.05-0.2 per perceived minute; tested
BUS_CONSTANT = 0.0       # calibrated with the heat factor

# --- seasons (one network, frequencies by season) ---
SEASONS = {  # months per year, school in session, hot middays
    "winter": dict(months=5, school=True, hot=False),         # Nov-Mar
    "spring_autumn": dict(months=5, school=True, hot=True),   # Apr-Jun, Sep-Oct
    "summer": dict(months=2, school=False, hot=True),         # Jul-Aug, the long school holiday
}

# --- objective ---
NOCAR_EQUITY_WEIGHT = 1.5   # agreed: a minute of a car-less resident counts 1.5x
MAX_AREA_LOSS = 0.10        # agreed: no residential area worse off by more than 10%
COVERAGE_STOP_M = 500       # agreed: every residential area keeps a stop within ~500 m ...
COVERAGE_HEADWAY_MIN = 30   # ... with a bus at least every 30 minutes in daytime
