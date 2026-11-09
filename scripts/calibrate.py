"""Calibrate the demand model on boardings per line, 2025 Q4 (the cleanest quarter: today's network, the 67+
rule in force, no evacuees, no war).

For each (logit scale, bus constant, car-owner propensity) on a grid, the purpose scales K are fitted by
non-negative least squares on relative errors, with a light pull toward equal scales (so one purpose can't
absorb everything). The best combination is kept. Checks: leave-one-line-out, and prediction (no refit) of
2025 Q2 (spring, hot middays) and 2026 Q1 (winter).

Outputs: data/calibration.json, data/calibration_fit.csv
"""
import itertools
import json

import numpy as np
import pandas as pd
from scipy.optimize import nnls

from eilat import demand as D
from eilat import model as M
from eilat import network as N

LINES = ["1", "2", "3", "4", "5", "6", "15", "16"]
MU = 0.05
GRID = dict(lam=[0.15, 0.2, 0.25, 0.3], const=[0.0, 1.0, 2.0], cp=[0.05, 0.1, 0.2])
MUS = [0.05, 0.3, 1.0, 3.0]


def targets(yq):
    d = pd.read_csv("data/ridership_eilat.csv")
    d = d[d.DestinationCityName == "אילת"]
    d = d[(d.year.astype(str) + "-" + d.Q.astype(str).str.replace("Q", "")) == yq]
    return d.groupby(d.RouteName.astype(str)).DailyPassengers.sum().reindex(LINES)


def board_matrix(m, pats, season, lam, const, cp):
    r = m.run(pats, season, lam=lam, const=const, car_prop=cp)
    B = pd.DataFrame(0.0, index=LINES, columns=D.PURPOSES)
    for p, b in r["board"].items():
        for pt, x in zip(pats, b, strict=True):
            ln = M.line_of(pt.line)
            if ln in LINES:
                B.loc[ln, p] += x
    return B


def fit(B, y, mu=MU):
    w = 1 / y.values
    A = B.values * w[:, None]; b = np.ones(len(y))
    # scale-free prior: all K equal to the single scale that best fits the total
    s = y.sum() / max(B.values.sum(), 1e-9)
    A2 = np.vstack([A, np.sqrt(mu) * np.eye(B.shape[1]) / s]); b2 = np.concatenate([b, np.sqrt(mu) * np.ones(B.shape[1])])
    k, _ = nnls(A2, b2)
    pred = B.values @ k
    err = np.sqrt(np.mean(((pred - y.values) / y.values) ** 2))
    return k, pred, err


def main():
    m = M.Model(); pats = N.from_gtfs()
    y = targets("2025-4")
    cache = {}
    for lam, const, cp in itertools.product(GRID["lam"], GRID["const"], GRID["cp"]):
        cache[(lam, const, cp)] = board_matrix(m, pats, "winter", lam, const, cp)
        print("computed", lam, const, cp, flush=True)
    summary = []
    for mu in MUS:
        res = min(((fit(B, y, mu)[2], key, B) for key, B in cache.items()), key=lambda x: x[0])
        err, key, B = res
        k, pred, _ = fit(B, y, mu)
        sh = (B * k).sum() / (B * k).values.sum()
        summary.append(dict(mu=mu, rel_rmse=round(err, 3), lam=key[0], const=key[1], car=key[2],
                            **{f"share_{p}": round(v * 100, 1) for p, v in sh.items()}))
    S = pd.DataFrame(summary); print(S.to_string(index=False))
    # choose the strongest prior whose fit is within 0.03 of the best
    ok = S[S.rel_rmse <= S.rel_rmse.min() + 0.03]
    mu = float(ok.mu.max()); print("chosen prior strength", mu)
    row = S[S.mu == mu].iloc[0]; key = (row.lam, row.const, row.car); B = cache[key]
    k, pred, err = fit(B, y, mu)
    best = (err, key[0], key[1], key[2], k, pred, B)
    globals()["MU"] = mu
    err, lam, const, cp, k, pred, B = best
    K = dict(zip(D.PURPOSES, map(float, k), strict=True))
    print(f"\nBEST lam {lam} const {const} car_prop {cp}  rel. RMSE {err:.3f}\nK: " + str({p: round(v, 3) for p, v in K.items()}))
    t = pd.DataFrame({"observed": y, "model": pred.round(0)}); t["ratio"] = (t.model / t.observed).round(2)
    share = (B * k).sum() / (B * k).values.sum()
    print(t.to_string()); print("boardings by purpose:", (share * 100).round(1).to_dict())
    # leave one line out
    loo = []
    for i, ln in enumerate(LINES):
        keep = [j for j in range(len(LINES)) if j != i]
        kk, _, _ = fit(B.iloc[keep], y.iloc[keep], MU)
        loo.append((ln, float(B.values[i] @ kk / y.values[i])))
    print("leave-one-line-out ratio:", {a: round(b, 2) for a, b in loo})
    # out-of-sample quarters, same parameters
    checks = {}
    for yq, season in [("2025-2", "spring_autumn"), ("2026-1", "winter")]:
        yy = targets(yq); BB = board_matrix(m, pats, season, lam, const, cp); pp = BB.values @ k
        checks[yq] = dict(observed_total=float(yy.sum()), model_total=float(pp.sum()),
                          rel_rmse=float(np.sqrt(np.mean(((pp - yy.values) / yy.values) ** 2))))
        print(yq, {kk: round(v, 2) for kk, v in checks[yq].items()})
    kB, predB, errB = fit(B, y, 1.0)
    shB = (B * kB).sum() / (B * kB).values.sum()
    print("variant B (prior strength 1.0): rel. RMSE %.3f, K %s, shares %s" % (errB, dict(zip(D.PURPOSES, kB.round(3))),
          (shB * 100).round(1).to_dict()))
    json.dump(dict(mu=MU, lam=lam, const=const, car_prop=cp, K=K, K_prior=dict(zip(D.PURPOSES, map(float, kB))),
                   rel_rmse_prior=float(errB), purpose_share_prior=shB.round(4).to_dict(), rel_rmse=err, loo=dict(loo), checks=checks,
                   purpose_share=share.round(4).to_dict()), open("data/calibration.json", "w"), indent=1)
    t.to_csv("data/calibration_fit.csv")


if __name__ == "__main__":
    main()
