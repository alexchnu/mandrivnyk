"""E2: learned POI significance model vs hand-made scores.

Task: among sightseeing candidates of a city, find the places tourists really
visit (positives = OSM objects linked to Flickr POIs). Evaluation is
leave-one-city-out, so every city is scored by a model that never saw it.

Run: ``uv run python -m planner.experiments.e2_classifier``
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, confusion_matrix, f1_score, roc_auc_score, roc_curve

from ..data.flickr import EXTRA_CITIES, MAIN_CITIES
from ..data.paths import PROCESSED_DIR, RESULTS_DIR
from ..ranking import model as rm
from ..ranking.features import manual_popularity
from .dataset import load_candidates

VARIANTS = [
    ("logreg", "osm"),
    ("lgbm", "osm"),
    ("lgbm", "osm+sitelinks"),
    ("logreg", "osm+wiki"),
    ("lgbm", "osm+wiki"),
]
BASELINES = ["manual", "n_tags", "sitelinks", "pageviews"]


def load_sights() -> pd.DataFrame:
    df = load_candidates()
    df = df[df["category"].isin(rm.SIGHT_CATEGORIES)].reset_index(drop=True)
    df["manual"] = manual_popularity(df)
    return df


def loco_scores(df: pd.DataFrame, seed: int = 0) -> pd.DataFrame:
    """Out-of-city predictions of every model variant, as extra columns."""
    out = df.copy()
    for kind, fs in VARIANTS:
        col = f"{kind}:{fs}"
        out[col] = np.nan
        for city in sorted(df["city"].unique()):
            # extra cities never take part in training; main cities are left out one at a time
            train = df[(df["city"] != city) & df["city"].isin(MAIN_CITIES)]
            test = df[df["city"] == city]
            model = rm.fit(train, fs, kind, seed)
            out.loc[test.index, col] = rm.predict(model, test, fs)
    return out


def _best_threshold(y: np.ndarray, score: np.ndarray) -> float:
    grid = np.quantile(score, np.linspace(0.5, 0.999, 200))
    return float(max(grid, key=lambda t: f1_score(y, score >= t, zero_division=0)))


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    df = load_sights()
    scored = loco_scores(df)
    scored.to_parquet(PROCESSED_DIR / "e2_loco_scores.parquet", index=False)
    methods = BASELINES + [f"{k}:{f}" for k, f in VARIANTS]

    main = scored[scored["city"].isin(MAIN_CITIES)]
    rows = []
    for city, grp in [*scored.groupby("city"), ("pooled", main)]:
        y = grp["label"].to_numpy()
        for m in methods:
            s = grp[m].to_numpy()
            k = int(y.sum())
            top = np.argsort(-s, kind="stable")[:k]
            rows.append(
                {
                    "city": city,
                    "method": m,
                    "n": len(grp),
                    "pos": k,
                    "roc_auc": roc_auc_score(y, s),
                    "pr_auc": average_precision_score(y, s),
                    "r_precision": float(y[top].mean()),
                }
            )
    res = pd.DataFrame(rows)
    macro = (
        res[res.city.isin(MAIN_CITIES)]
        .groupby("method")[["roc_auc", "pr_auc", "r_precision"]]
        .mean()
        .reset_index()
    )
    macro.insert(0, "city", "macro")
    res = pd.concat([res, macro], ignore_index=True)
    res.to_csv(RESULTS_DIR / "e2_metrics.csv", index=False)

    # ROC curves (pooled out-of-city predictions)
    curves = []
    for m in methods:
        fpr, tpr, _ = roc_curve(main["label"], main[m])
        grid = np.linspace(0, 1, 201)
        curves.append(pd.DataFrame({"method": m, "fpr": grid, "tpr": np.interp(grid, fpr, tpr)}))
    pd.concat(curves).to_csv(RESULTS_DIR / "e2_roc.csv", index=False)

    # Confusion matrices at the F1-optimal threshold; the threshold comes from training cities only
    cms = []
    for method in ("manual", "lgbm:osm", "lgbm:osm+sitelinks"):
        cm = np.zeros((2, 2), int)
        for city in MAIN_CITIES:
            train, test = main[main.city != city], main[main.city == city]
            thr = _best_threshold(train["label"].to_numpy(), train[method].to_numpy())
            cm += confusion_matrix(test["label"], test[method] >= thr, labels=[0, 1])
        tn, fp, fn, tp = cm.ravel()
        precision, recall = tp / max(tp + fp, 1), tp / max(tp + fn, 1)
        cms.append({"method": method, "tn": tn, "fp": fp, "fn": fn, "tp": tp, "precision": precision,
                    "recall": recall, "f1": 2 * precision * recall / max(precision + recall, 1e-9)})  # fmt: skip
    cms = pd.DataFrame(cms)
    cms.to_csv(RESULTS_DIR / "e2_confusion.csv", index=False)
    cm_total = cms

    # Learning curve: how many training cities are needed (test city fixed, random subsets of the rest)
    rng = np.random.default_rng(0)
    df_all, df = df, df[df["city"].isin(MAIN_CITIES)]
    cities = list(MAIN_CITIES)
    lc = []
    for test_city in cities:
        rest = [c for c in cities if c != test_city]
        test = df[df.city == test_city]
        for size in range(1, len(rest) + 1):
            for rep in range(3 if size < len(rest) else 1):
                subset = list(rng.choice(rest, size, replace=False))
                train = df[df.city.isin(subset)]
                if train["label"].sum() < 5:
                    continue
                for kind, fs in (("lgbm", "osm"), ("lgbm", "osm+sitelinks")):
                    model = rm.fit(train, fs, kind, seed=rep)
                    pred = rm.predict(model, test, fs)
                    fit_pred = rm.predict(model, train, fs)
                    lc.append(
                        {
                            "test_city": test_city,
                            "n_train_cities": size,
                            "model": f"{kind}:{fs}",
                            "n_train_pos": int(train["label"].sum()),
                            "test_auc": roc_auc_score(test["label"], pred),
                            "train_auc": roc_auc_score(train["label"], fit_pred),
                        }
                    )
    pd.DataFrame(lc).to_csv(RESULTS_DIR / "e2_learning_curve.csv", index=False)

    # Feature importance of the final models (trained on all cities)
    lgbm = rm.fit(df, "osm", "lgbm")
    logreg = rm.fit(df, "osm", "logreg")
    imp = pd.DataFrame(
        {
            "feature": rm.FEATURE_SETS["osm"],
            "lgbm_gain": lgbm.booster_.feature_importance(importance_type="gain"),
            "logreg_coef": logreg[-1].coef_[0],
        }
    )
    imp["lgbm_gain"] /= imp["lgbm_gain"].sum()
    imp.sort_values("lgbm_gain", ascending=False).to_csv(RESULTS_DIR / "e2_importance.csv", index=False)

    pd.set_option("display.width", 220)
    print(res[res.city.isin(["pooled", "macro"])].round(3).to_string(index=False))
    print(
        res[res.method.isin(["manual", "lgbm:osm", "lgbm:osm+wiki"])]
        .pivot(index="city", columns="method", values="roc_auc")
        .round(3)
        .to_string()
    )
    print(cm_total.round(3).to_string(index=False))
    print(imp.sort_values("lgbm_gain", ascending=False).head(12).round(3).to_string(index=False))
    (RESULTS_DIR / "e2_summary.json").write_text(
        json.dumps(
            {
                "n_candidates": len(df),
                "n_positive": int(df["label"].sum()),
                "cities": cities,
                "extra_cities": list(EXTRA_CITIES),
                "n_candidates_extra": len(df_all) - len(df),
            },
            indent=1,
        )
    )


if __name__ == "__main__":
    main()
