"""Stage 4: charts and the map.

Reads the cleaned fixes and the per-flight metrics, writes PNGs to figures/.
Recomputes nothing — every number on a chart comes from a column written by an
earlier stage.  Every figure answers one written question, stated in its title.
"""

import logging
import math
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

matplotlib.use("Agg")  # headless; we only save files

log = logging.getLogger("flighttrack.viz")

# Palette: two categorical slots plus recessive chrome.  Text never wears a series colour.
BLUE = "#2a78d6"       # series 1 — the default single-series colour
ORANGE = "#eb6834"     # series 2 — a contrasting overlay or second category
INK = "#0b0b0b"
INK_MUTED = "#898781"
GRID = "#e1e0d9"
SURFACE = "#fcfcfb"
DPI = 150


def _style() -> None:
    plt.rcParams.update({
        "figure.facecolor": SURFACE,
        "axes.facecolor": SURFACE,
        "axes.edgecolor": INK_MUTED,
        "axes.labelcolor": INK,
        "axes.titlecolor": INK,
        "axes.titleweight": "bold",
        "axes.titlesize": 12,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "grid.color": GRID,
        "grid.linewidth": 0.6,
        "xtick.color": INK_MUTED,
        "ytick.color": INK_MUTED,
        "font.family": "sans-serif",
        "font.size": 10,
        "legend.frameon": False,
    })


def _save(fig, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout(rect=(0, 0.03, 1, 1))  # leave a strip at the bottom for the footnote
    fig.savefig(path, dpi=DPI)
    plt.close(fig)
    log.info("wrote %s", path)
    return path


def _line_alpha(n_lines: int) -> float:
    """Fainter lines when many overlap, solid enough to see when there are few."""
    return float(np.clip(40.0 / max(n_lines, 1), 0.12, 0.8))


# Reference points for the no-basemap map.  Only those inside the plotted box are drawn.
AIRPORTS = {
    "JFK": (40.6413, -73.7781), "EWR": (40.6895, -74.1745), "LGA": (40.7769, -73.8740),
    "PHL": (39.8721, -75.2411), "BOS": (42.3656, -71.0096), "BDL": (41.9389, -72.6832),
    "ALB": (42.7483, -73.8017), "PVD": (41.7240, -71.4283), "HPN": (41.0670, -73.7076),
    "LHR": (51.4700, -0.4543), "CDG": (49.0097, 2.5479), "AMS": (52.3105, 4.7683),
    "FRA": (50.0379, 8.5622), "BRU": (50.9010, 4.4856), "LGW": (51.1537, -0.1821),
}


def _sample_note(n: int, fixes: pd.DataFrame) -> str:
    """'n = 412 flights, 2026-09-22 06:00–12:00 UTC' for a corner of every chart."""
    start, end = fixes["time"].min(), fixes["time"].max()
    if start.date() == end.date():
        window = f"{start:%Y-%m-%d} {start:%H:%M}–{end:%H:%M} UTC"
    else:
        window = f"{start:%Y-%m-%d %H:%M} – {end:%Y-%m-%d %H:%M} UTC"
    return f"n = {n} flights, {window}"


def _footnote(fig, text: str) -> None:
    fig.text(0.01, 0.01, text, ha="left", va="bottom", fontsize=8, color=INK_MUTED)


# --------------------------------------------------------------------------- #
# 1. Flight paths map — "What does the traffic actually look like?"
# --------------------------------------------------------------------------- #

def flight_paths_map(fixes: pd.DataFrame, metrics: pd.DataFrame, out: Path) -> Path:
    tracks = fixes[fixes["flight_id"].isin(metrics["flight_id"])]
    n = tracks["flight_id"].nunique()
    lat_c = tracks["latitude"].mean()

    try:
        import cartopy.crs as ccrs
        import cartopy.feature as cfeature

        fig = plt.figure(figsize=(10, 8))
        ax = fig.add_subplot(1, 1, 1, projection=ccrs.PlateCarree())
        ax.add_feature(cfeature.LAND, facecolor="#f1f0eb", edgecolor="none")
        ax.add_feature(cfeature.OCEAN, facecolor="#e6ecf3", edgecolor="none")
        ax.add_feature(cfeature.COASTLINE, linewidth=0.5, edgecolor=INK_MUTED)
        ax.add_feature(cfeature.BORDERS, linewidth=0.4, edgecolor=INK_MUTED, linestyle=":")
        ax.add_feature(cfeature.STATES, linewidth=0.3, edgecolor=INK_MUTED, alpha=0.6)
        plot_kwargs = {"transform": ccrs.PlateCarree()}
        basemap = "cartopy"
    except ImportError:
        fig, ax = plt.subplots(figsize=(10, 8))
        # Equirectangular: shrink the x axis by cos(latitude) so shapes are not stretched.
        ax.set_aspect(1.0 / math.cos(math.radians(lat_c)))
        ax.set_xlabel("Longitude (°)")
        ax.set_ylabel("Latitude (°)")
        plot_kwargs = {}
        basemap = "none"

    alpha = _line_alpha(n)
    for _, g in tracks.groupby("flight_id", sort=False):
        ax.plot(g["longitude"], g["latitude"], color=BLUE, linewidth=0.8, alpha=alpha, **plot_kwargs)

    pad = 0.1
    x0, x1 = tracks["longitude"].min() - pad, tracks["longitude"].max() + pad
    y0, y1 = tracks["latitude"].min() - pad, tracks["latitude"].max() + pad
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)

    if basemap == "cartopy":
        gl = ax.gridlines(draw_labels=True, linewidth=0.4, color=GRID)
        gl.top_labels = gl.right_labels = False
    else:
        # No coastline, so give the eye something to anchor on: major airports in the box.
        for code, (lat, lon) in AIRPORTS.items():
            if x0 <= lon <= x1 and y0 <= lat <= y1:
                ax.plot(lon, lat, marker="o", markersize=5, color=INK, zorder=5)
                ax.annotate(code, (lon, lat), xytext=(4, 4), textcoords="offset points",
                            fontsize=8, color=INK, zorder=5)
    ax.set_title(f"{n} flight tracks reconstructed from ADS-B position reports")
    _footnote(fig, _sample_note(n, tracks) + ("" if basemap == "cartopy" else "  ·  no basemap (cartopy not installed)"))
    return _save(fig, out)


