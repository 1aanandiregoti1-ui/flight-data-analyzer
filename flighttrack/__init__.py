"""flighttrack — collect live ADS-B position reports from OpenSky and turn them into flights.

Pipeline (each stage writes to disk before the next one reads):

    collect  ->  data/raw/*.parquet      (verbatim API rows, one file per poll)
    clean    ->  processed/states_clean  (nulls, units, callsigns, dedupe)
    flights  ->  processed/flights       (fixes grouped into flight_id)
    metrics  ->  processed/metrics.csv   (one row per flight)
    viz      ->  figures/*.png
"""

__version__ = "0.1.0"
