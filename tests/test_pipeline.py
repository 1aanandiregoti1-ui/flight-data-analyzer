"""End-to-end run over synthetic raw data, and the collector's error handling.

Nothing here touches the network.  The synthetic aircraft flies a known path
so the metrics can be checked against numbers worked out by hand.
"""

import math

import pandas as pd
import pytest

from flighttrack import analyze, clean, collect, flights, geo, metrics


def state_row(icao24, t, lat, lon, alt_m=10000.0, speed_ms=230.0, callsign="TEST123 ", on_ground=False):
    """A raw state vector in the API's positional layout (18 fields)."""
    return [icao24, callsign, "United States", t, t, lon, lat, alt_m, on_ground,
            speed_ms, 45.0, 0.0, None, alt_m, "1200", False, 0, 3]


def synthetic_snapshots(n_polls=40, interval_s=15, t0=1_790_000_000):
    """Two aircraft: one flying due north 0.01 deg per poll, one stationary on the ground."""
    polls = []
    for i in range(n_polls):
        t = t0 + i * interval_s
        rows = [
            state_row("aaaaaa", t, 40.0 + 0.01 * i, -74.0),
            state_row("bbbbbb", t, 40.5, -74.5, alt_m=None, speed_ms=0.0, callsign=None, on_ground=True),
        ]
        # Every 4th poll the flying aircraft reports no position (null lat/lon).
        if i % 4 == 3:
            rows[0][5] = rows[0][6] = None
        polls.append((t, rows))
    return polls


def write_synthetic_raw(raw_dir):
    for t, rows in synthetic_snapshots():
        collect.write_raw(collect.rows_to_frame(t, rows), raw_dir, t)


def test_rows_to_frame_pads_short_rows_and_keeps_nulls():
    row17 = state_row("abc123", 1_790_000_000, 40.0, -74.0)[:17]  # no category field
    frame = collect.rows_to_frame(1_790_000_000, [row17])
    assert list(frame.columns) == collect.STATE_COLUMNS + ["snapshot_time"]
    assert pd.isna(frame.loc[0, "category"])
    assert pd.isna(frame.loc[0, "sensors"])


def test_write_raw_never_overwrites(tmp_path):
    frame = collect.rows_to_frame(1_790_000_000, [state_row("abc123", 1_790_000_000, 40.0, -74.0)])
    first = collect.write_raw(frame, tmp_path, 1_790_000_000)
    second = collect.write_raw(frame, tmp_path, 1_790_000_000)
    assert first != second
    assert first.exists() and second.exists()


def test_clean_strips_callsigns_drops_positionless_and_converts_units(tmp_path):
    write_synthetic_raw(tmp_path)
    raw = clean.load_raw(tmp_path)
    assert len(raw) == 80

    fixes = clean.clean(raw)
    # 10 of the flying aircraft's 40 polls had no position; the ground aircraft
    # never moves so its 40 identical fixes are... 40 distinct time_positions here.
    assert len(fixes) == 70
    assert set(fixes["callsign"].dropna()) == {"TEST123"}
    assert fixes["callsign"].isna().sum() == 40  # the ground aircraft has none

    flying = fixes[fixes["icao24"] == "aaaaaa"]
    assert flying["geo_altitude_ft"].iloc[0] == pytest.approx(32808.4)
    assert flying["velocity_kt"].iloc[0] == pytest.approx(447.08, abs=0.01)
    assert flying["velocity_kmh"].iloc[0] == pytest.approx(828.0)
    assert fixes["time"].dt.tz is not None


def test_metrics_match_hand_calculation(tmp_path):
    write_synthetic_raw(tmp_path)
    fixes = flights.assign_flights(clean.clean(clean.load_raw(tmp_path)))
    table = metrics.flight_metrics(fixes)
    assert len(table) == 2

    flying = table[table["icao24"] == "aaaaaa"].iloc[0]
    # Polls 0..39, but every 4th (3, 7, ..., 39) has no position, so the last
    # fix is poll 38 at latitude 40.38.  Straight north from 40.00 to 40.38:
    # 0.38 deg x 111.19 km/deg = 42.25 km, and a straight line has detour ratio 1.
    assert flying["n_points"] == 30
    assert flying["gc_distance_km"] == pytest.approx(0.38 * 111.19, abs=0.05)
    assert flying["track_distance_km"] == pytest.approx(flying["gc_distance_km"], rel=1e-9)
    assert flying["detour_ratio"] == pytest.approx(1.0)
    assert flying["duration_min"] == pytest.approx(38 * 15 / 60)  # poll 0 to poll 38 = 570 s
    assert flying["max_altitude_ft"] == pytest.approx(32808.4)
    assert flying["mean_speed_kt"] == pytest.approx(447.08, abs=0.01)
    assert flying["callsign"] == "TEST123"
    assert flying["pct_on_ground"] == 0.0

    ground = table[table["icao24"] == "bbbbbb"].iloc[0]
    assert ground["gc_distance_km"] == 0.0
    assert math.isnan(ground["detour_ratio"])
    assert pd.isna(ground["max_altitude_ft"])   # null dropped per metric, row kept
    assert ground["mean_speed_kt"] == 0.0
    assert ground["pct_on_ground"] == 100.0


