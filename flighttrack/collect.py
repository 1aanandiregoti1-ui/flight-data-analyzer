"""Stage 1: poll OpenSky /states/all on a timer and save raw rows to Parquet.

This module never filters, converts units, or drops nulls.  Whatever the API
returns is what lands on disk, one timestamped file per poll, so the analysis
can be rerun a hundred times on the same snapshot.

Usage:
    python -m flighttrack.collect --minutes 60
    python -m flighttrack.collect --minutes 30 --interval 15 --bbox 47 -1 52 8
"""

import argparse
import csv
import logging
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

from flighttrack.auth import TokenManager

log = logging.getLogger("flighttrack.collect")

STATES_URL = "https://opensky-network.org/api/states/all"

# Field order of a state vector as documented by OpenSky.  Rows come back as
# bare JSON arrays, so this is the only place the positions are named.
STATE_COLUMNS = [
    "icao24",           # 0  24-bit transponder address (hex) — the stable aircraft id
    "callsign",         # 1  8 chars, often with trailing spaces; can be null
    "origin_country",   # 2
    "time_position",    # 3  unix seconds of last position fix; null if stale
    "last_contact",     # 4  unix seconds of last message of any kind
    "longitude",        # 5  WGS-84 degrees; can be null
    "latitude",         # 6  WGS-84 degrees; can be null
    "baro_altitude",    # 7  metres; can be null
    "on_ground",        # 8
    "velocity",         # 9  ground speed, m/s; can be null
    "true_track",       # 10 degrees clockwise from north
    "vertical_rate",    # 11 m/s, positive climbing
    "sensors",          # 12 receiver ids; usually null
    "geo_altitude",     # 13 metres; can be null
    "squawk",           # 14
    "spi",              # 15
    "position_source",  # 16 0 ADS-B, 1 ASTERIX, 2 MLAT, 3 FLARM
    "category",         # 17 aircraft size class, 0-20 (only with extended=1)
]

RATE_LOG_NAME = "ratelimit_log.csv"
RATE_LOG_FIELDS = ["logged_at", "status", "remaining", "retry_after_s", "n_rows", "snapshot_time"]


@dataclass(frozen=True)
class BoundingBox:
    """Lat/lon box passed to the API.  Area in square degrees sets the credit cost."""

    lamin: float
    lomin: float
    lamax: float
    lomax: float

    @property
    def area_sq_deg(self) -> float:
        return (self.lamax - self.lamin) * (self.lomax - self.lomin)

    @property
    def credit_cost(self) -> int:
        area = self.area_sq_deg
        if area <= 25:
            return 1
        if area <= 100:
            return 2
        if area <= 400:
            return 3
        return 4

    def as_params(self) -> dict:
        return {"lamin": self.lamin, "lomin": self.lomin, "lamax": self.lamax, "lomax": self.lomax}

    @classmethod
    def parse(cls, text: str):
        """Parse 'lamin,lomin,lamax,lomax' (commas or spaces)."""
        parts = [float(p) for p in text.replace(",", " ").split()]
        if len(parts) != 4:
            raise ValueError("bounding box needs exactly four numbers: lamin lomin lamax lomax")
        box = cls(*parts)
        if not (box.lamin < box.lamax and box.lomin < box.lomax):
            raise ValueError("bounding box must satisfy lamin < lamax and lomin < lomax")
        return box


# US Northeast corridor: New York, Philadelphia, Boston.  3° x 5° = 15 sq° = 1 credit,
# and dense receiver coverage, so almost every aircraft is seen on every poll.
DEFAULT_BBOX = BoundingBox(lamin=39.5, lomin=-76.0, lamax=42.5, lomax=-71.0)


class RateLimited(Exception):
    def __init__(self, retry_after_s: float, remaining):
        super().__init__(f"rate limited, retry after {retry_after_s}s")
        self.retry_after_s = retry_after_s
        self.remaining = remaining


def _rate_info(response) -> dict:
    headers = response.headers
    return {
        "remaining": headers.get("X-Rate-Limit-Remaining"),
        "retry_after_s": headers.get("X-Rate-Limit-Retry-After-Seconds"),
    }


def fetch_states(session, bbox: BoundingBox, token_manager=None, timeout_s: float = 30):
    """One call to /states/all.  Returns (snapshot_time, rows, rate_info).

    Retries exactly once on 401 (expired token).  Raises RateLimited on 429.
    """
    params = dict(bbox.as_params(), extended=1)
    for attempt in (1, 2):
        headers = token_manager.auth_headers() if token_manager else {}
        response = session.get(STATES_URL, params=params, headers=headers, timeout=timeout_s)
        info = _rate_info(response)

        if response.status_code == 401 and token_manager and attempt == 1:
            log.warning("401 from API — token expired, refreshing and retrying once")
            token_manager.invalidate()
            continue
        if response.status_code == 429:
            retry_after = float(info["retry_after_s"] or 60)
            raise RateLimited(retry_after, info["remaining"])
        response.raise_for_status()

        payload = response.json()
        rows = payload.get("states") or []
        return payload.get("time"), rows, info

    raise RuntimeError("unreachable")  # pragma: no cover


