"""Stage 3a: group position fixes into flights.

A flight is not a row in the API response — it is something we construct:
all fixes sharing one icao24, ordered by time, split wherever the gap between
consecutive fixes exceeds a threshold.  A long gap usually means the aircraft
landed, or left receiver coverage and came back on a different leg.

icao24 (not callsign) is the grouping key because callsigns are reused across
days and can be null.
"""

import pandas as pd

DEFAULT_GAP_MINUTES = 30.0


def assign_flights(df: pd.DataFrame, gap_minutes: float = DEFAULT_GAP_MINUTES) -> pd.DataFrame:
    """Add a `flight_id` column.  Expects `icao24` and a datetime `time` column.

    flight_id is icao24 + the UTC time of the flight's first fix, so it is
    unique across days and readable by a human.
    """
    if df.empty:
        out = df.copy()
        out["flight_id"] = pd.Series(dtype="str")
        return out

    df = df.sort_values(["icao24", "time"]).reset_index(drop=True)
    gap = pd.Timedelta(minutes=gap_minutes)

    # Time since the previous fix of the same aircraft; NaT for the first fix.
    since_previous = df.groupby("icao24")["time"].diff()

    # A new leg starts at the first fix of each aircraft and after any long gap.
    new_leg = since_previous.isna() | (since_previous > gap)

    # Running count of leg starts gives each leg its own integer, globally unique.
    leg_number = new_leg.cumsum()

    first_time = df.groupby(leg_number)["time"].transform("min")
    df["flight_id"] = df["icao24"] + "_" + first_time.dt.strftime("%Y%m%dT%H%M%SZ")
    return df


def flight_count(df: pd.DataFrame) -> int:
    return int(df["flight_id"].nunique()) if "flight_id" in df else 0
