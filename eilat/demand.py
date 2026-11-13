"""Who travels where and when: potential trips (all modes) by purpose, period and season, then the bus share.

Residents (by statistical area, sample points) make home-based tours for work, school, services and leisure;
hotel guests make outings. Destinations are chosen by a gravity model on distance (so destination choice
doesn't depend on the bus network). The bus share then depends on the bus vs walking perceived time (logit)
and on car ownership. Every tour is an outbound trip in one period and a return trip in a later one.
"""
from __future__ import annotations

import os

import geopandas as gpd
import numpy as np
import pandas as pd

from . import params as P
from .evaluate import walk_min

# attractor points, anchored on bus stops near them; "jobs" etc. are sizes for the gravity model (assumptions,
# see ATTRACTORS.md / PARAMETERS.md); the calibration scales each purpose as a whole
ATTRACTORS = pd.DataFrame([
    # name,                       lat,     lon,     jobs, school, services, leisure, tourist
    ("City hall / centre",        29.5561, 34.9520, 3500, 0,    3.0, 1.0, 1.0),
    ("Old central station (Star Eilat)", 29.5577, 34.9536, 300, 0, 1.0, 0.5, 0.5),
    ("Hotels, North Beach",       29.5535, 34.9625, 6000, 0,    0.3, 2.5, 0.0),
    ("Ice Mall",                  29.5549, 34.9661, 900,  0,    1.5, 1.5, 1.0),
    ("Mall HaYam",                29.5511, 34.9550, 700,  0,    1.5, 1.0, 1.0),
    ("Big centre",                29.5677, 34.9596, 1500, 0,    2.5, 0.3, 0.3),
    ("Industrial zone / depot",   29.5742, 34.9612, 1500, 0,    0.5, 0.0, 0.0),
    ("Yoseftal hospital",         29.5549, 34.9401, 900,  0,    1.5, 0.0, 0.0),
    ("Eilat campus",              29.5665, 34.9522, 80,   0,    0.3, 0.0, 0.0),
    ("Rabin high school",         29.5534, 34.9358, 90,   1191, 0.0, 0.0, 0.0),
    ("Begin high school",         29.5622, 34.9379, 90,   1084, 0.0, 0.0, 0.0),
    ("Goldwater high school",     29.5536, 34.9481, 90,   1067, 0.0, 0.0, 0.0),
    ("Coral Beach",               29.5082, 34.9207, 800,  0,    0.0, 1.5, 3.0),
    ("Taba / Princess",           29.4959, 34.9075, 900,  0,    0.0, 0.3, 1.0),
    ("Port",                      29.5355, 34.9404, 600,  0,    0.0, 0.0, 0.0),
    ("City entrance terminal",    29.5713, 34.9623, 100,  0,    0.3, 0.0, 0.3),
], columns=["name", "lat", "lon", "jobs", "school", "services", "leisure", "tourist"])
# robustness: DEMAND_PERTURB=<seed> multiplies every attractor's jobs, services, leisure and tourist size by its own
# random factor between 0.5 and 1.5 (school sizes are enrolment, kept), to test results not fitted to these guesses
if os.environ.get("DEMAND_PERTURB"):
    _rng = np.random.default_rng(int(os.environ["DEMAND_PERTURB"]))
    for _c in ("jobs", "services", "leisure", "tourist"):
        ATTRACTORS[_c] = ATTRACTORS[_c] * _rng.uniform(0.5, 1.5, len(ATTRACTORS))

# share of a purpose's daily outbound / return trips in each period (assumptions; school from bell times,
# work from hotel shifts 07/15/23 and office hours, tourists from beach and evening habits)
PROFILE = {
    "work":     dict(out=[.55, .10, .20, .10, .05], back=[.02, .05, .25, .38, .30]),
    "school":   dict(out=[.95, .05, 0, 0, 0],       back=[0, 0, .65, .35, 0]),
    "services": dict(out=[.10, .40, .15, .25, .10], back=[.02, .20, .30, .30, .18]),
    "leisure":  dict(out=[0, .20, .15, .35, .30],   back=[0, 0, .10, .30, .60]),
    "tourist":  dict(out=[.05, .40, .20, .20, .15], back=[0, .05, .20, .40, .35]),
}
BETA = {"work": 0.15, "school": 0.25, "services": 0.30, "leisure": 0.20, "tourist": 0.15}  # per km (assumption)
PURPOSES = list(PROFILE)
HOTEL = "Hotels, North Beach"
# beaches draw far more leisure and tourist outings in the summer than malls and the centre do
BEACHES = ("Hotels, North Beach", "Coral Beach", "Taba / Princess")
# students of the Eilat campus, kept apart from PURPOSES (no ridership to calibrate them on): two waves, as many
# students work (assumption); no classes in the long summer holiday
UNI_PROFILE = dict(out=[.25, .30, .15, .25, .05], back=[0, .10, .30, .30, .30])
CAMPUS = "Eilat campus"


