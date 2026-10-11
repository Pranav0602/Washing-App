"""Geometry helpers shared by the seed command and verification scripts.

Kept in an importable module so the smoke tests can build a throwaway zone with the
same geometry logic the seed command uses, rather than duplicating it.
"""

from __future__ import annotations

import math


def square_polygon(lat: float, lng: float, half_km: float = 3.0) -> dict:
    """A GeoJSON square around a centre point, sized in kilometres.

    GeoJSON orders coordinates as ``[lng, lat]`` and requires the ring to be closed.
    """
    lat_delta = half_km / 111.32
    lng_delta = half_km / (111.32 * math.cos(math.radians(lat)))

    min_lat, max_lat = lat - lat_delta, lat + lat_delta
    min_lng, max_lng = lng - lng_delta, lng + lng_delta

    ring = [
        [min_lng, min_lat],
        [max_lng, min_lat],
        [max_lng, max_lat],
        [min_lng, max_lat],
        [min_lng, min_lat],
    ]
    return {"type": "Polygon", "coordinates": [ring]}


def bbox_from_polygon(polygon: dict) -> tuple[float, float, float, float]:
    """``(min_lat, min_lng, max_lat, max_lng)`` for a GeoJSON Polygon."""
    ring = polygon["coordinates"][0]
    lats = [point[1] for point in ring]
    lngs = [point[0] for point in ring]
    return (min(lats), min(lngs), max(lats), max(lngs))