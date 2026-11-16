"""Mapping from OpenStreetMap tags to tourist categories.

The taxonomy is the single source of truth for the service, the experiments
and the thesis text: every rule is ``(key, value) -> (category, subtype minutes)``.
"""

from __future__ import annotations

from dataclasses import dataclass

CATEGORIES: tuple[str, ...] = (
    "culture",
    "history",
    "landmark",
    "nature",
    "religion",
    "entertainment",
    "food",
    "nightlife",
    "shopping",
)


@dataclass(frozen=True, slots=True)
class Rule:
    key: str
    value: str
    category: str
    visit_minutes: int


# Order matters: the first matching rule wins, so specific rules go first.
RULES: tuple[Rule, ...] = (
    # culture
    Rule("tourism", "museum", "culture", 75),
    Rule("tourism", "gallery", "culture", 45),
    Rule("amenity", "arts_centre", "culture", 40),
    Rule("amenity", "library", "culture", 30),
    # entertainment
    Rule("amenity", "theatre", "entertainment", 120),
    Rule("amenity", "cinema", "entertainment", 120),
    Rule("tourism", "zoo", "entertainment", 150),
    Rule("tourism", "aquarium", "entertainment", 90),
    Rule("tourism", "theme_park", "entertainment", 180),
    Rule("leisure", "water_park", "entertainment", 150),
    Rule("leisure", "stadium", "entertainment", 45),
    Rule("amenity", "casino", "entertainment", 90),
    # religion
    Rule("amenity", "place_of_worship", "religion", 20),
    # history
    Rule("historic", "castle", "history", 90),
    Rule("historic", "palace", "history", 90),
    Rule("historic", "fort", "history", 60),
    Rule("historic", "archaeological_site", "history", 60),
    Rule("historic", "ruins", "history", 45),
    Rule("historic", "city_gate", "history", 15),
    Rule("historic", "monument", "history", 10),
    Rule("historic", "memorial", "history", 10),
    Rule("historic", "manor", "history", 45),
    Rule("historic", "ship", "history", 45),
    Rule("historic", "building", "history", 20),
    Rule("historic", "church", "religion", 20),
    Rule("historic", "monastery", "religion", 30),
    # nature
    Rule("leisure", "park", "nature", 45),
    Rule("leisure", "garden", "nature", 30),
    Rule("leisure", "nature_reserve", "nature", 60),
    Rule("tourism", "viewpoint", "nature", 15),
    Rule("natural", "beach", "nature", 60),
    Rule("natural", "peak", "nature", 60),
    # landmark
    Rule("tourism", "attraction", "landmark", 30),
    Rule("tourism", "artwork", "landmark", 10),
    Rule("man_made", "tower", "landmark", 30),
    Rule("man_made", "lighthouse", "landmark", 20),
    Rule("man_made", "bridge", "landmark", 15),
    Rule("amenity", "fountain", "landmark", 10),
    Rule("amenity", "townhall", "landmark", 20),
    Rule("place", "square", "landmark", 20),
    # food
    Rule("amenity", "restaurant", "food", 60),
    Rule("amenity", "cafe", "food", 30),
    # nightlife
    Rule("amenity", "bar", "nightlife", 45),
    Rule("amenity", "pub", "nightlife", 45),
    Rule("amenity", "nightclub", "nightlife", 90),
    # shopping
    Rule("shop", "mall", "shopping", 90),
    Rule("shop", "department_store", "shopping", 60),
    Rule("amenity", "marketplace", "shopping", 40),
)

# Keys whose presence makes an OSM object worth keeping in a raw extract.
RELEVANT_KEYS: frozenset[str] = frozenset(
    {r.key for r in RULES} | {"wikidata", "wikipedia", "building", "railway"}
)

_INDEX: dict[tuple[str, str], Rule] = {}
for _rule in RULES:
    _INDEX.setdefault((_rule.key, _rule.value), _rule)
_KEY_ORDER: tuple[str, ...] = tuple(dict.fromkeys(r.key for r in RULES))
_RULE_RANK: dict[Rule, int] = {r: i for i, r in enumerate(RULES)}


# Fallback: an object that has its own Wikipedia/Wikidata entry and is a physical
# place of one of these kinds is treated as a landmark even without a tourism tag
# (parliaments, notable hotels, university buildings, railway stations, ...).
NOTABLE = Rule("wikidata", "*", "landmark", 20)
_NOTABLE_KEYS = ("building", "historic", "tourism", "man_made", "leisure", "natural", "amenity")
# Everyday facilities are not sights even when someone linked them to Wikidata.
_NOT_NOTABLE_AMENITIES = frozenset({
    "school", "kindergarten", "hospital", "clinic", "doctors", "pharmacy", "bank", "fuel", "parking",
    "post_office", "police", "fire_station", "bus_station", "courthouse", "prison", "college",
})  # fmt: skip


def _is_notable_place(tags: dict[str, str]) -> bool:
    """A physical place with its own encyclopedia entry (not a settlement or an area)."""
    if "wikidata" not in tags and "wikipedia" not in tags:
        return False
    if "place" in tags or "boundary" in tags or "admin_level" in tags:
        return False  # the node of a city or district carries the city's own Wikidata id
    if tags.get("amenity") in _NOT_NOTABLE_AMENITIES:
        return False
    return any(k in tags for k in _NOTABLE_KEYS) or tags.get("railway") == "station"


def classify(tags: dict[str, str]) -> Rule | None:
    """Return the highest-priority rule matching ``tags`` or ``None``."""
    best: Rule | None = None
    for key in _KEY_ORDER:
        value = tags.get(key)
        if value is None:
            continue
        rule = _INDEX.get((key, value))
        if rule is not None and (best is None or _RULE_RANK[rule] < _RULE_RANK[best]):
            best = rule
    if best is None and _is_notable_place(tags):
        return NOTABLE
    return best
