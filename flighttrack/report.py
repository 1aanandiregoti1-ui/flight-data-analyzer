"""Stage 5: one HTML page holding the six figures and the numbers behind them.

Recomputes nothing.  Every value on the page is either a column written by an
earlier stage or a plain summary of one (count, median, max), and the figures are
linked from figures/ rather than copied, so `python -m flighttrack.analyze`
refreshes the charts and the prose around them in the same run.

Usage:
    python -m flighttrack.report
    python -m flighttrack.report --out report.html
"""

import argparse
import html
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

log = logging.getLogger("flighttrack.report")

# The page borrows viz.py's palette so the chrome and the PNGs read as one system.
STYLE = """
:root {
  --paper: #fcfcfb;
  --panel: #f4f3ee;
  --ink: #0b0b0b;
  --ink-soft: #4a4843;
  --ink-muted: #898781;
  --rule: #e1e0d9;
  --rule-strong: #cbc9c0;
  --blue: #2a78d6;
  --orange: #eb6834;
  /* The figures are PNGs with a light background baked in, so their plate stays
     light in both themes -- prints hung on a wall, not inverted. */
  --plate: #fcfcfb;
  --plate-rule: #d8d6cd;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --paper: #191814;
    --panel: #211f1b;
    --ink: #f3f1ea;
    --ink-soft: #c6c2b7;
    --ink-muted: #928d81;
    --rule: #332f29;
    --rule-strong: #443f37;
    --blue: #6aa5f2;
    --orange: #f08a5d;
  }
}
:root[data-theme="dark"] {
  --paper: #191814;
  --panel: #211f1b;
  --ink: #f3f1ea;
  --ink-soft: #c6c2b7;
  --ink-muted: #928d81;
  --rule: #332f29;
  --rule-strong: #443f37;
  --blue: #6aa5f2;
  --orange: #f08a5d;
}

* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--paper);
  color: var(--ink);
  font-family: "Source Serif 4", Georgia, "Times New Roman", serif;
  font-size: 17px;
  line-height: 1.65;
  -webkit-font-smoothing: antialiased;
}
.wrap {
  max-width: 1080px;
  margin: 0 auto;
  padding-inline: 20px;
  padding-block: 0 72px;
}
.prose { max-width: 66ch; }
img { max-width: 100%; }

h1, h2, h3, .stat-value, .finding-value {
  font-family: Barlow, "Helvetica Neue", Arial, sans-serif;
  text-wrap: balance;
}
h1 {
  font-size: clamp(2.1rem, 5.5vw, 3.2rem);
  font-weight: 700;
  letter-spacing: -0.015em;
  line-height: 1.05;
  margin: 0 0 12px;
}
h2 {
  font-size: clamp(1.3rem, 3vw, 1.7rem);
  font-weight: 600;
  letter-spacing: -0.01em;
  line-height: 1.2;
  margin: 0;
}
p { margin: 0 0 1em; }
p:last-child { margin-bottom: 0; }
a { color: var(--blue); }

.eyebrow {
  font-family: "IBM Plex Mono", ui-monospace, "SFMono-Regular", Consolas, monospace;
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.14em;
  color: var(--ink-muted);
  margin: 0;
}
.mono { font-family: "IBM Plex Mono", ui-monospace, "SFMono-Regular", Consolas, monospace; }

/* --- masthead: the collection's own flight-plan header ------------------- */
header.masthead { border-bottom: 2px solid var(--ink); padding-block: 44px 20px; }
.subtitle {
  font-size: 1.15rem;
  color: var(--ink-soft);
  max-width: 62ch;
  margin: 0 0 28px;
}
.plan {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 2px;
  background: var(--rule);
  border: 1px solid var(--rule);
  margin: 0;
}
.plan div { background: var(--paper); padding: 10px 12px; }
.plan dt {
  font-family: "IBM Plex Mono", ui-monospace, Consolas, monospace;
  font-size: 0.65rem;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  color: var(--ink-muted);
  margin: 0 0 3px;
}
.plan dd {
  font-family: "IBM Plex Mono", ui-monospace, Consolas, monospace;
  font-size: 0.9rem;
  font-variant-numeric: tabular-nums;
  color: var(--ink);
  margin: 0;
}

/* --- the numbers that carry the report ---------------------------------- */
.stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 28px 32px;
  padding-block: 36px;
  border-bottom: 1px solid var(--rule);
}
.stat-value {
  font-size: clamp(1.9rem, 4.2vw, 2.7rem);
  font-weight: 700;
  line-height: 1;
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.02em;
  display: block;
}
.stat-unit { font-size: 0.5em; font-weight: 600; color: var(--ink-muted); margin-left: 3px; }
.stat-label {
  font-family: "IBM Plex Mono", ui-monospace, Consolas, monospace;
  font-size: 0.7rem;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--ink-muted);
  margin-top: 8px;
  display: block;
}

/* --- the one result the whole pipeline exists to produce ----------------- */
.finding {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 8px 26px;
  padding: 34px 0 38px;
  border-bottom: 1px solid var(--rule);
}
.finding-value {
  font-size: clamp(3.4rem, 11vw, 5.4rem);
  font-weight: 700;
  line-height: 0.9;
  letter-spacing: -0.035em;
  color: var(--orange);
  font-variant-numeric: tabular-nums;
}
.finding p { max-width: 42ch; font-size: 1.05rem; color: var(--ink-soft); flex: 1 1 320px; }

/* --- figures ------------------------------------------------------------ */
section.figure { padding-block: 46px; border-bottom: 1px solid var(--rule); }
section.figure h2 { margin: 6px 0 14px; }
.plate {
  background: var(--plate);
  border: 1px solid var(--plate-rule);
  border-radius: 3px;
  padding: 10px;
  margin: 22px 0 18px;
  overflow-x: auto;
}
.plate img { display: block; width: 100%; height: auto; border-radius: 1px; }
figcaption { color: var(--ink-soft); font-size: 0.98rem; max-width: 66ch; }
figure { margin: 0; }

/* --- leaderboard -------------------------------------------------------- */
.table-scroll { overflow-x: auto; margin-top: 22px; }
table { border-collapse: collapse; width: 100%; min-width: 620px; font-size: 0.86rem; }
caption { text-align: left; color: var(--ink-soft); font-size: 0.98rem; padding-bottom: 14px; max-width: 66ch; }
th, td {
  font-family: "IBM Plex Mono", ui-monospace, Consolas, monospace;
  text-align: right;
  padding: 8px 10px;
  border-bottom: 1px solid var(--rule);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
th {
  font-size: 0.65rem;
  text-transform: uppercase;
  letter-spacing: 0.09em;
  color: var(--ink-muted);
  font-weight: 500;
  border-bottom: 1px solid var(--rule-strong);
}
th:first-child, td:first-child, th:nth-child(2), td:nth-child(2) { text-align: left; }
td.ratio { color: var(--orange); font-weight: 600; }
tbody tr:last-child td { border-bottom: none; }

/* --- method ------------------------------------------------------------- */
.method { padding-block: 46px; }
.stages {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
  gap: 1px;
  background: var(--rule);
  border: 1px solid var(--rule);
  margin: 24px 0 30px;
}
.stage { background: var(--paper); padding: 14px 16px; }
.stage h3 {
  font-size: 0.82rem;
  margin: 0 0 6px;
  font-weight: 600;
  letter-spacing: 0.02em;
}
.stage p {
  font-size: 0.85rem;
  color: var(--ink-soft);
  font-family: "IBM Plex Mono", ui-monospace, Consolas, monospace;
  line-height: 1.5;
}
.caveats { border-left: 2px solid var(--rule-strong); padding-left: 18px; margin: 0; list-style: none; }
.caveats li { margin-bottom: 10px; color: var(--ink-soft); font-size: 0.97rem; }
footer {
  margin-top: 40px;
  padding-top: 18px;
  border-top: 1px solid var(--rule);
  color: var(--ink-muted);
  font-size: 0.8rem;
  font-family: "IBM Plex Mono", ui-monospace, Consolas, monospace;
  line-height: 1.6;
}

@media (max-width: 600px) {
  body { font-size: 16px; }
  .stats { gap: 24px; }
}
@media print {
  body { background: #fff; color: #000; font-size: 11pt; }
  section.figure { break-inside: avoid; }
}
"""

