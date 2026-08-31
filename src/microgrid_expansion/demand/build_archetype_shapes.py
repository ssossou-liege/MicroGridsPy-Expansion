r"""Measured hourly shape of each behavioural archetype.

The calibration already records what each archetype consumes in a day and what peak it
reaches. It records nothing about *when*, and the appliance parameters were therefore
never confronted with the shape they produce. They do not reproduce it: simulated against
the meters, the households of these villages are given three times too much load in the
middle of the day and a quarter of the load they actually draw between midnight and dawn.
That error is not cosmetic for a sizing study — night-time load is precisely what a battery
carries, and midday load is precisely what an array serves without one — so the shape is
made an explicit calibration target here.

Each household-month of the segmentation carries an archetype label. This script averages
the metered power of those household-months by hour of day, giving one measured
twenty-four-hour shape per archetype, normalised to a unit mean so that shape and level
stay separate concerns: level is already reconciled by the moment-matching step.
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from ..paths import DEMAND_DIR, REFERENCE_DIR
from ..sites import SITES
from .generator import ARCHETYPES

ASSIGNMENTS = "monthly_household_cluster_assignments.csv"
OUTPUT = "archetype_hourly_shapes.csv"


def measured_shapes(assignments: pd.DataFrame | None = None) -> pd.DataFrame:
    """Mean hourly power of each archetype, normalised to a unit daily mean."""
    if assignments is None:
        assignments = pd.read_csv(REFERENCE_DIR / ASSIGNMENTS)
    assignments = assignments[assignments["cluster"].astype(str).isin(ARCHETYPES)]
    labels = {(row.site_name, str(row.month), row.customer_code): str(row.cluster)
              for row in assignments.itertuples()}

    totals = {a: np.zeros(24) for a in ARCHETYPES}
    counts = {a: np.zeros(24) for a in ARCHETYPES}
    for site_name, site in SITES.items():
        if site.meter_file is None:
            continue
        meters = pd.read_parquet(DEMAND_DIR / site.meter_file)
        meters["ts"] = pd.to_datetime(meters.timestamp)
        meters["month"] = meters.ts.dt.to_period("M").astype(str)
        meters["hour"] = meters.ts.dt.hour
        keys = list(zip([site_name] * len(meters), meters.month, meters.customer_code))
        meters["cluster"] = [labels.get(k) for k in keys]
        meters = meters.dropna(subset=["cluster"])
        grouped = meters.groupby(["cluster", "hour"]).power_W.agg(["sum", "size"])
        for (cluster, hour), row in grouped.iterrows():
            totals[cluster][hour] += row["sum"]
            counts[cluster][hour] += row["size"]

    rows = {}
    for archetype in ARCHETYPES:
        with np.errstate(invalid="ignore", divide="ignore"):
            mean = np.where(counts[archetype] > 0,
                            totals[archetype] / np.maximum(counts[archetype], 1), np.nan)
        if np.nansum(mean) > 0:
            rows[archetype] = mean / np.nanmean(mean)
    frame = pd.DataFrame(rows).T
    frame.columns = [str(h) for h in range(24)]
    frame.index.name = "cluster"
    return frame


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=REFERENCE_DIR / OUTPUT)
    args = parser.parse_args(argv)

    shapes = measured_shapes()
    shapes.round(6).to_csv(args.out)
    bars = " ▁▂▃▄▅▆▇█"
    print(f"measured shapes written to {args.out}")
    for archetype, row in shapes.iterrows():
        values = row.to_numpy()
        daytime = 100 * values[7:19].sum() / values.sum()
        drawing = "".join(bars[min(int(v / values.max() * 8), 8)] for v in values)
        print(f"  archetype {archetype}  {drawing}  daytime {daytime:.0f} %")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
