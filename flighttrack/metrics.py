"""Stage 3b: per-flight aggregates and distances.

Reads the fix-level table with flight ids, writes one row per flight.
Nulls are dropped per metric, never row-wise: a fix with no altitude still
counts toward distance and duration.  This module draws nothing.
"""

import logging
from pathlib import Path

import pandas as pd

from flighttrack import geo

log = logging.getLogger("flighttrack.metrics")

METRIC_COLUMNS = [
    "flight_id", "icao24", "callsign", "origin_country",
    "n_points", "start_time", "end_time", "duration_min",
    "track_distance_km", "gc_distance_km", "detour_ratio",
    "max_altitude_m", "max_altitude_ft", "mean_speed_ms", "mean_speed_kt",
    "n_altitude_fixes", "n_speed_fixes", "pct_on_ground",
]


def _mode_or_none(series: pd.Series):
    """Most common non-null value, or None.  Used for callsign, which can flicker."""
    values = series.dropna()
    return None if values.empty else values.mode().iloc[0]


def _one_flight(flight_id: str, g: pd.DataFrame) -> dict:
    points = list(zip(g["latitude"].tolist(), g["longitude"].tolist()))
    first, last = points[0], points[-1]

    track_km = geo.track_distance_km(points)
    gc_km = geo.haversine_km(first[0], first[1], last[0], last[1])

    # Nulls dropped per metric.  The _ft / _kt columns were converted in clean.
    altitude_m = g["geo_altitude_m"].dropna()
    altitude_ft = g["geo_altitude_ft"].dropna()
    speed_ms = g["velocity_ms"].dropna()
    speed_kt = g["velocity_kt"].dropna()
    start, end = g["time"].iloc[0], g["time"].iloc[-1]

    return {
        "flight_id": flight_id,
        "icao24": g["icao24"].iloc[0],
        "callsign": _mode_or_none(g["callsign"]),
        "origin_country": g["origin_country"].iloc[0],
        "n_points": len(g),
        "start_time": start,
        "end_time": end,
        "duration_min": (end - start).total_seconds() / 60.0,
        "track_distance_km": track_km,
        "gc_distance_km": gc_km,
        "detour_ratio": geo.detour_ratio(track_km, gc_km),
        "max_altitude_m": altitude_m.max() if not altitude_m.empty else None,
        "max_altitude_ft": altitude_ft.max() if not altitude_ft.empty else None,
        "mean_speed_ms": speed_ms.mean() if not speed_ms.empty else None,
        "mean_speed_kt": speed_kt.mean() if not speed_kt.empty else None,
        "n_altitude_fixes": len(altitude_m),
        "n_speed_fixes": len(speed_ms),
        "pct_on_ground": 100.0 * g["on_ground"].mean(),
    }


def flight_metrics(fixes: pd.DataFrame) -> pd.DataFrame:
    """One row per flight_id.  Input must be sorted by time within each flight."""
    if fixes.empty:
        return pd.DataFrame(columns=METRIC_COLUMNS)
    rows = [_one_flight(fid, g) for fid, g in fixes.groupby("flight_id", sort=False)]
    return pd.DataFrame(rows, columns=METRIC_COLUMNS)


def filter_flights(metrics: pd.DataFrame, min_points: int = 5, min_gc_km: float = 5.0) -> pd.DataFrame:
    """Keep flights with enough fixes to say something about.

    Very short groups are usually an aircraft glimpsed once at the edge of
    the box; tiny great-circle distances are aircraft that ended up where they
    started (holding, training circuits, or taxiing), where the detour ratio
    means nothing.  The drop counts are logged so they can be reported.
    """
    n = len(metrics)
    enough_points = metrics["n_points"] >= min_points
    went_somewhere = metrics["gc_distance_km"] >= min_gc_km
    kept = metrics[enough_points & went_somewhere].reset_index(drop=True)
    log.info(
        "filter: %d flights -> %d kept (%d with < %d fixes, %d with < %.0f km between endpoints)",
        n, len(kept), int((~enough_points).sum()), min_points, int((enough_points & ~went_somewhere).sum()), min_gc_km,
    )
    return kept


def save_metrics(metrics: pd.DataFrame, path: Path = Path("data/processed/metrics.csv")) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    metrics.to_csv(path, index=False)
    return path