# Each figure answers one written question -- the same question its chart title states.
FIGURE_ORDER = [
    "flight_paths_map.png",
    "altitude_profiles.png",
    "detour_ratio_hist.png",
    "distance_vs_duration.png",
    "traffic_by_hour.png",
    "altitude_vs_speed.png",
]


def _esc(value) -> str:
    return html.escape(str(value), quote=True)


def _n(value) -> str:
    return f"{int(round(value)):,}"


def _link_prefix(figures_dir: Path, out: Path) -> str:
    """How the page should reach the figures: relative if it can, absolute if not.

    On Windows the two can sit on different drives, and there is no relative path
    between D: and C:.  A file:// URL still opens in that case.
    """
    try:
        return Path(os.path.relpath(figures_dir.resolve(), out.resolve().parent)).as_posix()
    except ValueError:
        return figures_dir.resolve().as_uri()


def summarise(fixes: pd.DataFrame, metrics: pd.DataFrame) -> dict:
    """Pull every number the page quotes out of columns earlier stages wrote."""
    hourly = fixes.groupby(fixes["time"].dt.floor("h"))["icao24"].nunique()
    highest = metrics.loc[metrics["max_altitude_ft"].idxmax()]
    fastest = metrics.loc[metrics["mean_speed_kt"].idxmax()]
    longest = metrics.loc[metrics["detour_ratio"].idxmax()]
    start, end = fixes["time"].min(), fixes["time"].max()
    return {
        "n_flights": len(metrics),
        "n_fixes": len(fixes),
        "n_aircraft": fixes["icao24"].nunique(),
        "start": start,
        "end": end,
        "window_min": (end - start).total_seconds() / 60,
        "median_detour": metrics["detour_ratio"].median(),
        "median_duration": metrics["duration_min"].median(),
        "total_km": metrics["track_distance_km"].sum(),
        "lat_min": fixes["latitude"].min(), "lat_max": fixes["latitude"].max(),
        "lon_min": fixes["longitude"].min(), "lon_max": fixes["longitude"].max(),
        "busiest_hour": hourly.idxmax(),
        "busiest_count": int(hourly.max()),
        "highest_ft": highest["max_altitude_ft"], "highest_call": highest["callsign"],
        "fastest_kt": fastest["mean_speed_kt"], "fastest_call": fastest["callsign"],
        "longest_ratio": longest["detour_ratio"], "longest_call": longest["callsign"],
        "n_alt_fixes": int((fixes["geo_altitude_ft"].notna() & fixes["velocity_kt"].notna()).sum()),
        "n_ground_fixes": int(fixes["on_ground"].sum()),
    }