# --------------------------------------------------------------------------- #
# 2. Altitude profiles — "How do aircraft climb and cruise?"
# --------------------------------------------------------------------------- #

def altitude_profiles(fixes: pd.DataFrame, metrics: pd.DataFrame, out: Path) -> Path:
    tracks = fixes[fixes["flight_id"].isin(metrics["flight_id"])].dropna(subset=["geo_altitude_ft"])
    tracks = tracks.assign(
        minutes=(tracks["time"] - tracks.groupby("flight_id")["time"].transform("min")).dt.total_seconds() / 60
    )
    n = tracks["flight_id"].nunique()

    fig, ax = plt.subplots(figsize=(10, 6))
    alpha = _line_alpha(n) * 0.6
    for _, g in tracks.groupby("flight_id", sort=False):
        ax.plot(g["minutes"], g["geo_altitude_ft"], color=BLUE, linewidth=0.6, alpha=alpha)

    # Median altitude per whole minute since first fix, only where >= 10 flights contribute.
    binned = tracks.assign(minute=tracks["minutes"].round()).groupby("minute")["geo_altitude_ft"]
    median = binned.median()[binned.count() >= 10]
    ax.plot(median.index, median.values, color=ORANGE, linewidth=2.0, label="median across flights")

    ax.set_xlabel("Minutes since first fix")
    ax.set_ylabel("Geometric altitude (ft)")
    ax.set_ylim(bottom=0)
    ax.set_title("Altitude profiles: one faint line per flight, median in orange")
    ax.legend(loc="upper right")
    _footnote(fig, _sample_note(n, tracks))
    return _save(fig, out)


# --------------------------------------------------------------------------- #
# 3. Detour ratio distribution — "How much further than straight do aircraft fly?"
# --------------------------------------------------------------------------- #

def detour_ratio_hist(metrics: pd.DataFrame, fixes: pd.DataFrame, out: Path, clip: float = 2.0) -> Path:
    ratios = metrics["detour_ratio"].dropna()
    n = len(ratios)
    median = ratios.median()
    shown = ratios.clip(upper=clip)
    n_clipped = int((ratios > clip).sum())

    fig, ax = plt.subplots(figsize=(9, 5.5))
    bins = np.arange(1.0, clip + 0.025, 0.025)
    ax.hist(shown, bins=bins, color=BLUE, edgecolor=SURFACE, linewidth=0.5)
    ax.axvline(1.0, color=INK, linewidth=1.2, linestyle="--")
    ax.text(1.005, ax.get_ylim()[1] * 0.95, "1.0 = direct route", color=INK, fontsize=9, va="top")
    ax.axvline(median, color=ORANGE, linewidth=1.5)
    ax.text(median + 0.005, ax.get_ylim()[1] * 0.85, f"median {median:.3f}", color=ORANGE, fontsize=9, va="top")

    ax.set_xlabel(f"Detour ratio = track distance / great-circle distance  (values above {clip:g} shown at {clip:g})")
    ax.set_ylabel("Flights")
    ax.set_title(f"The median flight flew {100 * (median - 1):.1f}% further than the direct route")
    note = _sample_note(n, fixes)
    if n_clipped:
        note += f"  ·  {n_clipped} flights above {clip:g} clipped"
    _footnote(fig, note)
    return _save(fig, out)


# --------------------------------------------------------------------------- #
# 4. Distance vs duration — "Does flight time scale linearly with distance?"
# --------------------------------------------------------------------------- #

