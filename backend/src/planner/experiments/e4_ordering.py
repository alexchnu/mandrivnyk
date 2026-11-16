"""E4a: does automatic ordering shorten real tourist routes?

For every Flickr travel sequence with at least ``MIN_STOPS`` distinct POIs the
set of visited places is kept and only their order is changed. The traveller's
real order is compared with constructive, local-search and exact orderings on
the pedestrian travel-time matrix (OSRM, foot profile).

Run: ``uv run python -m planner.experiments.e4_ordering``
"""

from __future__ import annotations

import time

import numpy as np
import pandas as pd

from ..data.flickr import CITIES, load_sequences
from ..data.paths import RESULTS_DIR
from ..metrics import bootstrap_ci
from ..routing import order as od
from .matrices import load_matrix

MIN_STOPS = 4
MAX_STOPS = 14
N_RANDOM = 20


def run_city(city: str, rng: np.random.Generator) -> pd.DataFrame:
    mat = load_matrix(city)
    pos = {fid: i for i, fid in enumerate(mat["flickr_id"])}
    seqs = load_sequences(city, MIN_STOPS)
    rows = []
    for s in seqs.itertuples():
        idx = [pos[p] for p in s.pois if p in pos]
        if not MIN_STOPS <= len(idx) <= MAX_STOPS:
            continue
        cost = mat["duration_s"][np.ix_(idx, idx)] / 60.0  # minutes; row 0 is the real first stop
        n = len(idx)
        row = {"city": city, "seq": s.seq, "n": n, "user": od.path_cost(cost, list(range(n)))}
        rand = [od.path_cost(cost, [0, *(1 + rng.permutation(n - 1))]) for _ in range(N_RANDOM)]
        row["random"] = float(np.mean(rand))
        for name in ("nearest", "nearest_2opt", "user_2opt", "ortools", "exact"):
            t0 = time.perf_counter()
            order = _order_by(name, cost)
            row[f"t_{name}"] = time.perf_counter() - t0
            row[name] = od.path_cost(cost, order)
        rows.append(row)
    return pd.DataFrame(rows)


def _order_by(name: str, cost: np.ndarray) -> list[int]:
    if name == "nearest":
        return od.nearest_neighbour(cost, 0)
    if name == "nearest_2opt":
        return od.two_opt(cost, od.nearest_neighbour(cost, 0))
    if name == "user_2opt":
        return od.two_opt(cost, list(range(len(cost))))
    if name == "ortools":
        return od.ortools_path(cost, 0, time_limit_s=0.3)
    return od.held_karp(cost, 0) if len(cost) <= 11 else od.ortools_path(cost, 0, time_limit_s=3.0)


def summarise(df: pd.DataFrame) -> pd.DataFrame:
    methods = ["random", "user", "nearest", "nearest_2opt", "user_2opt", "ortools", "exact"]
    rows = []
    for city, grp in [*df.groupby("city"), ("all", df)]:
        for m in methods:
            ratio = grp[m] / grp["exact"]
            mean, lo, hi = bootstrap_ci(ratio.to_numpy())
            rows.append(
                {
                    "city": city,
                    "method": m,
                    "n_routes": len(grp),
                    "walk_min": grp[m].mean(),
                    "ratio_to_best": mean,
                    "ci_lo": lo,
                    "ci_hi": hi,
                    "share_optimal": float((ratio <= 1.0 + 1e-6).mean()),
                    "saved_min_vs_user": float((grp["user"] - grp[m]).mean()),
                    "time_ms": float(grp[f"t_{m}"].mean() * 1000) if f"t_{m}" in grp else np.nan,
                }
            )
    return pd.DataFrame(rows)


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(0)
    df = pd.concat([run_city(c, rng) for c in CITIES], ignore_index=True)
    df.to_csv(RESULTS_DIR / "e4_ordering_routes.csv", index=False)
    summary = summarise(df)
    summary.to_csv(RESULTS_DIR / "e4_ordering_summary.csv", index=False)
    pd.set_option("display.width", 200)
    print(summary[summary["city"] == "all"].round(3).to_string(index=False))
    print(df.groupby("city").size().to_string())
    by_n = df.groupby("n").agg(
        routes=("user", "size"),
        user=("user", "mean"),
        exact=("exact", "mean"),
        t_exact_ms=("t_exact", lambda x: x.mean() * 1000),
        t_ortools_ms=("t_ortools", lambda x: x.mean() * 1000),
    )
    by_n.to_csv(RESULTS_DIR / "e4_ordering_by_size.csv")
    print(by_n.round(2).to_string())


if __name__ == "__main__":
    main()
