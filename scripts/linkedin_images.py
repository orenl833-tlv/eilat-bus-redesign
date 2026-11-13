"""The LinkedIn post's two images, as HTML pages from web/data.json (rendered to PNG by scripts/linkedin_shot.js).

1. linkedin/1_network.html: today's lines next to the proposal's (net_F2, winter), school lines left out.
2. linkedin/2_areas.html: each residential area coloured by its change in door-to-door time (year average).

Usage: python3 scripts/linkedin_images.py && node scripts/linkedin_shot.js
"""
import json

D = json.load(open("web/data.json"))
OPT = "net_F2"
import math
LAT = (29.537, 29.575)     # city, without the coast road to Taba
LON = (34.915, 34.968)
W = 540
H = round(W * (LAT[1] - LAT[0]) / ((LON[1] - LON[0]) * math.cos(math.radians(29.556))))  # true scale
PAL = ["#0f766e", "#2563eb", "#d97706", "#7c3aed", "#db2777", "#059669", "#0891b2", "#b45309", "#4f46e5", "#be123c"]


def xy(lat, lon):
    return (lon - LON[0]) / (LON[1] - LON[0]) * W, (LAT[1] - lat) / (LAT[1] - LAT[0]) * H


def path(pts):
    return "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)


def base():
    s = "".join(f'<path d="{path([xy(la, lo) for lo, la in r])}Z" class="land"/>' for r in D["land"])
    s += "".join(f'<path d="{path([xy(la, lo) for lo, la in r])}Z" class="sea"/>' for r in D["sea"])
    return s


def lines_svg(tag):
    ls = [l for l in D["lines"][tag]["winter"] if not l["line"].startswith("8") and any(l["hw"].values())]
    names = sorted({l["display"] for l in ls}, key=lambda n: (len(n), n))
    col = {n: PAL[k % len(PAL)] for k, n in enumerate(names)}
    s = ""
    for l in ls:
        pts = [xy(*D["stops"][i][:2]) for i in l["stops"]]
        s += f'<path d="{path(pts)}" stroke="{col[l["display"]]}" class="ln"/>'
    return s, len(names)


def areas_svg(fill):
    s = ""
    for a in D["areas"]:
        for r in a["rings"]:
            s += f'<path d="{path([xy(la, lo) for lo, la in r])}Z" fill="{fill(a)}" class="area"/>'
    return s


CSS = """
body{margin:0;background:#f6f3ec;font-family:'Assistant','Noto Sans Hebrew',Arial,sans-serif;color:#1f2933}
.card{width:1200px;box-sizing:border-box;padding:44px 48px;direction:rtl}
h1{font-size:46px;margin:0 0 10px;line-height:1.15} p.sub{font-size:24px;margin:0 0 26px;color:#52606d}
.maps{display:flex;gap:28px;justify-content:center} figure{margin:0;text-align:center}
figcaption{font-size:30px;font-weight:700;margin-bottom:8px} figcaption span{font-weight:400;color:#52606d;font-size:22px}
svg{background:#d6e6ee;border-radius:14px;display:block}
.land{fill:#f1ede4;stroke:#d9d2c3} .sea{fill:#d6e6ee} .ln{fill:none;stroke-width:6.5;stroke-linejoin:round;stroke-linecap:round;opacity:.85}
.area{stroke:#fff;stroke-width:1.2} .lbl{font-size:13px;font-weight:700;fill:#1f2933;paint-order:stroke;stroke:#fff;stroke-width:4px}
.foot{font-size:20px;color:#52606d;margin-top:18px} .leg{display:flex;gap:22px;font-size:22px;margin-top:16px;justify-content:center}
.leg i{display:inline-block;width:26px;height:18px;border-radius:4px;margin-left:8px;vertical-align:middle}
"""


def page(body):
    return (f'<!doctype html><html lang="he"><head><meta charset="utf-8"><link href="https://fonts.googleapis.com/css2?'
            f'family=Assistant:wght@400;700&display=swap" rel="stylesheet"><style>{CSS}</style></head><body><div class="card" id="card">'
            f'{body}</div></body></html>')


def main():
    lt, nt = lines_svg("today")
    lp, npl = lines_svg(OPT)
    svg = lambda inner, k=1: f'<svg width="{W*k:.0f}" height="{H*k:.0f}" viewBox="0 0 {W} {H}">{base()}{inner}</svg>'
    open("linkedin/1_network.html", "w").write(page(
        "<h1>מלולאות לקווים ישירים</h1>"
        "<p class='sub'>רשת האוטובוסים העירונית של אילת, ביום חול בחורף. כל צבע הוא קו.</p>"
        f"<div class='maps'><figure><figcaption>היום <span>· {nt} קווים, רובם לולאות בכיוון אחד</span></figcaption>{svg(lt)}</figure>"
        f"<figure><figcaption>ההצעה <span>· {npl} קווים, ישירים, הלוך וחזור</span></figcaption>{svg(lp)}</figure></div>"
        "<div class='foot'>בלי קווי בתי הספר (80–82), שנשארים כמו היום. ניתוח עצמאי מנתונים פומביים.</div>"))

    ch = D["summary"][OPT]["area"]

    def fill(a):
        v = ch.get(str(a["id"]))
        if v is None:
            return "#e4dfd3"
        if v > 0:
            return "#f3c4c0" if v >= 1 else "#f9e3e0"
        return "#a7d7c5" if v > -5 else ("#5fb49c" if v > -10 else "#2a8c73")
    lbl = ""
    for a in D["areas"]:
        v = ch.get(str(a["id"]))
        if v is None:
            continue
        r = max(a["rings"], key=len)
        x = sum(p[0] for p in r) / len(r); y = sum(p[1] for p in r) / len(r)
        X, Y = xy(y, x)
        t = (f"{v:+.0f}" if abs(v) >= 1 else f"{v:+.1f}").replace("-", "\u2212")
        lbl += f'<text x="{X:.0f}" y="{Y:.0f}" text-anchor="middle" class="lbl" direction="ltr">{t}%</text>'
    year = (1 - D["summary"][OPT]["season"]["year"]) * 100
    open("linkedin/2_areas.html", "w").write(page(
        f"<h1>כמעט כל שכונה מרוויחה</h1>"
        f"<p class='sub'>השינוי בזמן הנסיעה מהבית, מדלת לדלת, לעומת היום. ממוצע שנתי: כ-{year:.0f}% פחות בכל העיר.</p>"
        f"<div class='maps'><figure>{svg(areas_svg(fill) + lbl, 1.9)}</figure></div>"
        "<div class='leg'><span><i style='background:#2a8c73'></i>מתקצרת ב-10% ויותר</span><span><i style='background:#5fb49c'></i>5–10%</span>"
        "<span><i style='background:#a7d7c5'></i>עד 5%</span><span><i style='background:#f3c4c0'></i>מתארכת</span></div>"
        "<div class='foot'>אזורי מגורים. ממוצע של חורף, אביב-סתיו וקיץ לפי מספר החודשים. ניתוח עצמאי מנתונים פומביים.</div>"))


if __name__ == "__main__":
    main()