def _captions(s: dict) -> dict:
    """One caption per figure, quoting the same columns the chart was drawn from."""
    pct = (s["median_detour"] - 1) * 100
    return {
        "flight_paths_map.png": (
            "Where did the aircraft actually go?",
            f"Every kept flight drawn as one faint line, {s['n_flights']:,} in all, between "
            f"{s['lat_min']:.1f}&ndash;{s['lat_max']:.1f}&deg;N and {abs(s['lon_max']):.1f}&ndash;"
            f"{abs(s['lon_min']):.1f}&deg;W. The fans converging on JFK, EWR and LGA are arrival "
            "streams: aircraft lining up on the same published approach, one behind another. The "
            "airport markers come from fixed coordinates, not from the data."),
        "altitude_profiles.png": (
            "What does a climb and a descent look like?",
            "One faint line per flight against minutes since its first fix, with the median across "
            "flights in orange. The median wanders after roughly 15 minutes because few flights stay "
            f"inside the box that long &mdash; the median duration here is {s['median_duration']:.1f} "
            "minutes, so the right-hand end of that line is averaging a handful of aircraft, not all "
            "of them."),
        "detour_ratio_hist.png": (
            "How far off the direct route do flights fly?",
            f"Track distance divided by great-circle distance, one value per flight. A ratio of 1.0 "
            f"would be a perfectly direct path. The median is {s['median_detour']:.3f}, so the typical "
            f"flight covered {pct:.1f}% more ground than the straight line between where it entered and "
            "where it left the box. The long right tail is mostly holding patterns and approach turns, "
            f"topping out at {s['longest_ratio']:.2f} for {_esc(s['longest_call'])}."),
        "distance_vs_duration.png": (
            "Are these aircraft cruising or manoeuvring?",
            "Time observed against distance flown, with an 800 km/h reference line. Points above the "
            "line moved slower than cruise. Most of them sit above it, which is the honest read on a "
            "box this size: an aircraft inside it is usually climbing out or slowing into an approach, "
            "not settled at cruise."),
        "traffic_by_hour.png": (
            "When was the sky busiest?",
            f"Distinct aircraft seen per clock hour. The busiest was {s['busiest_hour']:%H:%M} UTC with "
            f"{s['busiest_count']:,}. With a {s['window_min']:.0f}-minute collection both bars are "
            "partial hours, so this chart says more about how long the collector ran than about the "
            "daily rhythm of the airspace &mdash; a longer overnight run is what would make it mean "
            "something."),
        "altitude_vs_speed.png": (
            "Is there a cruise regime?",
            f"Every position fix carrying both an altitude and a speed, {s['n_alt_fixes']:,} of them. "
            "The dense cluster at the top right is cruise; the flat shelf at 10,000 ft near 300 kt is "
            f"the speed limit below that altitude showing up in the data. {s['n_ground_fixes']:,} fixes "
            "were flagged on the ground, but ground reports rarely carry a geometric altitude, so "
            "almost none survive the filter this chart applies &mdash; the on-ground series is "
            "near-empty by construction."),
    }


