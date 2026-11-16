"""Train the significance models shipped with the service (all main cities).

Run: ``uv run python -m planner.experiments.train_final``
"""

from __future__ import annotations

from datetime import date

from ..data.flickr import MAIN_CITIES
from ..ranking import model as rm
from .e2_classifier import load_sights

ARTIFACT_DIR = rm.Path(__file__).resolve().parents[1] / "ranking" / "artifacts"


def main() -> None:
    df = load_sights()
    df = df[df["city"].isin(MAIN_CITIES)]
    for feature_set in ("osm", "osm+sitelinks"):
        model = rm.fit(df, feature_set, "lgbm")
        path = ARTIFACT_DIR / f"significance_{feature_set.replace('+', '_')}.joblib"
        rm.save(model, path, feature_set, "lgbm", {
            "trained": date.today().isoformat(), "cities": list(MAIN_CITIES), "rows": len(df),
            "positives": int(df["label"].sum()), "features": rm.FEATURE_SETS[feature_set]})  # fmt: skip
        print(
            f"saved {path.name}: {len(df)} rows, {int(df['label'].sum())} positives, {path.stat().st_size // 1024} KiB"
        )


if __name__ == "__main__":
    main()
