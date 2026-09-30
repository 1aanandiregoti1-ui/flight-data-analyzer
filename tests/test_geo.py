"""Hand-checked values for the geometry functions.

Expected distances come from published airport coordinates and the standard
great-circle figures for each city pair; tolerances allow for the spherical
Earth approximation (real Earth is ~0.3% flatter at the poles).
"""

import math

import pytest

from flighttrack import geo

ATL = (33.6407, -84.4277)
LHR = (51.4700, -0.4543)
JFK = (40.6413, -73.7781)
LAX = (33.9416, -118.4085)
SYD = (-33.9399, 151.1753)


def test_atlanta_to_heathrow_is_about_6760_km():
    # The blueprint's reference pair: "within a few km of 6,760".
    d = geo.haversine_km(*ATL, *LHR)
    assert d == pytest.approx(6760, abs=15)


def test_jfk_to_lax_is_about_3980_km():
    d = geo.haversine_km(*JFK, *LAX)
    assert d == pytest.approx(3983, abs=15)


def test_southern_hemisphere_and_dateline_side():
    # LAX -> Sydney crosses the equator and the 180th meridian region.
    d = geo.haversine_km(*LAX, *SYD)
    assert d == pytest.approx(12050, abs=40)


def test_same_point_is_zero():
    assert geo.haversine_km(*ATL, *ATL) == 0.0


def test_one_degree_of_latitude_is_about_111_km():
    # 2 * pi * 6371 / 360 = 111.19 km — a number you can check on paper.
    assert geo.haversine_km(0, 0, 1, 0) == pytest.approx(111.19, abs=0.01)


def test_one_degree_of_longitude_shrinks_away_from_the_equator():
    # This is why Pythagoras on lat/lon is wrong: at 60N a degree of longitude
    # is half what it is at the equator (cos 60 = 0.5).
    at_equator = geo.haversine_km(0, 0, 0, 1)
    at_60_north = geo.haversine_km(60, 0, 60, 1)
    assert at_60_north == pytest.approx(at_equator / 2, rel=1e-3)


def test_distance_is_symmetric():
    assert geo.haversine_km(*ATL, *LHR) == pytest.approx(geo.haversine_km(*LHR, *ATL))


def test_antipodal_points_are_half_the_circumference():
    # Rounding can push sqrt(a) a hair above 1; asin must not blow up.
    d = geo.haversine_km(0, 0, 0, 180)
    assert d == pytest.approx(math.pi * geo.EARTH_RADIUS_KM, rel=1e-9)


def test_track_distance_sums_segments():
    # Three points due north of each other, one degree apart: 2 x 111.19 km.
    points = [(0, 0), (1, 0), (2, 0)]
    assert geo.track_distance_km(points) == pytest.approx(2 * 111.19, abs=0.02)


def test_track_distance_with_a_detour_exceeds_the_straight_line():
    # Go 1 degree east, then 1 degree north, versus the diagonal.
    detour = geo.track_distance_km([(0, 0), (0, 1), (1, 1)])
    direct = geo.haversine_km(0, 0, 1, 1)
    assert detour > direct
    assert geo.detour_ratio(detour, direct) == pytest.approx(math.sqrt(2), rel=0.01)


def test_track_distance_of_fewer_than_two_points_is_zero():
    assert geo.track_distance_km([]) == 0.0
    assert geo.track_distance_km([(10, 10)]) == 0.0


def test_detour_ratio_is_nan_when_endpoints_coincide():
    assert math.isnan(geo.detour_ratio(50.0, 0.0))


def test_bearing_cardinal_directions():
    assert geo.initial_bearing_deg(0, 0, 1, 0) == pytest.approx(0.0)     # north
    assert geo.initial_bearing_deg(0, 0, 0, 1) == pytest.approx(90.0)    # east
    assert geo.initial_bearing_deg(0, 0, -1, 0) == pytest.approx(180.0)  # south
    assert geo.initial_bearing_deg(0, 0, 0, -1) == pytest.approx(270.0)  # west


def test_bearing_atl_to_lhr_is_northeast():
    # Great-circle initial course ATL -> LHR is about 045 degrees (northeast),
    # even though London is only 18 degrees further north — the shortest path
    # over a sphere bows toward the pole.
    assert geo.initial_bearing_deg(*ATL, *LHR) == pytest.approx(45, abs=1)