def test_filter_drops_stationary_and_sparse_flights(tmp_path):
    write_synthetic_raw(tmp_path)
    fixes = flights.assign_flights(clean.clean(clean.load_raw(tmp_path)))
    table = metrics.flight_metrics(fixes)
    kept = metrics.filter_flights(table, min_points=5, min_gc_km=5.0)
    assert list(kept["icao24"]) == ["aaaaaa"]
    assert metrics.filter_flights(table, min_points=31).empty


def test_analyze_end_to_end_writes_metrics_and_figures(tmp_path):
    raw, processed, figures = tmp_path / "raw", tmp_path / "processed", tmp_path / "figures"
    write_synthetic_raw(raw)
    kept = analyze.run(raw, processed, figures, gap_minutes=30, min_points=5, min_gc_km=5.0)
    assert len(kept) == 1
    assert (processed / "metrics.csv").exists()
    assert (processed / "flights.parquet").exists()
    pngs = sorted(p.name for p in figures.glob("*.png"))
    assert pngs == sorted([
        "flight_paths_map.png", "altitude_profiles.png", "detour_ratio_hist.png",
        "distance_vs_duration.png", "traffic_by_hour.png", "altitude_vs_speed.png",
    ])


# --------------------------------------------------------------------------- #
# Collector behaviour against a scripted API
# --------------------------------------------------------------------------- #

class ScriptedResponse:
    def __init__(self, status, payload=None, headers=None):
        self.status_code = status
        self._payload = payload or {}
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise collect.requests.HTTPError(f"{self.status_code}")

    def json(self):
        return self._payload


class ScriptedSession:
    """Returns the next scripted response on each GET and records the calls."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params, headers, timeout):
        self.calls.append({"params": params, "headers": headers})
        return self.responses.pop(0)


class FakeTokenManager:
    def __init__(self):
        self.tokens = iter(["old", "new"])
        self.current = next(self.tokens)
        self.invalidated = 0

    def auth_headers(self):
        return {"Authorization": f"Bearer {self.current}"}

    def invalidate(self):
        self.invalidated += 1
        self.current = next(self.tokens)


def ok(t=1_790_000_000, remaining="3999"):
    rows = [state_row("abc123", t, 40.0, -74.0)]
    return ScriptedResponse(200, {"time": t, "states": rows}, {"X-Rate-Limit-Remaining": remaining})


def test_fetch_states_passes_bbox_and_returns_rows():
    session = ScriptedSession([ok()])
    t, rows, info = collect.fetch_states(session, collect.DEFAULT_BBOX)
    assert t == 1_790_000_000 and len(rows) == 1
    assert info["remaining"] == "3999"
    assert session.calls[0]["params"]["lamin"] == 39.5
    assert session.calls[0]["params"]["extended"] == 1
    assert session.calls[0]["headers"] == {}


def test_fetch_states_refreshes_token_once_on_401():
    session = ScriptedSession([ScriptedResponse(401), ok()])
    tm = FakeTokenManager()
    _, rows, _ = collect.fetch_states(session, collect.DEFAULT_BBOX, token_manager=tm)
    assert len(rows) == 1
    assert tm.invalidated == 1
    assert session.calls[0]["headers"]["Authorization"] == "Bearer old"
    assert session.calls[1]["headers"]["Authorization"] == "Bearer new"


def test_fetch_states_raises_rate_limited_on_429():
    session = ScriptedSession([ScriptedResponse(429, headers={"X-Rate-Limit-Retry-After-Seconds": "120"})])
    with pytest.raises(collect.RateLimited) as excinfo:
        collect.fetch_states(session, collect.DEFAULT_BBOX)
    assert excinfo.value.retry_after_s == 120


def test_collect_loop_sleeps_for_retry_after_and_keeps_going(tmp_path):
    session = ScriptedSession([
        ok(t=100),
        ScriptedResponse(429, headers={"X-Rate-Limit-Retry-After-Seconds": "45"}),
        ok(t=200),
    ])
    sleeps = []
    clock = {"now": 0.0}

    def fake_sleep(s):
        sleeps.append(s)
        clock["now"] += s

    def fake_clock():
        clock["now"] += 0.001  # each read moves time a hair, like a real clock
        return clock["now"]

    written = collect.collect(minutes=1, interval_s=10, bbox=collect.DEFAULT_BBOX, out_dir=tmp_path,
                              session=session, sleep=fake_sleep, clock=fake_clock)
    assert written == 2
    assert len(list(tmp_path.glob("states_*.parquet"))) == 2
    assert sleeps[1] == pytest.approx(45, abs=0.1)  # honoured the API's retry-after
    log_lines = (tmp_path / collect.RATE_LOG_NAME).read_text().strip().splitlines()
    assert len(log_lines) == 4  # header + 3 calls
    assert ",429," in log_lines[2]


def test_bounding_box_credit_cost():
    assert collect.DEFAULT_BBOX.area_sq_deg == pytest.approx(15)
    assert collect.DEFAULT_BBOX.credit_cost == 1
    assert collect.BoundingBox(40, -80, 50, -70).credit_cost == 2       # 100 sq deg
    assert collect.BoundingBox(30, -90, 50, -70).credit_cost == 3       # 400 sq deg
    assert collect.BoundingBox(30, -90, 50, -69).credit_cost == 4       # 420 sq deg
    assert collect.BoundingBox.parse("39.5,-76,42.5,-71") == collect.DEFAULT_BBOX
    with pytest.raises(ValueError):
        collect.BoundingBox.parse("1 2 3")
