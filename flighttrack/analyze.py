"""Run the analysis pipeline over collected data: clean -> flights -> metrics -> figures -> report.

Collection is slow and irreplaceable; everything here is fast and repeatable,
so this can be rerun as often as the charts need tweaking.

Usage:
    python -m flighttrack.analyze
    python -m flighttrack.analyze --raw-dir data/raw --gap-minutes 30 --min-points 5
"""

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

from flighttrack import clean, flights, metrics, report, viz

log = logging.getLogger("flighttrack.analyze")


def run(raw_dir: Path, processed_dir: Path, figures_dir: Path,
        gap_minutes: float, min_points: int, min_gc_km: float, no_figures: bool = False,
        report_path: Path | None = None) -> pd.DataFrame:
    processed_dir.mkdir(parents=True, exist_ok=True)

    # Stage 2 — clean
    raw = clean.load_raw(raw_dir)
    print("Nulls per column in the raw data (this is why nothing is dropped row-wise):")
    print(clean.null_report(raw).to_string(), "\n")
    fixes = clean.clean(raw)

    # Stage 3 — flights and metrics
    fixes = flights.assign_flights(fixes, gap_minutes=gap_minutes)
    fixes.to_parquet(processed_dir / "flights.parquet", index=False)
    all_metrics = metrics.flight_metrics(fixes)
    kept = metrics.filter_flights(all_metrics, min_points=min_points, min_gc_km=min_gc_km)
    metrics.save_metrics(all_metrics, processed_dir / "metrics_all.csv")
    metrics_path = metrics.save_metrics(kept, processed_dir / "metrics.csv")

    print(f"{len(fixes):,} position fixes from {fixes['icao24'].nunique():,} aircraft, "
          f"grouped into {flights.flight_count(fixes):,} flights; {len(kept):,} kept for analysis.\n")

    summary_cols = ["n_points", "duration_min", "track_distance_km", "gc_distance_km",
                    "detour_ratio", "max_altitude_ft", "mean_speed_kt"]
    print("Metrics summary (kept flights):")
    print(kept[summary_cols].describe().round(2).to_string(), "\n")

    print("Nulls in the metrics table (a flight with no altitude fixes has no max altitude):")
    print(kept[summary_cols].isna().sum().to_string(), "\n")

    print(f"First flights:\n{kept.head(10).to_string()}\n")
    print(f"metrics -> {metrics_path}")

    # Stage 4 — figures
    if not no_figures:
        if kept.empty:
            log.warning("no flights survived filtering — skipping figures")
        else:
            for path in viz.make_all_figures(fixes, kept, figures_dir):
                print(f"figure  -> {path}")

            # Stage 5 - the page that puts the figures next to the numbers behind them
            print(f"report  -> {report.build_report(fixes, kept, figures_dir, report_path)}")
    return kept


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Clean, group, measure and chart collected flight data.")
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--processed-dir", type=Path, default=Path("data/processed"))
    parser.add_argument("--figures-dir", type=Path, default=Path("figures"))
    parser.add_argument("--gap-minutes", type=float, default=flights.DEFAULT_GAP_MINUTES,
                        help="gap between fixes that starts a new flight (default 30)")
    parser.add_argument("--min-points", type=int, default=5, help="drop flights with fewer fixes (default 5)")
    parser.add_argument("--min-gc-km", type=float, default=5.0,
                        help="drop flights whose endpoints are closer than this (default 5 km)")
    parser.add_argument("--report", type=Path, default=None,
                        help="where to write the HTML report (default: report.html beside figures/)")
    parser.add_argument("--no-figures", action="store_true", help="compute metrics only")
    return parser


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = build_parser().parse_args(argv)
    run(args.raw_dir, args.processed_dir, args.figures_dir,
        args.gap_minutes, args.min_points, args.min_gc_km, args.no_figures, args.report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
