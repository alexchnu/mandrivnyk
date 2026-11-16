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
    return text.removeprefix("the ")


def _wikidata_id(tags_json: str) -> str:
    start = tags_json.find('"wikidata": "')
    if start < 0:
        return ""
    start += len('"wikidata": "')
    return tags_json[start : tags_json.find('"', start)].split(";")[0].strip()


def _cluster_keep(grp: pd.DataFrame, radius_m: float) -> list[int]:
    """Greedy spatial clustering: the best row of every cluster survives."""
    grp = grp.sort_values("_quality", ascending=False)
    lat, lon = grp["lat"].to_numpy(), grp["lon"].to_numpy()
    taken = np.zeros(len(grp), bool)
    keep: list[int] = []
    for i in range(len(grp)):
        if taken[i]:
            continue
        keep.append(grp.index[i])
        taken |= haversine_m(lat[i], lon[i], lat, lon) <= radius_m
    return keep


def dedupe(df: pd.DataFrame, radius_m: float = 150.0, entity_radius_m: float = 1500.0) -> pd.DataFrame:
    """Keep one row per real-world place; the richest row wins.

    Two passes: rows with the same normalised name within ``radius_m``, then rows
    that point to the same Wikidata item within ``entity_radius_m`` (a university
    whose every building carries the university's id is one sight, not ten).
    """
    if df.empty:
        return df
    work = df.copy()
    work["_norm"] = work["name"].map(normalise_name)
    work["_qid"] = work["tags"].map(_wikidata_id)
    kind_rank = work["poi_id"].str[0].map({"r": 2, "w": 1, "n": 0}).fillna(0)
    work["_quality"] = (
        (work["_qid"] != "").astype(int) * 1000 + work["category"].notna() * 100 + work["n_tags"] + kind_rank
    )
    keep: list[int] = []
    for _, grp in work.groupby("_norm", sort=False):
        keep.extend([grp.index[0]] if len(grp) == 1 else _cluster_keep(grp, radius_m))
    work = work.loc[sorted(keep)]
    keep = work.index[work["_qid"] == ""].tolist()
    for _, grp in work[work["_qid"] != ""].groupby("_qid", sort=False):
        keep.extend([grp.index[0]] if len(grp) == 1 else _cluster_keep(grp, entity_radius_m))
    return work.loc[sorted(keep)].drop(columns=["_norm", "_qid", "_quality"]).reset_index(drop=True)
