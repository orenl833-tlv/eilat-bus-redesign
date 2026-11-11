"""The decision-makers' page (web/brief.html): fills web/brief_src.html with the route map of the recommended network (net_H), the
evening variants (data/evening.csv) and the example journeys (data/journeys.json).

Usage: python3 scripts/build_brief.py
"""
import csv
import json
import math

LAT0, LAT1, LON0, LON1 = 29.495, 29.585, 34.900, 34.985


def main():
    d = json.load(open("web/data.json"))
    S = d["stops"]
    k = math.cos(math.radians(29.55)); W = 600; H = round(W * (LAT1 - LAT0) / ((LON1 - LON0) * k))
    X = lambda lon: (lon - LON0) / (LON1 - LON0) * W  # noqa: E731
    Y = lambda lat: (LAT1 - lat) / (LAT1 - LAT0) * H  # noqa: E731
    routes, seen = [], set()
    for ln in d["lines"]["net_H"]["winter"]:
        if tuple(ln["stops"]) in seen:
            continue
        seen.add(tuple(ln["stops"]))
        routes.append("M" + " L".join(f"{X(S[i][1]):.0f},{Y(S[i][0]):.0f}" for i in ln["stops"]))
    sea = ["M" + " L".join(f"{X(x):.0f},{Y(y):.0f}" for x, y in r) + "Z" for r in d["sea"]]
    data = dict(W=W, H=H, routes=routes, sea=sea, journeys=json.load(open("data/journeys_tt.json")),
                evening=list(csv.DictReader(open("data/evening.csv"))))
    src = open("web/brief_src.html").read()
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    open("web/brief.html", "w").write(src.replace("/*DATA*/null", blob))


if __name__ == "__main__":
    main()
