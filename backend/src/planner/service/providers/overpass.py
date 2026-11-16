"""POI download from the Overpass API with mirror fail-over."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict

import httpx

from ...osm.rows import build_row
from ...taxonomy import RULES
from ..config import get_settings
from .http import ProviderError, client

log = logging.getLogger(__name__)
_NOTABLE_KEYS = ("building", "historic", "tourism", "man_made", "leisure", "natural", "place")


def build_query(lat: float, lon: float, radius_m: float, timeout_s: int = 40) -> str:
    """One query for every tag of the taxonomy plus named objects with a Wikidata id."""
    values: dict[str, list[str]] = defaultdict(list)
    for rule in RULES:
        values[rule.key].append(rule.value)
    around = f"(around:{radius_m:.0f},{lat:.6f},{lon:.6f})"
    parts = [f'nwr["name"]["{key}"~"^({"|".join(vals)})$"]{around};' for key, vals in values.items()]
    parts += [f'nwr["name"]["wikidata"]["{key}"]{around};' for key in _NOTABLE_KEYS]
    return f"[out:json][timeout:{timeout_s}];\n(\n  " + "\n  ".join(parts) + "\n);\nout center tags;"


def parse_elements(elements: list[dict]) -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()
    for el in elements:
        kind = {"node": "n", "way": "w", "relation": "r"}.get(el.get("type", ""))
        centre = el if kind == "n" else el.get("center", {})
        lat, lon = centre.get("lat"), centre.get("lon")
        if kind is None or lat is None or lon is None:
            continue
        row = build_row(kind, int(el["id"]), float(lat), float(lon), el.get("tags") or {})
        if row is not None and row["poi_id"] not in seen:
            seen.add(row["poi_id"])
            rows.append(row)
    return rows


async def fetch_rows(lat: float, lon: float, radius_m: float, budget_s: float = 45.0) -> list[dict]:
    """Try every configured mirror in turn within a total time budget.

    Raises ``ProviderError`` when no mirror answers: a request must fail in
    bounded time instead of hanging while the public servers are overloaded.
    """
    query = build_query(lat, lon, radius_m, timeout_s=25)
    errors: list[str] = []
    deadline = asyncio.get_running_loop().time() + budget_s
    for url in get_settings().overpass_urls:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining < 3:
            errors.append("time budget exhausted")
            break
        try:
            resp = await client().post(url, data={"data": query}, timeout=min(30.0, remaining))
        except httpx.HTTPError as exc:
            errors.append(f"{url}: {type(exc).__name__}")
            continue
        if resp.status_code == 200:
            try:
                return parse_elements(resp.json().get("elements", []))
            except ValueError:
                errors.append(f"{url}: invalid JSON")
                continue
        errors.append(f"{url}: HTTP {resp.status_code}")
    log.warning("overpass unavailable: %s", "; ".join(errors))
    raise ProviderError("Map data service is temporarily unavailable")
