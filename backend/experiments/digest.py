"""Print every number quoted in the thesis from the result files (single source of truth)."""
import json

import pandas as pd

from planner.data.paths import PROCESSED_DIR as P
from planner.data.paths import RESULTS_DIR as R

pd.set_option("display.width", 250)
pd.set_option("display.max_rows", 300)


def show(title, frame):
    print(f"\n== {title}")
    print(frame.round(3).to_string(index=False) if not isinstance(frame.index, pd.MultiIndex) else frame.round(3).to_string())


show("E1 pool", pd.read_csv(R / "e1_pool.csv"))
e = pd.read_csv(R / "e1_spearman.csv")
show("E1 pooled", e[e.city == "all"])
m = pd.read_parquet(P / "flickr_osm_matches.parquet")
print("\n== matches")
print(m.groupby("city").agg(n=("flickr_id", "size"), matched=("poi_id", lambda x: x.notna().sum()),
                            by_id=("method", lambda x: (x == "wikidata").sum()),
                            classified=("osm_category", lambda x: x.notna().sum())).to_string())
print("\n== E2 summary", json.load(open(R / "e2_summary.json")))
x = pd.read_csv(R / "e2_metrics.csv")
show("E2 macro/pooled", x[x.city.isin(["macro", "pooled"])])
print(x.pivot(index="city", columns="method", values="pr_auc").round(3).to_string())
print(x.pivot(index="city", columns="method", values="roc_auc").round(3).to_string())
show("E2 sizes", x[x.method == "manual"][["city", "n", "pos"]])
show("E2 confusion", pd.read_csv(R / "e2_confusion.csv"))
lc = pd.read_csv(R / "e2_learning_curve.csv")
print(lc.groupby(["model", "n_train_cities"])[["test_auc", "train_auc"]].mean().round(3).to_string())
show("E2 importance", pd.read_csv(R / "e2_importance.csv"))
show("E3 data", pd.read_csv(R / "e3_data.csv"))
show("E3 explore", pd.read_csv(R / "e3_explore_summary.csv").drop(columns=["scorer", "selector"]))
show("E3 by city", pd.read_csv(R / "e3_explore_by_city.csv"))
show("E3 sensitivity", pd.read_csv(R / "e3_sensitivity.csv"))
show("E3 loco tuning", pd.read_csv(R / "e3_loco_tuning.csv"))
show("E3 ablation", pd.read_csv(R / "e3_ablation.csv"))
show("E3 tests", pd.read_csv(R / "e3_tests.csv"))
show("E3 interactive", pd.read_csv(R / "e3_interactive_summary.csv"))
show("E4 ordering", pd.read_csv(R / "e4_ordering_summary.csv"))
show("E4 by size", pd.read_csv(R / "e4_ordering_by_size.csv"))
for name in ("e4_toptw_summary.csv", "e4_toptw_gain.csv", "perf.csv"):
    if (R / name).exists():
        show(name, pd.read_csv(R / name))
