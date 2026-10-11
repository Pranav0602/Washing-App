"""Spatial helpers for service zones.

A point-in-polygon test runs only after an indexed bounding-box pre-filter, so the
expensive part touches a handful of candidate zones rather than the whole table.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Iterable, Sequence
from typing import Any

logger = logging.getLogger("apps.locations.geo")

EARTH_RADIUS_KM = 6371.0088

Point = tuple[float, float]
Ring = Sequence[Point]


class InvalidGeometry(ValueError):
    """Raised when stored GeoJSON cannot be interpreted."""


def normalise_phone_geojson(geometry: dict[str, Any]) -> list[list[Point]]:
    """Extract a list of polygon rings from a GeoJSON Polygon/MultiPolygon.

    Coordinates are ``[lng, lat]`` in GeoJSON order and are converted to
    ``(lat, lng)`` internally so every other function in this module speaks
    latitude-first and matches the database columns.
    """
    if not geometry:
        return []

    gtype = (geometry.get("type") or "").lower()
    coordinates = geometry.get("coordinates")

    if gtype == "polygon":
        raw_rings = coordinates or []
    elif gtype == "multipolygon":
        raw_rings = [ring for polygon in (coordinates or []) for ring in polygon]
    else:
        raise InvalidGeometry(f"Unsupported geometry type {gtype!r}; expected Polygon or MultiPolygon")

    rings: list[list[Point]] = []
    for ring in raw_rings:
        points = [(float(point[1]), float(point[0])) for point in ring]
        if len(points) >= 4:
            rings.append(points)
    return rings


def compute_bbox(rings: Iterable[Ring]) -> tuple[float, float, float, float]:
    """Return ``(min_lat, min_lng, max_lat, max_lng)`` across every ring."""
    lats: list[float] = []
    lngs: list[float] = []
    for ring in rings:
        for lat, lng in ring:
            lats.append(lat)
            lngs.append(lng)
    if not lats:
        raise InvalidGeometry("Cannot compute a bounding box from an empty geometry")
    return (min(lats), min(lngs), max(lats), max(lngs))


def bbox_contains(
    bbox: tuple[float, float, float, float] | None, lat: float, lng: float
) -> bool:
    """Cheap pre-filter. A zone with no bbox is treated as not matching."""
    if bbox is None:
        return False
    min_lat, min_lng, max_lat, max_lng = bbox
    return min_lat <= lat <= max_lat and min_lng <= lng <= max_lng


def point_in_ring(lat: float, lng: float, ring: Ring) -> bool:
    """Ray-casting point-in-polygon for a single ring.

    The half-open rule means a point exactly on a horizontal edge is excluded, which
    keeps neighbouring zones from both claiming the same address.
    """
    inside = False
    count = len(ring)
    if count < 3:
        return False

    j = count - 1
    for i in range(count):
        lat_i, lng_i = ring[i]
        lat_j, lng_j = ring[j]
        if (lat_i > lat) != (lat_j > lat):
            # Latitude of the edge crossing at this longitude.
            slope = (lng_j - lng_i) / (lat_j - lat_i)
            x_at_lat = lng_i + slope * (lat - lat_i)
            if lng < x_at_lat:
                inside = not inside
        j = i
    return inside


def point_in_geometry(lat: float, lng: float, rings: list[Ring]) -> bool:
    """A point is inside if any outer ring contains it and no hole excludes it."""
    if not rings:
        return False
    if not point_in_ring(lat, lng, rings[0]):
        return False
    # Subsequent rings are holes.
    return not any(point_in_ring(lat, lng, hole) for hole in rings[1:])


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance.

    Used only for display and as a fallback ETA input. Dispatch ranking must not
    rely on straight-line distance alone, per the PDF.
    """
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lng2 - lng1)

    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def zone_bbox(zone) -> tuple[float, float, float, float] | None:
    if None in (
        zone.bbox_min_lat,
        zone.bbox_min_lng,
        zone.bbox_max_lat,
        zone.bbox_max_lng,
    ):
        return None
    return (zone.bbox_min_lat, zone.bbox_min_lng, zone.bbox_max_lat, zone.bbox_max_lng)


def zone_contains_point(zone, lat: float, lng: float) -> bool:
    """Full containment test: bbox pre-filter, then point-in-polygon."""
    if not bbox_contains(zone_bbox(zone), lat, lng):
        return False
    try:
        rings = normalise_phone_geojson(zone.polygon_geojson)
    except InvalidGeometry:
        # A zone whose polygon cannot be parsed must not silently accept every point.
        logger.error("zone %s has unreadable geometry; falling back to bbox only", zone.code)
        return True
    if not rings:
        return True
    return point_in_geometry(lat, lng, rings)