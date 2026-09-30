"""Stage 2: turn raw state vectors into a tidy, typed table of position fixes.

Responsibilities (and nothing else — this module never touches the network):
  * drop rows that have no position or no position timestamp
  * strip the trailing whitespace OpenSky pads callsigns with
  * remove duplicate fixes (the same aircraft, unchanged since the last poll)
  * convert units ONCE and name every column with its unit
"""

import logging
from pathlib import Path

import pandas as pd

log = logging.getLogger("flighttrack.clean")

# Unit conversions — applied here and nowhere else.
METRES_TO_FEET = 3.28084
MS_TO_KNOTS = 1.94384
MS_TO_KMH = 3.6
MS_TO_FPM = 196.850394  # feet per minute

# Columns the analysis needs, in the order the cleaned table is written.
CLEAN_COLUMNS = [
    "icao24", "callsign", "origin_country", "time", "snapshot_time",
    "latitude", "longitude", "on_ground",
    "baro_altitude_m", "baro_altitude_ft",
    "geo_altitude_m", "geo_altitude_ft",
    "velocity_ms", "velocity_kt", "velocity_kmh",
    "vertical_rate_ms", "vertical_rate_fpm",
    "true_track_deg", "position_source", "category",
]


def load_raw(raw_dir: Path) -> pd.DataFrame:
    """Read every states_*.parquet in `raw_dir` into one DataFrame."""
    files = sorted(Path(raw_dir).glob("states_*.parquet"))
    if not files:
        raise FileNotFoundError(f"no states_*.parquet files in {raw_dir} — run flighttrack.collect first")
    frames = [pd.read_parquet(f) for f in files]
    df = pd.concat(frames, ignore_index=True)
    log.info("loaded %d rows from %d raw files", len(df), len(files))
    return df


def null_report(df: pd.DataFrame) -> pd.DataFrame:
    """Count and percentage of nulls per column.  Print this before trusting anything."""
    counts = df.isna().sum()
    return pd.DataFrame({"nulls": counts, "pct": (100 * counts / max(len(df), 1)).round(1)})


def clean(raw: pd.DataFrame) -> pd.DataFrame:
    """Raw state vectors in, tidy position fixes out.  Returns a new DataFrame."""
    df = raw.copy()
    n_start = len(df)

    # 1. A fix with no position or no time of position is useless for tracks.
    df = df.dropna(subset=["latitude", "longitude", "time_position"])
    n_positioned = len(df)

    # 2. Duplicate fixes: an aircraft that has not reported since the last poll
    #    comes back with the same time_position.  Keep one copy.
    df = df.drop_duplicates(subset=["icao24", "time_position"], keep="first")
    n_deduped = len(df)

    # 3. Callsigns arrive padded to 8 characters; empty after stripping means unknown.
    df["callsign"] = df["callsign"].str.strip().replace("", None)

    # 4. Timestamps: unix seconds -> timezone-aware datetime.
    df["time"] = pd.to_datetime(df["time_position"], unit="s", utc=True)

    # 5. Units.  Metric stays (that is what the API gives); aviation units are added.
    df = df.rename(columns={
        "baro_altitude": "baro_altitude_m",
        "geo_altitude": "geo_altitude_m",
        "velocity": "velocity_ms",
        "vertical_rate": "vertical_rate_ms",
        "true_track": "true_track_deg",
    })
    df["baro_altitude_ft"] = df["baro_altitude_m"] * METRES_TO_FEET
    df["geo_altitude_ft"] = df["geo_altitude_m"] * METRES_TO_FEET
    df["velocity_kt"] = df["velocity_ms"] * MS_TO_KNOTS
    df["velocity_kmh"] = df["velocity_ms"] * MS_TO_KMH
    df["vertical_rate_fpm"] = df["vertical_rate_ms"] * MS_TO_FPM

    df["on_ground"] = df["on_ground"].astype(bool)
    df = df.sort_values(["icao24", "time"]).reset_index(drop=True)

    log.info(
        "clean: %d raw -> %d with position (-%d) -> %d unique fixes (-%d duplicates)",
        n_start, n_positioned, n_start - n_positioned, n_deduped, n_positioned - n_deduped,
    )
    return df[CLEAN_COLUMNS]


def main(raw_dir: Path = Path("data/raw"), out_path: Path = Path("data/processed/states_clean.parquet")) -> pd.DataFrame:
    raw = load_raw(raw_dir)
    print("Nulls in raw data:")
    print(null_report(raw).to_string())
    df = clean(raw)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_path, index=False)
    print(f"\n{len(df)} fixes from {df['icao24'].nunique()} aircraft -> {out_path}")
    return df


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    main()
