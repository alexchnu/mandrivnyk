"""Loader for the Flickr user-visit datasets of Lim et al. (IJCAI'15, CIKM'16)."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import unquote

import pandas as pd

from .paths import FLICKR_DIR

_IJCAI = FLICKR_DIR / "ijcai15" / "data-ijcai15"
_CIKM = FLICKR_DIR / "cikm16" / "data-cikm16"


@dataclass(frozen=True, slots=True)
class CitySpec:
    key: str
    title: str
    poi_file: str
    visits_file: str
    pbf: str  # Geofabrik extract containing the city
    source: str = "ijcai15"


CITIES: dict[str, CitySpec] = {
    c.key: c
    for c in (
        CitySpec("edinburgh", "Edinburgh", "POI-Edin.csv", "userVisits-Edin.csv", "scotland"),
        CitySpec("glasgow", "Glasgow", "POI-Glas.csv", "userVisits-Glas.csv", "scotland"),
        CitySpec("budapest", "Budapest", "POI-Buda.csv", "userVisits-Buda-allPOI.csv", "hungary"),
        CitySpec("vienna", "Vienna", "POI-Vien.csv", "userVisits-Vien-allPOI.csv", "austria"),
        CitySpec("toronto", "Toronto", "POI-Toro.csv", "userVisits-Toro.csv", "ontario"),
        CitySpec("osaka", "Osaka", "POI-Osak.csv", "userVisits-Osak.csv", "kansai"),
        CitySpec("delhi", "Delhi", "POI-Delh.csv", "userVisits-Delh-allPOI.csv", "northern-zone"),
        CitySpec("perth", "Perth", "POI-Pert.csv", "userVisits-Pert-allPOI.csv", "australia"),
        CitySpec("melbourne", "Melbourne", "POI-Melb.csv", "userVisits-Melb-allPOI.csv", "australia", "cikm16"),
    )
}


def load_pois(city: str) -> pd.DataFrame:
    """Flickr POI list: ``flickr_id, title, name, lat, lon, theme``.

    ``title`` is the raw identifier from the dataset (for the IJCAI'15 cities it
    is the title of the English Wikipedia article), ``name`` is human readable.
    """
    spec = CITIES[city]
    base = _IJCAI / "poiList-ijcai15" if spec.source == "ijcai15" else _CIKM
    df = pd.read_csv(base / spec.poi_file, sep=";")
    df = df.rename(columns={"poiID": "flickr_id", "poiName": "name", "long": "lon"})
    df["title"] = df["name"]
    df["name"] = df["name"].map(unquote).str.replace("_", " ").str.strip()
    return df[["flickr_id", "title", "name", "lat", "lon", "theme"]]


def load_visits(city: str) -> pd.DataFrame:
    """Photo-level visits: ``user, ts, flickr_id, seq``."""
    spec = CITIES[city]
    base = _IJCAI / "userVisits-ijcai15" if spec.source == "ijcai15" else _CIKM
    df = pd.read_csv(base / spec.visits_file, sep=";")
    df = df.rename(columns={"userID": "user", "dateTaken": "ts", "poiID": "flickr_id", "seqID": "seq"})
    return df[["user", "ts", "flickr_id", "seq"]]


def load_sequences(city: str, min_len: int = 1) -> pd.DataFrame:
    """Travel sequences as ordered lists of distinct POIs.

    Returns one row per sequence: ``seq, user, pois (list), start_ts, end_ts``.
    Consecutive photos of the same POI are merged; a POI revisited later in the
    same sequence is kept only at its first position.
    """
    visits = load_visits(city).sort_values(["seq", "ts"])
    out = []
    for seq, grp in visits.groupby("seq", sort=True):
        pois = list(dict.fromkeys(grp["flickr_id"].tolist()))
        if len(pois) >= min_len:
            out.append(
                {"seq": seq, "user": grp["user"].iloc[0], "pois": pois,
                 "start_ts": int(grp["ts"].iloc[0]), "end_ts": int(grp["ts"].iloc[-1])}
            )
    return pd.DataFrame(out)


def poi_popularity(city: str) -> pd.DataFrame:
    """Per-POI popularity from Flickr: distinct users, sequences and photos."""
    visits = load_visits(city)
    grp = visits.groupby("flickr_id")
    return pd.DataFrame(
        {"users": grp["user"].nunique(), "sequences": grp["seq"].nunique(), "photos": grp.size()}
    ).reset_index()
