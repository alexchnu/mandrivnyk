import json

import pandas as pd

from planner.osm.dedupe import dedupe, normalise_name
from planner.osm.rows import build_row
from planner.taxonomy import classify


def test_classification_priorities():
    assert classify({"tourism": "museum", "amenity": "cafe"}).category == "culture"
    assert classify({"amenity": "place_of_worship", "historic": "monument"}).category == "religion"
    assert classify({"shop": "bakery"}) is None
    assert classify({"tourism": "museum"}).visit_minutes == 75


def test_notable_fallback_only_for_physical_places():
    assert classify({"building": "yes", "wikidata": "Q1"}).category == "landmark"
    assert classify({"railway": "station", "wikipedia": "uk:Вокзал"}).category == "landmark"
    assert classify({"place": "city", "wikidata": "Q157725", "tourism": "yes"}) is None  # the city itself
    assert classify({"boundary": "administrative", "wikidata": "Q1", "leisure": "yes"}) is None
    assert classify({"amenity": "school", "wikidata": "Q1"}) is None
    assert classify({"highway": "residential", "wikidata": "Q1"}) is None


def test_build_row_requires_name_and_relevance():
    assert build_row("n", 1, 1.0, 2.0, {"tourism": "museum"}) is None
    assert build_row("n", 1, 1.0, 2.0, {"name": "X", "office": "it"}) is None
    row = build_row("w", 7, 1.0, 2.0, {"name": "X", "tourism": "museum", "secret": "1"})
    assert row["poi_id"] == "w7" and row["category"] == "culture" and "secret" not in row["tags"]


def _frame(rows):
    out = []
    for i, (kind, name, lat, lon, tags) in enumerate(rows):
        out.append({"poi_id": f"{kind}{i}", "name": name, "lat": lat, "lon": lon, "category": "culture",
                    "n_tags": len(tags) + 1, "tags": json.dumps({"name": name, **tags})})  # fmt: skip
    return pd.DataFrame(out)


def test_normalise_name():
    assert normalise_name("The  Café-«Müller»") == "cafe muller"


def test_dedupe_same_name_nearby_but_not_far():
    df = _frame([
        ("n", "Музей", 48.2900, 25.9300, {}),
        ("w", "Музей", 48.2901, 25.9301, {"wikidata": "Q5"}),  # same place, richer
        ("n", "Музей", 48.3300, 25.9300, {}),  # 4 km away: a different museum
    ])  # fmt: skip
    out = dedupe(df)
    assert sorted(out["poi_id"]) == ["n2", "w1"]


def test_dedupe_same_wikidata_item():
    df = _frame([
        ("w", "Університет, головний корпус", 48.2970, 25.9240, {"wikidata": "Q9", "website": "x", "image": "y"}),
        ("w", "Університет, корпус 4", 48.2950, 25.9300, {"wikidata": "Q9"}),
        ("w", "Університет, філія", 48.4500, 25.9300, {"wikidata": "Q9"}),  # another town: kept
        ("n", "Ратуша", 48.2920, 25.9350, {"wikidata": "Q10"}),
    ])  # fmt: skip
    out = dedupe(df)
    assert sorted(out["poi_id"]) == ["n3", "w0", "w2"]
