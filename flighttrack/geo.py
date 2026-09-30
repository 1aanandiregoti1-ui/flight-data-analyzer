"""Pure geometry on a spherical Earth.

No network, no file I/O, no pandas — just numbers in, numbers out.
Everything in here is tested against hand-checked values in tests/test_geo.py.

Why not plain Pythagoras on (latitude, longitude)?  Because a degree of
longitude is not a fixed distance: it is ~111 km at the equator and shrinks
to zero at the poles.  The haversine formula works on the sphere directly,
so it gets this right everywhere.
"""

import math

EARTH_RADIUS_KM = 6371.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres between two (lat, lon) points in degrees.

    d = 2R * asin( sqrt( sin^2(dphi/2) + cos(phi1) * cos(phi2) * sin^2(dlambda/2) ) )
    """
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)

    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    # Clamp guards against a rounding error pushing sqrt(a) a hair above 1.0.
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def track_distance_km(points) -> float:
    """Sum of haversine distances between consecutive (lat, lon) pairs.

    `points` is any sequence of (lat, lon) tuples in flight order.
    Zero or one point gives 0.0 — you cannot travel anywhere with one fix.
    """
    total = 0.0
    for (lat1, lon1), (lat2, lon2) in zip(points, points[1:]):
        total += haversine_km(lat1, lon1, lat2, lon2)
    return total


def initial_bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Compass bearing (0-360, clockwise from north) from point 1 toward point 2."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_lambda = math.radians(lon2 - lon1)

    x = math.sin(d_lambda) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(d_lambda)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def detour_ratio(track_km: float, gc_km: float) -> float:
    """How much further than the straight line a flight went: track / great-circle.

    1.0 means a perfectly direct route.  Returns NaN when the endpoints are the
    same place (gc_km == 0), because the ratio is undefined there — an aircraft
    circling and landing where it started has no "direct route" to compare to.
    """
    if gc_km <= 0.0:
        return math.nan
    return track_km / gc_km
