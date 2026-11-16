"""E1: is the tag-based popularity proxy a valid signal of tourist interest?

Ground truth: number of distinct Flickr users who photographed a POI. The
hand-made proxy from the coursework is compared with Wikidata sitelinks and
Wikipedia pageviews (Spearman rank correlation, per city and pooled).

Run: ``uv run python -m planner.experiments.e1_popularity``
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from ..data.flickr import MAIN_CITIES
from ..data.paths import RESULTS_DIR
from ..ranking.features import manual_popularity
from .dataset import load_candidates

SIGNALS = {
    "manual": "Ручний скор (теги OSM)",
    "n_tags": "Кількість тегів OSM",
    "sitelinks": "Sitelinks Wikidata",
    "pageviews": "Перегляди Wikipedia",
}


def _boot_spearman(x: np.ndarray, y: np.ndarray, groups: np.ndarray, n_boot: int = 2000, seed: int = 0):
    """Pooled Spearman with a bootstrap CI; ranks are taken within city so that
    differences in city size and Flickr activity do not create the correlation."""
    frame = pd.DataFrame({"x": x, "y": y, "g": groups})
    frame["xr"] = frame.groupby("g")["x"].rank(pct=True)
    frame["yr"] = frame.groupby("g")["y"].rank(pct=True)
    rho = spearmanr(frame["xr"], frame["yr"]).statistic
    rng = np.random.default_rng(seed)
    xr, yr = frame["xr"].to_numpy(), frame["yr"].to_numpy()
    boots = []
    for _ in range(n_boot):
        idx = rng.integers(0, len(frame), len(frame))
        boots.append(spearmanr(xr[idx], yr[idx]).statistic)
    lo, hi = np.nanquantile(boots, [0.025, 0.975])
    return float(rho), float(lo), float(hi)


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    df = load_candidates()
    df["manual"] = manual_popularity(df)
    visited = df[df["label"] == 1].copy()

    rows = []
    for city, grp in visited.groupby("city"):
        for sig in SIGNALS:
            res = spearmanr(grp[sig], grp["flickr_users"])
            rows.append({"city": city, "signal": sig, "n": len(grp), "rho": res.statistic, "p": res.pvalue})
    main = visited[visited["city"].isin(MAIN_CITIES)]
    for sig in SIGNALS:
        rho, lo, hi = _boot_spearman(
            main[sig].to_numpy(), main["flickr_users"].to_numpy(), main["city"].to_numpy()
        )
        rows.append({"city": "all", "signal": sig, "n": len(main), "rho": rho, "ci_lo": lo, "ci_hi": hi})
    out = pd.DataFrame(rows)
    out.to_csv(RESULTS_DIR / "e1_spearman.csv", index=False)
    visited[["city", "name", "category", "flickr_users", *SIGNALS]].to_csv(
        RESULTS_DIR / "e1_points.csv", index=False
    )

    # How informative is the proxy over the whole candidate pool?
    pool = []
    for city, grp in df.groupby("city"):
        wiki = grp[grp["sitelinks"] > 0]
        pool.append(
            {
                "city": city,
                "candidates": len(grp),
                "visited": int(grp["label"].sum()),
                "with_wikidata": len(wiki),
                "share_wikidata": len(wiki) / len(grp),
                "manual_levels": grp["manual"].round(4).nunique(),
                "share_at_min_score": float((grp["manual"] <= 0.3 + 1e-9).mean()),
                "rho_manual_vs_pageviews": spearmanr(wiki["manual"], wiki["pageviews"]).statistic
                if len(wiki) > 5
                else np.nan,
                "rho_sitelinks_vs_pageviews": spearmanr(wiki["sitelinks"], wiki["pageviews"]).statistic
                if len(wiki) > 5
                else np.nan,
            }
        )
    pool = pd.DataFrame(pool)
    pool.to_csv(RESULTS_DIR / "e1_pool.csv", index=False)

    pd.set_option("display.width", 220)
    print(out.pivot(index="city", columns="signal", values="rho").round(3).to_string())
    print(out[out.city == "all"].round(3).to_string(index=False))
    print(pool.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
