"""Haversine distance. No PostGIS; zones are radius-based circles."""

import math

from django.db.models import F, FloatField, Value
from django.db.models.functions import ASin, Cast, Cos, Radians, Sin, Sqrt

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


def distance_km_expression(lat, lng):
    """The same haversine, as a SQL expression over a model's `lat`/`lng`.

    Filtering a radius in Python means loading every row before pagination, so
    a list endpoint pays for the whole table on every request. Postgres has the
    trigonometry, so the distance can be an annotation: `.annotate(
    distance_km=distance_km_expression(...)).filter(distance_km__lte=radius)`.
    Rows with a null coordinate have no distance and must be excluded by the
    caller first.
    """
    phi1 = Value(math.radians(float(lat)), output_field=FloatField())
    lambda1 = Value(math.radians(float(lng)), output_field=FloatField())
    # `lat`/`lng` are Decimal columns; the trigonometry runs in float.
    phi2 = Radians(Cast(F("lat"), output_field=FloatField()))
    lambda2 = Radians(Cast(F("lng"), output_field=FloatField()))

    d_phi = phi2 - phi1
    d_lambda = lambda2 - lambda1
    # sin²(Δφ/2) + cos φ1 · cos φ2 · sin²(Δλ/2)
    half_d_phi = Sin(d_phi / 2)
    half_d_lambda = Sin(d_lambda / 2)
    a = half_d_phi * half_d_phi + Cos(phi1) * Cos(phi2) * half_d_lambda * half_d_lambda
    return 2 * EARTH_RADIUS_KM * ASin(Sqrt(a))
