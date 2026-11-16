"""E4b: multi-day planning with opening hours - greedy insertion vs OR-Tools.

Instances are built from real data: the most relevant sights of every benchmark
city (relevance = output of the deployed model), their real opening hours from
OSM where present, typical visit durations and pedestrian travel times (OSRM).

Run: ``uv run python -m planner.experiments.e4_toptw``
"""

from __future__ import annotations

import json
import time
from functools import partial

import numpy as np
import pandas as pd

from .. import hours
from ..data.flickr import MAIN_CITIES
from ..data.paths import PROCESSED_DIR, RESULTS_DIR
from ..geo import haversine_m
from ..ranking.features import density_centre
from ..routing.osrm import table
from ..routing.toptw import Stop, greedy_plan, ortools_plan

RADIUS_M = 3000.0
SIZES = (20, 40, 60)
DAYS = (1, 2, 3)
DAY_START, DAY_END = 9 * 60, 19 * 60
SCORE = "lgbm:osm+sitelinks"


def build_instance(city: str, scored: pd.DataFrame, n: int) -> tuple[list[Stop], np.ndarray, float]:
    df = scored[scored["city"] == city]
    c_lat, c_lon = density_centre(df)
    near = df[haversine_m(c_lat, c_lon, df["lat"].to_numpy(), df["lon"].to_numpy()) <= RADIUS_M]
    top = near.sort_values(SCORE, ascending=False).head(n).reset_index(drop=True)
    cache = PROCESSED_DIR / f"toptw_{city}_{n}.npz"
    if cache.exists() and list(np.load(cache, allow_pickle=True)["ids"]) == top["poi_id"].tolist():
        minutes = np.load(cache)["minutes"]
    else:
        duration, _ = table(top["lat"], top["lon"])
        minutes = duration / 60.0
        np.savez_compressed(cache, ids=top["poi_id"].to_numpy(), minutes=minutes)
    stops, with_hours = [], 0
    for tags, score, visit in zip(top["tags"], top[SCORE], top["visit_minutes"], strict=True):
        week = hours.parse(json.loads(tags).get("opening_hours"))
        with_hours += week is not None
        windows = [hours.intervals_for_day(week, d % 7) for d in range(max(DAYS))]  # trip starts on a Monday
        stops.append(Stop(float(score), int(visit), windows))
    return stops, minutes, with_hours / len(top)


def main() -> None:
    scored = pd.read_parquet(PROCESSED_DIR / "e2_loco_scores.parquet")
    rows = []
    for city in MAIN_CITIES:
        for n in SIZES:
            stops, minutes, hours_share = build_instance(city, scored, n)
            total = sum(s.profit for s in stops)
            for days in DAYS:
                day_stops = [Stop(s.profit, s.visit_min, s.windows[:days]) for s in stops]
                args = (day_stops, minutes, days, DAY_START, DAY_END)
                solvers = {
                    "greedy": partial(greedy_plan, *args),
                    "ortools_1s": partial(ortools_plan, *args, time_limit_s=1.0),
                    "ortools_5s": partial(ortools_plan, *args, time_limit_s=5.0),
                }
                for name, solve in solvers.items():
                    t0 = time.perf_counter()
                    plan = solve()
                    elapsed = time.perf_counter() - t0
                    rows.append({
                        "city": city, "n": n, "days": days, "solver": name, "profit": plan.profit(day_stops),
                        "profit_share": plan.profit(day_stops) / total, "stops": len(plan.visited),
                        "walk_min": plan.travel_min(minutes), "time_s": elapsed, "hours_share": hours_share,
                    })  # fmt: skip
            print(city, n, "done")
    df = pd.DataFrame(rows)
    df.to_csv(RESULTS_DIR / "e4_toptw.csv", index=False)
    wide = df.pivot_table(index=["city", "n", "days"], columns="solver", values="profit")
    gain = pd.DataFrame({
        "gain_1s_pct": (wide["ortools_1s"] / wide["greedy"] - 1) * 100,
        "gain_5s_pct": (wide["ortools_5s"] / wide["greedy"] - 1) * 100,
    }).reset_index()  # fmt: skip
    summary = df.groupby(["n", "days", "solver"]).agg(
        profit_share=("profit_share", "mean"), stops=("stops", "mean"), walk_min=("walk_min", "mean"), time_s=("time_s", "mean")
    ).reset_index()  # fmt: skip
    summary.to_csv(RESULTS_DIR / "e4_toptw_summary.csv", index=False)
    gains = gain.groupby(["n", "days"])[["gain_1s_pct", "gain_5s_pct"]].agg(["mean", "min", "max"])
    gains.to_csv(RESULTS_DIR / "e4_toptw_gain.csv")
    pd.set_option("display.width", 200)
    print(summary.round(3).to_string(index=False))
    print(gains.round(2).to_string())
    print("share of stops with parsed opening hours:", round(df["hours_share"].mean(), 3))
    print(
        "ortools worse than greedy in", int((gain["gain_5s_pct"] < -1e-6).sum()), "of", len(gain), "instances"
    )


if __name__ == "__main__":
    main()