def build_report(fixes: pd.DataFrame, metrics: pd.DataFrame,
                 figures_dir: Path = Path("figures"),
                 out: Path | None = None) -> Path:
    """Write the page beside the figures it links, unless told otherwise."""
    figures_dir = Path(figures_dir)
    out = Path(out) if out is not None else figures_dir.parent / "report.html"
    s = summarise(fixes, metrics)
    captions = _captions(s)
    pct = (s["median_detour"] - 1) * 100
    rel = _link_prefix(figures_dir, out)

    plan = [
        ("Collected", f"{s['start']:%Y-%m-%d}"),
        ("Window (UTC)", f"{s['start']:%H:%M}&ndash;{s['end']:%H:%M}"),
        ("Duration", f"{s['window_min']:.0f} min"),
        ("Latitude", f"{s['lat_min']:.2f}&ndash;{s['lat_max']:.2f}&deg;N"),
        ("Longitude", f"{abs(s['lon_max']):.2f}&ndash;{abs(s['lon_min']):.2f}&deg;W"),
        ("Source", "OpenSky /states/all"),
    ]
    stats = [
        (_n(s["n_flights"]), "", "Flights analysed"),
        (_n(s["n_fixes"]), "", "Position fixes"),
        (_n(s["n_aircraft"]), "", "Distinct aircraft"),
        (_n(s["total_km"]), "km", "Track distance flown"),
        (f"{s['highest_ft'] / 1000:.1f}k", "ft", "Highest fix"),
        (_n(s["fastest_kt"]), "kt", "Fastest mean speed"),
    ]
    stages = [
        ("collect.py", "Polls /states/all every 15 s and writes raw parquet. Filters nothing."),
        ("clean.py", "Types the columns, adds ft and kt, drops nothing row-wise."),
        ("flights.py", "Splits each aircraft's fixes into flights on a 30-minute gap."),
        ("metrics.py", "Haversine track distance, great-circle distance, detour ratio."),
        ("viz.py", "Draws the six figures above. Recomputes nothing."),
        ("report.py", "This page. Also recomputes nothing."),
    ]
    caveats = [
        f"A {s['window_min']:.0f}-minute window is a snapshot, not a pattern. Every hourly or daily "
        "claim here needs a longer, authenticated collection behind it.",
        "Distances are measured between the first and last fix <em>inside the bounding box</em>, not "
        "between the real origin and destination airports, so a detour ratio here is a lower bound on "
        "the whole route's.",
        "Flights with fewer than 5 fixes, or with endpoints closer than 5 km, are dropped &mdash; they "
        "are mostly aircraft clipping the corner of the box.",
        "Anonymous OpenSky access returns positions at reduced time resolution, so a short manoeuvre "
        "between two polls leaves no trace.",
    ]

    top = metrics.nlargest(10, "detour_ratio")
    rows = "".join(
        "<tr>"
        f"<td>{_esc(r.callsign).strip() or '&mdash;'}</td>"
        f"<td>{_esc(r.origin_country)}</td>"
        f"<td>{r.track_distance_km:,.0f}</td>"
        f"<td>{r.gc_distance_km:,.0f}</td>"
        f'<td class="ratio">{r.detour_ratio:.2f}</td>'
        f"<td>{r.duration_min:.1f}</td>"
        f"<td>{int(r.n_points)}</td>"
        "</tr>"
        for r in top.itertuples()
    )

    figures = "".join(
        f"""
  <section class="figure">
    <figure>
      <p class="eyebrow">figures/{name}</p>
      <h2>{captions[name][0]}</h2>
      <div class="plate"><img src="{rel}/{name}" alt="{captions[name][0]}" loading="lazy"></div>
      <figcaption>{captions[name][1]}</figcaption>
    </figure>
  </section>"""
        for name in FIGURE_ORDER if (figures_dir / name).exists()
    )

    plan_html = "".join(f"<div><dt>{k}</dt><dd>{v}</dd></div>" for k, v in plan)
    stats_html = "".join(
        f'<div><span class="stat-value">{v}<span class="stat-unit">{u}</span></span>'
        f'<span class="stat-label">{label}</span></div>' for v, u, label in stats)
    stages_html = "".join(f'<div class="stage"><h3>{n}</h3><p>{d}</p></div>' for n, d in stages)
    caveats_html = "".join(f"<li>{c}</li>" for c in caveats)

    doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Flight Detour Report</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow:wght@600;700&amp;family=IBM+Plex+Mono:wght@400;500&amp;family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&amp;display=swap">
