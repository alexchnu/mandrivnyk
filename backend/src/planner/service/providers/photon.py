"""Place search (geocoding) through Photon - a search-as-you-type service on OSM data.

The public Nominatim instance forbids autocomplete, which the coursework used
directly from the browser; Photon is designed for it. Requests still go through
the server so that they can be cached and throttled.
"""

from __future__ import annotations

import httpx

from ..config import get_settings
from .http import ProviderError, client

_PLACE_TYPES = {
    "city",
    "town",
    "village",
    "district",
    "locality",
    "county",
    "state",
    "country",
    "borough",
    "suburb",
}


def _label(props: dict) -> str:
    parts = [props.get("name"), props.get("state") or props.get("county"), props.get("country")]
    seen: list[str] = []
    for part in parts:
        if part and part not in seen:
            seen.append(part)
    return ", ".join(seen)


async def search(query: str, lang: str = "default", limit: int = 6) -> list[dict]:
    params: dict[str, str | int | list[str]] = {
        "q": query, "limit": limit * 2, "layer": ["city", "district", "locality", "county", "state"],
    }  # fmt: skip
    if lang in ("en", "de", "fr"):
        params["lang"] = lang
    try:
        resp = await client().get(f"{get_settings().photon_url}/api", params=params)
        resp.raise_for_status()
        features = resp.json().get("features", [])
    except (httpx.HTTPError, ValueError) as exc:
        raise ProviderError("Place search is temporarily unavailable") from exc
    out: list[dict] = []
    seen: set[str] = set()
    for feat in features:
        props = feat.get("properties", {})
        coords = feat.get("geometry", {}).get("coordinates")
        if not coords or not props.get("name"):
            continue
        label = _label(props)
        if label in seen:
            continue
        seen.add(label)
        out.append(
            {
                "name": props["name"],
                "label": label,
                "country": props.get("country", ""),
                "country_code": (props.get("countrycode") or "").lower(),
                "kind": props.get("type") or props.get("osm_value", ""),
                "lat": float(coords[1]),
                "lon": float(coords[0]),
                "bbox": props.get("extent"),
            }  # fmt: skip
        )
        if len(out) >= limit:
            break
    return out
