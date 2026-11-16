"""E3: quality of recommendations on real tourist trajectories.

Two protocols replay Flickr travel sequences against the recommender:

* **explore** - the traveller opens the map at the first place of the trip and
  gets a page of ``K_EXPLORE`` suggestions within ``RADIUS_KM``; the other places
  of the same trip are the relevant items;
* **interactive** - the trip is replayed stop by stop; after each real stop the
  system suggests ``K_NEARBY`` next places and is scored on the stop the
  traveller really chose next.

Compared: relevance signals (hand-made, Wikidata/Wikipedia, learned models
evaluated out-of-city) x list construction (plain ranking, category round-robin
from the coursework, MMR, xQuAD) + ablation and parameter sensitivity.

Run: ``uv run python -m planner.experiments.e3_recommendation``
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.stats import wilcoxon

from .. import diversify as dv
from .. import metrics as mt
from ..data.flickr import CITIES, MAIN_CITIES, load_sequences
from ..data.paths import PROCESSED_DIR, RESULTS_DIR
from ..geo import haversine_m
from ..ranking.features import manual_popularity
from ..ranking.model import SIGHT_CATEGORIES

RADIUS_KM = 3.0
K_EXPLORE = 12
K_NEARBY = 8
POOL_SIZE = 100  # candidates passed from ranking to list construction
MIN_TRIP = 3

SCORERS = {
    "manual": "Ручний скор",
    "sitelinks": "Sitelinks",
    "pageviews": "Перегляди",
    "lgbm:osm": "Модель (OSM)",
    "lgbm:osm+sitelinks": "Модель (OSM+sitelinks)",
    "lgbm:osm+wiki": "Модель (OSM+Wiki)",
}
SELECTORS = ("top_k", "round_robin", "mmr", "xquad")
DEPLOYED = "lgbm:osm+sitelinks"  # relevance model used by the service
PROPOSED = f"{DEPLOYED}|w=0.15|lam=0.25"  # service configuration: xQuAD, distance weight 0.15


@dataclass(slots=True)
class City:
    key: str
    df: pd.DataFrame
    lat: np.ndarray
    lon: np.ndarray
    cats: np.ndarray
    subs: np.ndarray
    index_of: dict[int, int]  # flickr id -> row
    rel: dict[str, np.ndarray]
    trips: list[list[int]]  # rows of visited places, in visiting order


def load_city(key: str, scored: pd.DataFrame) -> City | None:
    df = scored[scored["city"] == key].reset_index(drop=True)
    if df.empty:
        return None
    cat_code = {c: i for i, c in enumerate(SIGHT_CATEGORIES)}
    index_of = {int(f): i for i, f in enumerate(df["flickr_id"]) if not pd.isna(f)}
    trips = []
    for pois in load_sequences(key, MIN_TRIP)["pois"]:
        rows = [index_of[p] for p in pois if p in index_of]
        rows = list(dict.fromkeys(rows))
        if len(rows) >= MIN_TRIP:
            trips.append(rows)
    rel = {
        "manual": manual_popularity(df),
        "sitelinks": df["sitelinks_log"].to_numpy(float),
        "pageviews": df["pageviews_log"].to_numpy(float),
        "lgbm:osm": df["lgbm:osm"].to_numpy(float),
        "lgbm:osm+sitelinks": df["lgbm:osm+sitelinks"].to_numpy(float),
        "lgbm:osm+wiki": df["lgbm:osm+wiki"].to_numpy(float),
    }
    return City(
        key,
        df,
        df["lat"].to_numpy(float),
        df["lon"].to_numpy(float),
        df["category"].map(cat_code).to_numpy(int),
        pd.factorize(df["subtype"])[0],
        index_of,
        rel,
        trips,
    )


# --------------------------------------------------------------------- lists
def base_scores(city: City, scorer: str, around: int, w_dist: float, jitter_seed: int | None = None):
    """Relevance + closeness for candidates within the radius of row ``around``.

    Returns (rows, score, relevance in [0, 1]). ``manual`` keeps the exact
    coursework formula 0.4 * popularity + 0.2 * closeness when ``w_dist`` is None.
    """
    dist_km = haversine_m(city.lat[around], city.lon[around], city.lat, city.lon) / 1000.0
    rows = np.flatnonzero(dist_km <= RADIUS_KM)
    rows = rows[rows != around]
    closeness = 1.0 - dist_km[rows] / RADIUS_KM
    rel = dv.minmax(city.rel[scorer][rows])
    score = (1.0 - w_dist) * rel + w_dist * closeness
    if jitter_seed is not None:
        score = score + np.random.default_rng(jitter_seed).uniform(0, 0.08 / 0.6, len(rows))
    return rows, score


def build_list(
    city: City,
    rows: np.ndarray,
    score: np.ndarray,
    selector: str,
    k: int,
    *,
    lam: float = 0.5,
    max_per_cat: int = 2,
    exclude: frozenset[int] = frozenset(),
    context_cats: tuple[int, ...] = (),
) -> list[int]:
    keep = np.array([r not in exclude for r in rows], bool) if exclude else np.ones(len(rows), bool)
    rows, score = rows[keep], score[keep]
    top = np.argsort(-score, kind="stable")[:POOL_SIZE]
    rows, score = rows[top], score[top]
    cats = city.cats[rows]
    if selector == "top_k":
        pick = dv.top_k(score, k)
    elif selector == "round_robin":
        pick = dv.round_robin(score, cats, k, max_per_cat)
    elif selector == "mmr":
        pick = dv.mmr(score, dv.category_similarity(cats, city.subs[rows]), k, lam)
    elif selector == "xquad":
        pick = dv.xquad(score, cats, k, lam, already_selected=context_cats)
    else:
        raise ValueError(selector)
    return rows[pick].tolist()


def list_metrics(city: City, ranked: list[int], relevant: set[int], k: int) -> dict[str, float]:
    cats = city.cats[ranked[:k]]
    sim = dv.category_similarity(cats, city.subs[ranked[:k]])
    return {
        "recall": mt.recall_at_k(ranked, relevant, k),
        "precision": mt.precision_at_k(ranked, relevant, k),
        "f1": mt.f1_at_k(ranked, relevant, k),
        "ndcg": mt.ndcg_at_k(ranked, relevant, k),
        "ild": mt.intra_list_diversity(list(range(len(cats))), sim),
        "categories": float(len(set(cats.tolist()))),
        "entropy": mt.category_entropy(cats, len(SIGHT_CATEGORIES)),
    }


# ------------------------------------------------------------------ explore
def run_explore(cities: list[City], configs: list[dict]) -> pd.DataFrame:
    """Per (trip, config) metrics for the first page and recall after two pages."""
    out = []
    for city in cities:
        cache: dict[tuple, tuple[list[int], list[int]]] = {}
        for trip_id, trip in enumerate(city.trips):
            start, relevant = trip[0], set(trip[1:])
            for ci, cfg in enumerate(configs):
                key = (start, ci)
                if key not in cache:
                    rows, score = base_scores(city, cfg["scorer"], start, cfg["w_dist"], cfg.get("jitter"))
                    kw = {"lam": cfg.get("lam", 0.5), "max_per_cat": cfg.get("max_per_cat", 2)}
                    page1 = build_list(city, rows, score, cfg["selector"], K_EXPLORE, **kw)
                    page2 = build_list(
                        city, rows, score, cfg["selector"], K_EXPLORE, exclude=frozenset(page1), **kw
                    )
                    cache[key] = (page1, page2)
                page1, page2 = cache[key]
                in_reach = relevant & set(
                    np.flatnonzero(
                        haversine_m(city.lat[start], city.lon[start], city.lat, city.lon) <= RADIUS_KM * 1000
                    ).tolist()
                )
                if not in_reach:
                    continue
                m = list_metrics(city, page1, in_reach, K_EXPLORE)
                m["recall_2pages"] = mt.recall_at_k(page1 + page2, in_reach, 2 * K_EXPLORE)
                out.append({"city": city.key, "trip": trip_id, "config": cfg["name"], **m})
    return pd.DataFrame(out)


# -------------------------------------------------------------- interactive
def run_interactive(cities: list[City], configs: list[dict]) -> pd.DataFrame:
    out = []
    for city in cities:
        for trip_id, trip in enumerate(city.trips):
            for t in range(1, len(trip)):
                current, target = trip[t - 1], trip[t]
                if (
                    haversine_m(city.lat[current], city.lon[current], city.lat[target], city.lon[target])
                    > RADIUS_KM * 1000
                ):
                    continue
                visited = frozenset(trip[:t])
                context = tuple(city.cats[trip[:t]].tolist())
                for cfg in configs:
                    rows, score = base_scores(city, cfg["scorer"], current, cfg["w_dist"])
                    ranked = build_list(
                        city,
                        rows,
                        score,
                        cfg["selector"],
                        K_NEARBY,
                        lam=cfg.get("lam", 0.5),
                        exclude=visited,
                        context_cats=context if cfg.get("contextual") else (),
                    )
                    future = set(trip[t:])
                    out.append(
                        {
                            "city": city.key,
                            "trip": trip_id,
                            "step": t,
                            "config": cfg["name"],
                            "hit": float(target in ranked),
                            "mrr": mt.reciprocal_rank(ranked, target),
                            "recall_future": mt.recall_at_k(ranked, future, K_NEARBY),
                            "categories": float(len(set(city.cats[ranked].tolist()))),
                        }
                    )
    return pd.DataFrame(out)


# ------------------------------------------------------------------ helpers
def summarise(df: pd.DataFrame, metrics: list[str], unit: list[str]) -> pd.DataFrame:
    """Mean over evaluation units with bootstrap CI; also the macro average over cities."""
    rows = []
    is_main = df["city"].isin(MAIN_CITIES)
    extra = df[~is_main].groupby("config")[metrics].mean()
    for cfg, grp in df[is_main].groupby("config", sort=False):
        row = {"config": cfg, "n": len(grp)}
        for m in metrics:
            mean, lo, hi = mt.bootstrap_ci(grp[m].to_numpy(), n_boot=1000)
            row[m], row[f"{m}_lo"], row[f"{m}_hi"] = mean, lo, hi
            row[f"{m}_macro"] = grp.groupby("city")[m].mean().mean()
            if cfg in extra.index:  # out-of-distribution city, reported separately
                row[f"{m}_extra"] = float(extra.loc[cfg, m])
        rows.append(row)
    return pd.DataFrame(rows)


def paired_test(df: pd.DataFrame, a: str, b: str, metric: str, unit: list[str]) -> dict:
    df = df[df["city"].isin(MAIN_CITIES)]
    wide = df[df["config"].isin([a, b])].pivot_table(index=unit, columns="config", values=metric)
    diff = (wide[a] - wide[b]).dropna()
    stat = wilcoxon(diff) if (diff != 0).any() else None
    per_city = df[df["config"].isin([a, b])].pivot_table(index="city", columns="config", values=metric)
    return {
        "a": a,
        "b": b,
        "metric": metric,
        "n": len(diff),
        "mean_a": wide[a].mean(),
        "mean_b": wide[b].mean(),
        "diff": diff.mean(),
        "p_wilcoxon": stat.pvalue if stat else 1.0,
        "cities_a_better": int((per_city[a] > per_city[b]).sum()),
        "cities": len(per_city),
    }


def cfg(name: str, scorer: str, selector: str, w_dist: float = 1 / 3, **kw) -> dict:
    return {"name": name, "scorer": scorer, "selector": selector, "w_dist": w_dist, **kw}


def loco_choice(grid_summary: pd.DataFrame, metric: str) -> pd.DataFrame:
    """For every test city pick the grid point that is best on the *other* cities."""
    rows = []
    cities = sorted(grid_summary["city"].unique())
    for test in cities:
        tuning = grid_summary[(grid_summary["city"] != test) & grid_summary["city"].isin(MAIN_CITIES)]
        others = tuning.groupby("config")[metric].mean()
        best = others.idxmax()
        hit = grid_summary[(grid_summary["city"] == test) & (grid_summary["config"] == best)]
        rows.append({"city": test, "chosen": best, metric: float(hit[metric].iloc[0])})
    return pd.DataFrame(rows)


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    scored = pd.read_parquet(PROCESSED_DIR / "e2_loco_scores.parquet")
    cities = [c for c in (load_city(k, scored) for k in CITIES) if c is not None and c.trips]
    stats = pd.DataFrame(
        [
            {
                "city": c.key,
                "candidates": len(c.df),
                "visited": len(c.index_of),
                "trips": len(c.trips),
                "mean_trip_len": float(np.mean([len(t) for t in c.trips])),
            }
            for c in cities
        ]
    )
    stats.to_csv(RESULTS_DIR / "e3_data.csv", index=False)
    print(stats.round(2).to_string(index=False))
    pd.set_option("display.width", 250)
    explore_metrics = ["recall", "ndcg", "f1", "recall_2pages", "ild", "categories", "entropy"]

    # 1. Main grid: relevance signal x list construction ---------------------
    main_cfgs = [cfg(f"{s}|{sel}", s, sel) for s in SCORERS for sel in SELECTORS]
    explore = run_explore(cities, main_cfgs)
    explore.to_parquet(PROCESSED_DIR / "e3_explore.parquet", index=False)
    summary = summarise(explore, explore_metrics, ["city", "trip"])
    summary[["scorer", "selector"]] = summary["config"].str.split("|", expand=True)
    summary.to_csv(RESULTS_DIR / "e3_explore_summary.csv", index=False)
    explore.groupby(["city", "config"])[explore_metrics].mean().reset_index().to_csv(
        RESULTS_DIR / "e3_explore_by_city.csv", index=False
    )
    print(
        summary[["config", "n", "recall", "ndcg", "recall_2pages", "ild", "categories"]]
        .round(3)
        .to_string(index=False)
    )

    # 2. Ablation of the coursework method -----------------------------------
    abl = [
        cfg("full", "manual", "round_robin"),
        cfg("no_diversification", "manual", "top_k"),
        cfg("no_popularity", "manual", "round_robin", w_dist=1.0),
        cfg("no_distance", "manual", "round_robin", w_dist=0.0),
        *[cfg(f"jitter_seed{s}", "manual", "round_robin", jitter=s) for s in range(5)],
        *[cfg(f"max_per_cat={m}", "manual", "round_robin", max_per_cat=m) for m in (1, 2, 3, 4, 6)],
    ]
    ablation = summarise(run_explore(cities, abl), explore_metrics, ["city", "trip"])
    ablation.to_csv(RESULTS_DIR / "e3_ablation.csv", index=False)
    print(ablation[["config", "recall", "ndcg", "ild", "categories"]].round(3).to_string(index=False))

    # 3. Sensitivity: distance weight and diversification strength ----------
    # DEPLOYED is the scorer the service can compute for any city (OSM + one batched
    # Wikidata call); the richer "+wiki" scorer needs the monthly pageview dump.
    grid = [
        cfg(f"{scorer}|w={w:.2f}|lam={lam:.2f}", scorer, "xquad", w_dist=w, lam=lam)
        for scorer in (DEPLOYED, "lgbm:osm+wiki")
        for w in (0.0, 0.15, 0.33, 0.5, 0.7)
        for lam in (0.0, 0.25, 0.5, 0.75, 1.0)
    ]
    grid += [
        cfg(f"mmr|w=0.15|lam={lam:.2f}", DEPLOYED, "mmr", w_dist=0.15, lam=lam)
        for lam in (0.3, 0.5, 0.7, 0.85, 1.0)
    ]
    grid += [cfg(f"round_robin|w={w:.2f}", DEPLOYED, "round_robin", w_dist=w) for w in (0.15, 0.33)]
    grid += [
        cfg(f"manual|w={w:.2f}", "manual", "round_robin", w_dist=w) for w in (0.0, 0.15, 0.33, 0.5, 0.7, 1.0)
    ]
    sens_raw = run_explore(cities, grid)
    sens_raw.to_parquet(PROCESSED_DIR / "e3_sensitivity.parquet", index=False)
    sens = summarise(sens_raw, explore_metrics, ["city", "trip"])
    sens.to_csv(RESULTS_DIR / "e3_sensitivity.csv", index=False)
    by_city = sens_raw.groupby(["city", "config"])[explore_metrics].mean().reset_index()
    xq = by_city[by_city["config"].str.startswith(f"{DEPLOYED}|w=")]
    chosen = loco_choice(xq, "ndcg")
    chosen.to_csv(RESULTS_DIR / "e3_loco_tuning.csv", index=False)
    print(sens[["config", "recall", "ndcg", "ild", "categories"]].round(3).to_string(index=False))
    print(chosen.to_string(index=False))

    # 4. Interactive protocol -------------------------------------------------
    inter_cfgs = [
        cfg("manual|round_robin", "manual", "round_robin"),
        cfg("manual|top_k", "manual", "top_k"),
        cfg("pageviews|top_k", "pageviews", "top_k"),
        cfg("lgbm:osm|top_k", "lgbm:osm", "top_k"),
        cfg("lgbm:osm|round_robin", "lgbm:osm", "round_robin"),
        cfg("lgbm:osm|xquad", "lgbm:osm", "xquad"),
        cfg("lgbm:osm|xquad+context", "lgbm:osm", "xquad", contextual=True),
        cfg("lgbm:osm+wiki|top_k", "lgbm:osm+wiki", "top_k"),
        cfg("lgbm:osm+wiki|round_robin", "lgbm:osm+wiki", "round_robin"),
        cfg("lgbm:osm+wiki|xquad", "lgbm:osm+wiki", "xquad"),
        cfg("lgbm:osm+wiki|xquad+context", "lgbm:osm+wiki", "xquad", contextual=True),
        cfg("distance_only", "manual", "top_k", w_dist=1.0),
        cfg("lgbm:osm+sitelinks|top_k", "lgbm:osm+sitelinks", "top_k"),
        cfg("proposed", DEPLOYED, "xquad", w_dist=0.15, lam=0.25),
        cfg("proposed+context", DEPLOYED, "xquad", w_dist=0.15, lam=0.25, contextual=True),
        cfg(f"{DEPLOYED}|top_k|w=0.15", DEPLOYED, "top_k", w_dist=0.15),
        cfg(f"{DEPLOYED}|round_robin", DEPLOYED, "round_robin"),
        cfg("lgbm:osm+sitelinks|xquad", "lgbm:osm+sitelinks", "xquad"),
        # how much should closeness to the current stop weigh when the next stop is suggested?
        *[
            cfg(f"lgbm:osm+wiki|top_k|w={w:.2f}", "lgbm:osm+wiki", "top_k", w_dist=w)
            for w in (0.0, 0.15, 0.5, 0.7, 0.85)
        ],
        *[cfg(f"lgbm:osm+wiki|xquad|w={w:.2f}", "lgbm:osm+wiki", "xquad", w_dist=w) for w in (0.5, 0.7)],
        *[cfg(f"manual|round_robin|w={w:.2f}", "manual", "round_robin", w_dist=w) for w in (0.15, 0.5, 0.7)],
    ]
    inter = run_interactive(cities, inter_cfgs)
    inter.to_parquet(PROCESSED_DIR / "e3_interactive.parquet", index=False)
    inter_summary = summarise(inter, ["hit", "mrr", "recall_future", "categories"], ["city", "trip", "step"])
    inter_summary.to_csv(RESULTS_DIR / "e3_interactive_summary.csv", index=False)
    print(
        inter_summary[["config", "n", "hit", "mrr", "recall_future", "categories"]]
        .round(3)
        .to_string(index=False)
    )

    # 5. Significance of the key comparisons ---------------------------------
    both = pd.concat([explore, sens_raw], ignore_index=True)
    trip, step = ["city", "trip"], ["city", "trip", "step"]
    old = "manual|round_robin"
    tests = [
        # learned relevance vs the hand-made score, same list construction
        paired_test(explore, "lgbm:osm|round_robin", old, "ndcg", trip),
        paired_test(explore, f"{DEPLOYED}|round_robin", old, "ndcg", trip),
        paired_test(explore, "lgbm:osm+wiki|round_robin", old, "ndcg", trip),
        # the configuration shipped in the service vs the coursework algorithm
        paired_test(both, PROPOSED, old, "ndcg", trip),
        paired_test(both, PROPOSED, old, "recall", trip),
        paired_test(both, PROPOSED, old, "ild", trip),
        paired_test(both, PROPOSED, old, "categories", trip),
        # price of diversification
        paired_test(explore, f"{DEPLOYED}|xquad", f"{DEPLOYED}|top_k", "ild", trip),
        paired_test(explore, f"{DEPLOYED}|xquad", f"{DEPLOYED}|top_k", "ndcg", trip),
        paired_test(both, PROPOSED, f"{DEPLOYED}|w=0.15|lam=0.00", "ndcg", trip),
        paired_test(both, PROPOSED, f"{DEPLOYED}|w=0.15|lam=0.00", "ild", trip),
        paired_test(explore, old, "manual|top_k", "ndcg", trip),
        # round-robin from the coursework vs xQuAD on the same relevance
        paired_test(explore, f"{DEPLOYED}|xquad", f"{DEPLOYED}|round_robin", "ndcg", trip),
        # interactive protocol
        paired_test(inter, "proposed", old, "hit", step),
        paired_test(inter, "proposed", old, "mrr", step),
        paired_test(inter, f"{DEPLOYED}|top_k", old, "hit", step),
        paired_test(inter, "lgbm:osm|top_k", old, "hit", step),
        paired_test(inter, "lgbm:osm+wiki|xquad+context", "lgbm:osm+wiki|xquad", "hit", step),
        paired_test(inter, "proposed+context", "proposed", "hit", step),
    ]
    tests = pd.DataFrame(tests)
    tests.to_csv(RESULTS_DIR / "e3_tests.csv", index=False)
    print(tests.round(4).to_string(index=False))


if __name__ == "__main__":
    main()
