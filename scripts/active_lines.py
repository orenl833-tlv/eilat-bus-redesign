"""How many lines run in each hour of a weekday, today and in each option, by season.

A line is active in an hour if at least one trip of it leaves in that hour. Lines are counted by their public
number: a variant (stops passed, route shortened) is the same line, so 5 and its variant count once; 5 and 5א
are two lines. School lines 80-82 are included (not in the summer holiday). Also: departures and buses out
per hour (a bus is out from its block's first departure to its last arrival).

Today's network is the real GTFS weekday of 10 Nov 2026 in every season (one timetable all year). The options run
to 23:00 plus the 5 shift-change trips (scripts/shift_trips.py); an option's
hours follow its period frequencies, so its curve steps at 06, 09, 12, 15 and 19.

Usage: PYTHONPATH=.:scripts python3 scripts/active_lines.py   Output: data/active_lines.csv, figs/active_lines.png
"""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

import blocking as BL  # noqa: E402
import shift_trips as SHT  # noqa: E402
from eilat import params as P  # noqa: E402
from export_page import public_name  # noqa: E402

OPTIONS = {"today": "Today", "net_H": "Recommended network"}
HOURS = range(5, 24)


def per_hour(trips, blocks):
    pub = trips.line.map(lambda x: public_name(x)[0])
    h = (trips.start // 60).astype(int)
    out = []
    for hr in HOURS:
        m = h == hr
        out.append(dict(hour=hr, lines=int(pub[m].nunique()), departures=int(m.sum()),
                        buses_out=sum(1 for b in blocks if b.start.min() < (hr + 1) * 60 and b.end.max() > hr * 60)))
    return pd.DataFrame(out)


def main():
    st = pd.read_csv("data/stops_all.csv").set_index("stop_id")
    rows = []
    for tag in OPTIONS:
        for se in P.SEASONS:
            if tag == "today":
                trips = BL.option_trips(tag, se, st)
            else:   # the recommended package: evening to 23:00 plus the shift-change trips
                x = SHT.shift_trips(BL.option_net(tag, se), SHT.hotel_stops())
                trips = pd.concat([BL.option_trips(tag, se, st, 23), x[x.o.isin(st.index) & x.d.isin(st.index)]], ignore_index=True)
            if tag == "today" and se == "summer":
                trips = trips[~trips.line.isin(BL.SCHOOL)]   # no school trips in the holiday
            _, _, blocks = BL.block(trips, st)
            d = per_hour(trips, blocks); d.insert(0, "season", se); d.insert(0, "option", tag)
            rows.append(d)
            print(tag, se, d.lines.tolist(), flush=True)
    D = pd.concat(rows, ignore_index=True)
    D.to_csv("data/active_lines.csv", index=False)
    plot(D)


def plot(D):
    fig, axs = plt.subplots(1, 3, figsize=(15, 4.2), sharey=True)
    for ax, se in zip(axs, P.SEASONS, strict=True):
        for tag, lab in OPTIONS.items():
            x = D[(D.option == tag) & (D.season == se)]
            x = pd.concat([x, x.tail(1).assign(hour=x.hour.max() + 1)])   # draw the last hour to its end
            ax.step(x.hour, x.lines, where="post", label=lab, lw=2.4 if tag == "today" else 1.6,
                    color="#444" if tag == "today" else None, ls="--" if tag == "today" else "-")
        ax.set_title(se.replace("_", " / ")); ax.set_xticks(range(6, 25, 3)); ax.set_xlabel("hour"); ax.grid(alpha=.3)
    axs[0].set_ylabel("lines running"); axs[0].legend(fontsize=8)
    fig.suptitle("Lines running in each hour of a weekday (at least one departure in the hour)")
    fig.tight_layout(); fig.savefig("figs/active_lines.png", dpi=120)


if __name__ == "__main__":
    main()
