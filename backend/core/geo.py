"""Haversine distance. No PostGIS; zones are radius-based circles."""

import math

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1, lng1, lat2, lng2) -> float:
    """Great-circle distance in kilometres between two WGS84 points."""
    if None in (lat1, lng1, lat2, lng2):
        return math.inf

    phi1, phi2 = math.radians(float(lat1)), math.radians(float(lat2))
    d_phi = phi2 - phi1
    d_lambda = math.radians(float(lng2) - float(lng1))

    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def within_radius_km(*, lat, lng, center_lat, center_lng, radius_km) -> bool:
    return haversine_km(lat, lng, center_lat, center_lng) <= float(radius_km)