def uni_tours(pop, season):
    """Student tours to the campus per day (all modes) from each home point, by population; dorm residents walk."""
    if not P.SEASONS[season]["school"] or DAY == "saturday":
        return np.zeros(len(pop))
    n = P.UNI_STUDENTS * P.UNI_ATTEND * (1 - P.UNI_DORM_SHARE) * (0.2 if DAY == "friday" else 1.0)
    return n * pop / pop.sum()


def dorm_tours(season):
    """Tours per day from the campus dorms (all modes, residents mostly car-less) to each attractor, by purpose:
    jobs in the city (hotels, restaurants, shops), and outings to restaurants, malls and the beach like other
    residents. Dorms are taken as empty in the long summer holiday."""
    att = ATTRACTORS
    c = att.index[att.name == CAMPUS][0]
    n = P.UNI_STUDENTS * P.UNI_DORM_SHARE * (1 if P.SEASONS[season]["school"] else 0)
    dk = walk_min(att.lat[c], att.lon[c], att.lat.values, att.lon.values) * (P.WALK_KMH * 1000 / 60) / P.DETOUR / 1000
    gen = {"work": n * P.UNI_DORM_WORK, "services": n * P.TOUR_RATE["services"], "leisure": n * P.TOUR_RATE["leisure"]}
    size = {"work": att.jobs.values, "services": att.services.values, "leisure": att.leisure.values}
    out = {}
    for p, g in gen.items():
        w = size[p] * np.exp(-BETA[p] * dk); w[c] = 0
        out[p] = g * DAY_FACTORS[DAY][p] * w / w.sum()
    return out, c


def areas(n_points=6):
    a = gpd.read_file("data/areas.geojson")
    a = a[a.use == "מגורים"].copy()
    # area 16's population is published with 15 (CBS): split 15+16 by area
    tot = a.loc[a.stat11 == 15, "pop2020"].sum()
    ar = a.to_crs(2039).geometry.area
    s15, s16 = ar[a.stat11 == 15].sum(), ar[a.stat11 == 16].sum()
    a.loc[a.stat11 == 15, "pop2020"] = tot * s15 / (s15 + s16)
    a.loc[a.stat11 == 16, "pop2020"] = tot * s16 / (s15 + s16)
    a["pop"] = a.pop2020 * 55_210 / a.pop2020.sum()   # scale 2020 polygons to the 2022 census total
    a["nocar"] = a.Vehicle0_pcnt / 100
    rows = []
    for r in a.itertuples():
        pts = gpd.GeoSeries([r.geometry], crs=a.crs).sample_points(n_points, rng=int(r.stat11)).iloc[0]
        for p in pts.geoms:
            rows.append(dict(kind="home", area=int(r.stat11), lat=p.y, lon=p.x, pop=r.pop / n_points, nocar=r.nocar))
    return a, pd.DataFrame(rows)


# future scenario (EILAT_FUTURE=1): planned districts from the master plan and land tenders (press, see FUTURE notes)
FUTURE_HOMES = [  # area code, name, lat, lon, residents (units x 2.4), share of households without a car (assumption)
    (901, "Old airport district", 29.5620, 34.9590, 2469 * 2.4, 0.25),
    (902, "Shifolei HaHar (north-west)", 29.5680, 34.9260, 2680 * 2.4, 0.10),
]
FUTURE_JOBS = ("Old airport district", 29.5620, 34.9590, 5900, 0, 3.0, 1.0, 0.5)  # 88k m2 offices + 95k m2 retail
FUTURE_ROOMS = 2776 + 373