<style>{STYLE}</style>
</head>
<body>
<div class="wrap">

  <header class="masthead">
    <p class="eyebrow">Flight Data Analyzer &middot; ADS-B position reports</p>
    <h1>How far off the direct route do real flights fly?</h1>
    <p class="subtitle">{s['n_aircraft']:,} aircraft were broadcasting their position over the New York
      and New England corridor during one {s['window_min']:.0f}-minute collection. This page measures
      the ground each one actually covered against the straight line it could have flown.</p>
    <dl class="plan">{plan_html}</dl>
  </header>

  <div class="stats">{stats_html}</div>

  <div class="finding">
    <span class="finding-value">+{pct:.1f}%</span>
    <p>The median flight covered {pct:.1f}% more ground than the great-circle route between the point
      it entered the box and the point it left &mdash; a median detour ratio of
      {s['median_detour']:.3f} across {s['n_flights']:,} flights. None of it is a wasted mile: that gap
      is what separation, published departure routes and approach sequencing cost in distance.</p>
  </div>
{figures}

  <section class="figure">
    <h2>The ten longest detours</h2>
    <div class="table-scroll">
      <table>
        <caption>Ranked by detour ratio. These are the aircraft that gave up the most distance to
          holding, vectoring or an approach turn while inside the box.</caption>
        <thead><tr>
          <th scope="col">Callsign</th><th scope="col">Operator country</th>
          <th scope="col">Track km</th><th scope="col">Direct km</th>
          <th scope="col">Ratio</th><th scope="col">Minutes</th><th scope="col">Fixes</th>
        </tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
  </section>

  <section class="method prose">
    <p class="eyebrow">Method</p>
    <h2>How the numbers were made</h2>
    <p>Five stages, each writing a file the next one reads. Collection is slow and irreplaceable;
      everything after it is fast and repeatable, so the charts can be redrawn without touching the
      API again.</p>
    <div class="stages">{stages_html}</div>
    <h2>What this cannot tell you</h2>
    <ul class="caveats">{caveats_html}</ul>
    <footer>
      Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC by <span class="mono">python -m
      flighttrack.report</span> &middot; {s['n_fixes']:,} fixes &middot; {s['n_flights']:,} flights
      &middot; data &copy; the OpenSky Network
    </footer>
  </section>

</div>
</body>
</html>
"""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(doc, encoding="utf-8")
    log.info("wrote %s", out)
    return out


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the HTML report from processed data.")
    parser.add_argument("--processed-dir", type=Path, default=Path("data/processed"))
    parser.add_argument("--figures-dir", type=Path, default=Path("figures"))
    parser.add_argument("--out", type=Path, default=None,
                        help="where to write the page (default: report.html beside figures/)")
    return parser


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = build_parser().parse_args(argv)
    fixes = pd.read_parquet(args.processed_dir / "flights.parquet")
    metrics = pd.read_csv(args.processed_dir / "metrics.csv", parse_dates=["start_time", "end_time"])
    print(f"report  -> {build_report(fixes, metrics, args.figures_dir, args.out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
