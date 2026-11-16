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


async def fetch_rows(lat: float, lon: float, radius_m: float) -> list[dict]:
    """Try every configured mirror in turn; raise ``ProviderError`` when all fail."""
    query = build_query(lat, lon, radius_m)
    errors: list[str] = []
    for url in get_settings().overpass_urls:
        for attempt in range(2):
            try:
                resp = await client().post(url, data={"data": query}, timeout=60)
            except httpx.HTTPError as exc:
                errors.append(f"{url}: {type(exc).__name__}")
                break
            if resp.status_code == 200:
                try:
                    return parse_elements(resp.json().get("elements", []))
                except ValueError:
                    errors.append(f"{url}: invalid JSON")
                    break
            errors.append(f"{url}: HTTP {resp.status_code}")
            if resp.status_code in (429, 504) and attempt == 0:
                await asyncio.sleep(3)
                continue
            break
    log.warning("overpass unavailable: %s", "; ".join(errors))
    raise ProviderError("Map data service is temporarily unavailable")
