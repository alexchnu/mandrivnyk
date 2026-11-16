"""Small geodesy helpers (WGS84, spherical approximation)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

EARTH_RADIUS_M = 6_371_008.8


@dataclass(frozen=True, slots=True)
class BBox:
    south: float
    west: float
    north: float
    east: float

    def contains(self, lat: float, lon: float) -> bool:
        return self.south <= lat <= self.north and self.west <= lon <= self.east

    @classmethod
    def around(cls, lats, lons, margin_m: float) -> "BBox":
        lats, lons = np.asarray(lats, float), np.asarray(lons, float)
        dlat = np.degrees(margin_m / EARTH_RADIUS_M)
        dlon = dlat / max(np.cos(np.radians(lats.mean())), 1e-6)
        return cls(lats.min() - dlat, lons.min() - dlon, lats.max() + dlat, lons.max() + dlon)


def haversine_m(lat1, lon1, lat2, lon2):
    """Great-circle distance in metres; broadcasts over numpy arrays."""
    lat1, lon1, lat2, lon2 = (np.radians(np.asarray(x, float)) for x in (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_M * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def distance_matrix_m(lats, lons) -> np.ndarray:
    """Symmetric great-circle distance matrix for a set of points."""
    lats, lons = np.asarray(lats, float), np.asarray(lons, float)
    return haversine_m(lats[:, None], lons[:, None], lats[None, :], lons[None, :])