def rows_to_frame(snapshot_time, rows) -> pd.DataFrame:
    """Turn the bare arrays into a DataFrame with named columns, verbatim.

    Rows without the trailing `category` field are padded with None so every
    file has the same schema.  `snapshot_time` records which poll a row came from.
    """
    width = len(STATE_COLUMNS)
    padded = [list(r)[:width] + [None] * (width - len(r)) for r in rows]
    frame = pd.DataFrame(padded, columns=STATE_COLUMNS)
    # `sensors` is a list-or-null column that varies per row; Parquet copes but
    # the mixed types are a nuisance downstream.  Store it as a string so the
    # raw value is preserved without needing a nested schema.
    frame["sensors"] = frame["sensors"].map(lambda s: None if s is None else str(s))
    frame["snapshot_time"] = snapshot_time
    return frame


def raw_filename(snapshot_time) -> str:
    stamp = datetime.fromtimestamp(snapshot_time, tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"states_{stamp}.parquet"


def write_raw(frame: pd.DataFrame, out_dir: Path, snapshot_time) -> Path:
    """Write one poll to a timestamped file.  Never overwrites an existing file."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / raw_filename(snapshot_time)
    suffix = 1
    while path.exists():
        path = out_dir / raw_filename(snapshot_time).replace(".parquet", f"_{suffix}.parquet")
        suffix += 1
    frame.to_parquet(path, index=False)
    return path


def append_rate_log(out_dir: Path, status, info: dict, n_rows, snapshot_time) -> None:
    """Append one line per call so credit usage can be charted later."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / RATE_LOG_NAME
    new_file = not path.exists()
    with path.open("a", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=RATE_LOG_FIELDS)
        if new_file:
            writer.writeheader()
        writer.writerow(
            {
                "logged_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "status": status,
                "remaining": info.get("remaining"),
                "retry_after_s": info.get("retry_after_s"),
                "n_rows": n_rows,
                "snapshot_time": snapshot_time,
            }
        )


def collect(minutes: float, interval_s: float, bbox: BoundingBox, out_dir: Path,
            token_manager=None, session=None, sleep=time.sleep, clock=time.time) -> int:
    """Poll for `minutes`, writing one Parquet file per poll.  Returns files written."""
    session = session or requests.Session()
    deadline = clock() + minutes * 60
    files_written = 0
    total_rows = 0
    consecutive_errors = 0

    log.info(
        "collecting for %.0f min every %.0fs over %s (%.0f sq deg, %d credit/call, ~%d credits)",
        minutes, interval_s, bbox, bbox.area_sq_deg, bbox.credit_cost,
        bbox.credit_cost * (minutes * 60 / interval_s),
    )
    log.info("mode: %s", "authenticated" if token_manager else "anonymous (no credentials in .env)")

    while clock() < deadline:
        started = clock()
        wait = interval_s
        try:
            snapshot_time, rows, info = fetch_states(session, bbox, token_manager)
            frame = rows_to_frame(snapshot_time, rows)
            path = write_raw(frame, out_dir, snapshot_time)
            append_rate_log(out_dir, 200, info, len(rows), snapshot_time)
            files_written += 1
            total_rows += len(rows)
            consecutive_errors = 0
            log.info("%s  aircraft=%-4d credits_remaining=%s", path.name, len(rows), info["remaining"])
        except RateLimited as exc:
            append_rate_log(out_dir, 429, {"remaining": exc.remaining, "retry_after_s": exc.retry_after_s}, 0, None)
            wait = max(interval_s, exc.retry_after_s)
            log.warning("429 rate limited — sleeping %.0fs as the API asked", wait)
        except (requests.RequestException, ValueError) as exc:
            # Network hiccup or malformed JSON.  Keep going; a long collection
            # should survive a flaky minute.  Back off a little each time.
            consecutive_errors += 1
            append_rate_log(out_dir, "error", {}, 0, None)
            wait = min(interval_s * (2 ** consecutive_errors), 300)
            log.warning("request failed (%s) — retrying in %.0fs", exc, wait)

        remaining = deadline - clock()
        if remaining <= 0:
            break
        elapsed = clock() - started
        sleep(max(0.0, min(wait - elapsed, remaining)))

    log.info("done: %d files, %d state vectors in %s", files_written, total_rows, out_dir)
    return files_written


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Poll OpenSky and save raw state vectors.")
    parser.add_argument("--minutes", type=float, default=60, help="how long to collect (default 60)")
    parser.add_argument("--interval", type=float, default=15, help="seconds between polls (default 15)")
    parser.add_argument(
        "--bbox", nargs=4, type=float, metavar=("LAMIN", "LOMIN", "LAMAX", "LOMAX"),
        help="bounding box in degrees (default: OPENSKY_BBOX from .env, else US Northeast)",
    )
    parser.add_argument("--out", type=Path, default=Path("data/raw"), help="output directory")
    parser.add_argument("--anonymous", action="store_true", help="ignore credentials and poll anonymously")
    return parser


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = build_parser().parse_args(argv)

    token_manager = None if args.anonymous else TokenManager.from_env()
    if args.bbox:
        bbox = BoundingBox(*args.bbox)
    elif os.getenv("OPENSKY_BBOX"):
        bbox = BoundingBox.parse(os.environ["OPENSKY_BBOX"])
    else:
        bbox = DEFAULT_BBOX

    try:
        collect(args.minutes, args.interval, bbox, args.out, token_manager=token_manager)
    except KeyboardInterrupt:
        log.info("stopped by user — everything collected so far is already on disk")
    return 0


if __name__ == "__main__":
    sys.exit(main())