def future():
    import os
    return os.environ.get("EILAT_FUTURE") == "1"


def points():
    """All trip ends: home sample points, then attractors."""
    global ATTRACTORS
    a, homes = areas()
    if future():
        rng = np.random.default_rng(9)
        extra = []
        for code, _, lat, lon, pop, nc in FUTURE_HOMES:
            for _ in range(6):
                extra.append(dict(kind="home", area=code, lat=lat + rng.normal(0, .002), lon=lon + rng.normal(0, .002),
                                  pop=pop / 6, nocar=nc))
        homes = pd.concat([homes, pd.DataFrame(extra)], ignore_index=True)
        if FUTURE_JOBS[0] not in set(ATTRACTORS.name):
            ATTRACTORS = pd.concat([ATTRACTORS, pd.DataFrame([FUTURE_JOBS], columns=ATTRACTORS.columns)], ignore_index=True)
            P.HOTEL_ROOMS = 11_500 + FUTURE_ROOMS
    att = ATTRACTORS.assign(kind="attractor", area=-1, pop=0.0, nocar=np.nan)
    pts = pd.concat([homes, att[["kind", "area", "lat", "lon", "pop", "nocar", "name"]]], ignore_index=True)
    return a, pts


# day type: weekday (default), friday, saturday. Multipliers on each purpose's tours (assumptions, then one
# weekend scale is calibrated on weekly minus 5 x daily boardings per line)
DAY = "weekday"
DAY_FACTORS = {
    "weekday": dict(work=1.0, school=1.0, services=1.0, leisure=1.0, tourist=1.0),
    "friday": dict(work=0.45, school=0.5, services=1.2, leisure=1.3, tourist=1.2),
    "saturday": dict(work=0.3, school=0.0, services=0.5, leisure=1.5, tourist=1.3),
}


def potential(pts, season, rates=None, car_prop=P.CAR_PROPENSITY):
    """Outbound tours per day (all modes) for each purpose: dict purpose -> (homes x attractors) array, plus the
    weight of car-less travellers. Tourist outings start at the hotel point."""
    rates = rates or P.TOUR_RATE
    cfg = P.SEASONS[season]
    homes = pts[pts.kind == "home"]; att = ATTRACTORS
    d_km = walk_min(homes.lat.values[:, None], homes.lon.values[:, None], att.lat.values[None, :],
                    att.lon.values[None, :]) * (P.WALK_KMH * 1000 / 60) / P.DETOUR / 1000
    pop = homes["pop"].values; nocar = homes.nocar.values
    gen = {"work": pop * P.EMPLOYED_SHARE * rates["work"],
           "school": pop * P.SECONDARY_SHARE * rates["school"] * (1 if cfg["school"] else 0),
           "services": pop * rates["services"], "leisure": pop * rates["leisure"] * (1.5 if season == "summer" else 1.0)}
    beach = np.where(att.name.isin(BEACHES), P.SUMMER_BEACH if season == "summer" else 1.0, 1.0)
    size = {"work": att.jobs.values, "school": att.school.values, "services": att.services.values,
            "leisure": att.leisure.values * beach}
    f = DAY_FACTORS[DAY]
    gen = {p: g * f[p] for p, g in gen.items()}
    out = {}
    for p, g in gen.items():
        w = size[p][None, :] * np.exp(-BETA[p] * d_km)
        w = w / np.maximum(w.sum(axis=1, keepdims=True), 1e-12)
        out[p] = g[:, None] * w
    # people in car-owning households ride less: weight per home point
    prop = nocar + car_prop * (1 - nocar)
    guests = P.HOTEL_ROOMS * P.OCCUPANCY[season] * P.GUESTS_PER_ROOM * P.TOURIST_TOUR_RATE
    hotel = att.index[att.name == HOTEL][0]
    dk = walk_min(att.lat[hotel], att.lon[hotel], att.lat.values, att.lon.values) * (P.WALK_KMH * 1000 / 60) / P.DETOUR / 1000
    tw = att.tourist.values * beach * np.exp(-BETA["tourist"] * dk); tw[hotel] = 0
    tour = guests * tw / tw.sum() * f["tourist"]
    return out, prop, tour, hotel
