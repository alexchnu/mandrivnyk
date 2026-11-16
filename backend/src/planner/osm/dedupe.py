"""Merge OSM objects that describe the same real-world place.

A landmark is often mapped several times (a node for the label, a way for the
building, a relation for the site). Objects are merged when they share a
normalised name *and* lie close to each other - unlike a name-only rule this
keeps distinct places with the same name in different parts of a city.
"""

from __future__ import annotations

import re
import unicodedata

import numpy as np
import pandas as pd

from ..geo import haversine_m

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_SPACE = re.compile(r"\s+")


def normalise_name(name: str) -> str:
    text = unicodedata.normalize("NFKD", name)
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).casefold()
    text = _PUNCT.sub(" ", text)
    text = _SPACE.sub(" ", text).strip()
    return text[4:] if text.startswith("the ") else text


def dedupe(df: pd.DataFrame, radius_m: float = 150.0) -> pd.DataFrame:
    """Keep one row per (normalised name, spatial cluster); the richest row wins."""
    if df.empty:
        return df
    work = df.copy()
    work["_norm"] = work["name"].map(normalise_name)
    has_wiki = work["tags"].str.contains('"wikidata"', regex=False)
    kind_rank = work["poi_id"].str[0].map({"r": 2, "w": 1, "n": 0}).fillna(0)
    work["_quality"] = has_wiki.astype(int) * 1000 + work["category"].notna() * 100 + work["n_tags"] + kind_rank
    keep: list[int] = []
    for _, grp in work.groupby("_norm", sort=False):
        if len(grp) == 1:
            keep.append(grp.index[0])
            continue
        grp = grp.sort_values("_quality", ascending=False)
        lat, lon = grp["lat"].to_numpy(), grp["lon"].to_numpy()
        taken = np.zeros(len(grp), bool)
        for i in range(len(grp)):
            if taken[i]:
                continue
            keep.append(grp.index[i])
            taken |= haversine_m(lat[i], lon[i], lat, lon) <= radius_m
    return work.loc[sorted(keep)].drop(columns=["_norm", "_quality"]).reset_index(drop=True)
