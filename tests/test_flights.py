"""Synthetic gap-splitting cases for flights.assign_flights."""

import pandas as pd
import pytest

from flighttrack import flights


def fixes(icao24: str, minutes: list, start="2026-09-20 10:00"):
    """Build a tiny fix table for one aircraft with fixes at the given minute offsets."""
    t0 = pd.Timestamp(start, tz="UTC")
    return pd.DataFrame({
        "icao24": icao24,
        "time": [t0 + pd.Timedelta(minutes=m) for m in minutes],
        "latitude": 40.0,
        "longitude": -74.0,
    })


def test_continuous_fixes_form_one_flight():
    df = flights.assign_flights(fixes("abc123", [0, 1, 2, 3, 4]))
    assert df["flight_id"].nunique() == 1
    assert df["flight_id"].iloc[0] == "abc123_20260920T100000Z"


def test_gap_longer_than_threshold_splits_into_two_flights():
    df = flights.assign_flights(fixes("abc123", [0, 1, 2, 60, 61, 62]), gap_minutes=30)
    assert df["flight_id"].nunique() == 2
    assert df["flight_id"].iloc[3] == "abc123_20260920T110000Z"


def test_gap_exactly_at_threshold_does_not_split():
    df = flights.assign_flights(fixes("abc123", [0, 30]), gap_minutes=30)
    assert df["flight_id"].nunique() == 1


def test_gap_just_over_threshold_splits():
    df = flights.assign_flights(fixes("abc123", [0, 30.01]), gap_minutes=30)
    assert df["flight_id"].nunique() == 2


def test_two_aircraft_are_never_merged():
    a = fixes("aaaaaa", [0, 1, 2])
    b = fixes("bbbbbb", [0, 1, 2])
    df = flights.assign_flights(pd.concat([a, b]))
    assert df["flight_id"].nunique() == 2
    assert set(df[df["icao24"] == "aaaaaa"]["flight_id"]) == {"aaaaaa_20260920T100000Z"}


def test_out_of_order_input_is_sorted_before_splitting():
    # Same fixes, shuffled.  Grouping must depend on time, not row order.
    df = fixes("abc123", [62, 0, 61, 2, 60, 1])
    out = flights.assign_flights(df, gap_minutes=30)
    assert out["flight_id"].nunique() == 2
    assert out["time"].is_monotonic_increasing


def test_three_legs_with_an_interleaved_aircraft():
    a = fixes("aaaaaa", [0, 5, 10, 100, 105, 200, 205])   # three legs
    b = fixes("bbbbbb", [0, 50, 100, 150])                # gaps of 50 -> four legs
    out = flights.assign_flights(pd.concat([a, b]), gap_minutes=30)
    assert out[out["icao24"] == "aaaaaa"]["flight_id"].nunique() == 3
    assert out[out["icao24"] == "bbbbbb"]["flight_id"].nunique() == 4
    assert flights.flight_count(out) == 7


def test_empty_input():
    empty = pd.DataFrame({"icao24": pd.Series(dtype="str"), "time": pd.Series(dtype="datetime64[ns, UTC]")})
    out = flights.assign_flights(empty)
    assert "flight_id" in out.columns
    assert len(out) == 0


@pytest.mark.parametrize("gap,expected", [(5, 3), (15, 2), (60, 1)])
def test_threshold_changes_flight_count(gap, expected):
    # Fixes at 0, 10, 30: gaps of 10 and 20 minutes.
    df = flights.assign_flights(fixes("abc123", [0, 10, 30]), gap_minutes=gap)
    assert df["flight_id"].nunique() == expected