def distance_vs_duration(metrics: pd.DataFrame, fixes: pd.DataFrame, out: Path) -> Path:
    n = len(metrics)
    fig, ax = plt.subplots(figsize=(9, 6))
    ax.scatter(metrics["track_distance_km"], metrics["duration_min"], s=14, color=BLUE, alpha=0.5, edgecolors="none")

    # A reference line for a typical jet ground speed, so the reader has a yardstick.
    kmh = 800
    xmax = metrics["track_distance_km"].max()
    xs = np.array([0, xmax])
    ax.plot(xs, xs / kmh * 60, color=ORANGE, linewidth=1.2, linestyle="--", label=f"{kmh} km/h reference")

    ax.set_xlabel("Track distance flown inside the box (km)")
    ax.set_ylabel("Time observed (min)")
    ax.set_xlim(left=0)
    ax.set_ylim(bottom=0)
    ax.set_title("Time observed vs. distance flown — points above the line are slower than 800 km/h")
    ax.legend(loc="upper left")
    _footnote(fig, _sample_note(n, fixes))
    return _save(fig, out)


# --------------------------------------------------------------------------- #
# 5. Traffic by hour — "When is the sky busiest?"
# --------------------------------------------------------------------------- #

def traffic_by_hour(fixes: pd.DataFrame, out: Path) -> Path:
    hourly = fixes.groupby(fixes["time"].dt.floor("h"))["icao24"].nunique()
    n_aircraft = fixes["icao24"].nunique()

    fig, ax = plt.subplots(figsize=(10, 5))
    labels = [t.strftime("%H:%M") for t in hourly.index]
    positions = np.arange(len(labels))
    ax.bar(positions, hourly.values, color=BLUE, width=0.8, edgecolor=SURFACE)
    ax.set_xticks(positions, labels)
    for i, v in enumerate(hourly.values):
        ax.text(i, v, str(v), ha="center", va="bottom", fontsize=8, color=INK)

    busiest = hourly.idxmax()
    ax.set_xlabel("Hour (UTC)")
    ax.set_ylabel("Distinct aircraft seen")
    ax.set_title(f"Busiest hour was {busiest:%H:%M} UTC with {hourly.max()} distinct aircraft")
    ax.grid(axis="x", visible=False)
    if len(labels) > 12:
        ax.tick_params(axis="x", labelrotation=45)
    _footnote(fig, f"n = {n_aircraft} aircraft, {fixes['time'].min():%Y-%m-%d %H:%M} – {fixes['time'].max():%Y-%m-%d %H:%M} UTC  ·  partial hours at each end")
    return _save(fig, out)


# --------------------------------------------------------------------------- #
# 6. Altitude vs speed — "Is there a cruise regime?"
# --------------------------------------------------------------------------- #

def altitude_vs_speed(fixes: pd.DataFrame, out: Path, max_points: int = 40_000) -> Path:
    pts = fixes.dropna(subset=["geo_altitude_ft", "velocity_kt"])
    n_total = len(pts)
    if n_total > max_points:
        pts = pts.sample(max_points, random_state=0)

    fig, ax = plt.subplots(figsize=(9, 6))
    for on_ground, colour, label in [(False, BLUE, "airborne"), (True, ORANGE, "on ground")]:
        sub = pts[pts["on_ground"] == on_ground]
        ax.scatter(sub["velocity_kt"], sub["geo_altitude_ft"], s=6, color=colour, alpha=0.25,
                   edgecolors="none", label=f"{label} ({len(sub):,} fixes)")

    ax.set_xlabel("Ground speed (kt)")
    ax.set_ylabel("Geometric altitude (ft)")
    ax.set_xlim(left=0)
    ax.set_ylim(bottom=0)
    ax.set_title("Altitude vs. ground speed — the dense cluster top-right is cruise")
    ax.legend(loc="upper left", markerscale=3)
    note = f"n = {n_total:,} position fixes"
    if n_total > max_points:
        note += f" ({max_points:,} plotted)"
    _footnote(fig, note + f", {pts['time'].min():%Y-%m-%d}")
    return _save(fig, out)


# --------------------------------------------------------------------------- #

def make_all_figures(fixes: pd.DataFrame, metrics: pd.DataFrame, figures_dir: Path = Path("figures")) -> list:
    _style()
    figures_dir = Path(figures_dir)
    return [
        flight_paths_map(fixes, metrics, figures_dir / "flight_paths_map.png"),
        altitude_profiles(fixes, metrics, figures_dir / "altitude_profiles.png"),
        detour_ratio_hist(metrics, fixes, figures_dir / "detour_ratio_hist.png"),
        distance_vs_duration(metrics, fixes, figures_dir / "distance_vs_duration.png"),
        traffic_by_hour(fixes, figures_dir / "traffic_by_hour.png"),
        altitude_vs_speed(fixes, figures_dir / "altitude_vs_speed.png"),
    ]
