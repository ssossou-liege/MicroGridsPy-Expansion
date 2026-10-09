r"""Calibrate the community uses that the meters can speak to.

Writes one table to ``data/ramp_params/reference/``:

``community_class_profiles.csv``
    Mean hourly load of one connected community use of each class [kW], its mean daily
    energy, and the spread of that energy from day to day.

Only one class comes out of this. A village has four community loads worth naming --- a
school, a health centre, a place of worship and the street lighting --- and of the four,
the meters of the two reference villages speak to exactly one.

The places of worship are measured. Five are metered across the two villages and four have
drawn current; their shape is unmistakable once drawn, peaking at seven in the evening with
a second rise through the morning service hours, and carrying a third of its energy through
the night on what is presumably a security lamp. The level is low --- half a kilowatt-hour a
day --- and the spread is wide, which is what a building used on particular days rather than
continuously looks like.

The school is not measured, and the distinction matters more than it looks. One school is
metered, at Gbowele since the tenth of May 2026, and over nine thousand seven hundred
readings it has drawn nothing at all: its relay has stood open throughout. It is equipped,
not supplied. The other village has no school meter. So there is no school load here to
calibrate, and a shape invented for one would be a shape invented.

The health centre is not measured either, for the plainer reason that neither pilot village
has one.

Both therefore remain uses a developer declares, device by device, through the
specification in :mod:`microgrid_expansion.demand.uses`; and the street lighting, which has
no behaviour to calibrate, is placed from a lamp count and a rating.

The script is deterministic given its inputs.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from ..paths import REFERENCE_DIR

#: The meters that carry a community use, by the class they belong to. Identified by the
#: operator rather than by their tariff code, which does not distinguish a place of worship
#: from any other non-household connection.
COMMUNITY_METERS: dict[str, tuple[str, ...]] = {
    "place_of_worship": ("0004SAM", "0007SAM", "0153GBO", "0150GBO", "0056GBO"),
    "school": ("0054GBO",),
}

#: Relay states in which the connection is actually supplying. Every other state is a meter
#: reporting while its relay stands open, and counting those hours would dilute a shape with
#: hours during which nothing could have been drawn.
SUPPLYING_STATES = (0, 1)

#: Below this, a meter has not drawn enough over its life for an hourly shape to mean
#: anything, and it is left out of the class it belongs to rather than flattening it.
MIN_KWH = 1.0

HOURS = tuple(range(24))


def _meter_readings(archive: Path, code: str) -> pd.DataFrame:
    """One meter's supplying hours, from the harmonised smart-meter archive."""
    site = code[-3:]
    frame = pd.read_parquet(archive / f"{site}_readings.parquet",
                            columns=["timestamp", "kwh", "state", "customer_id"])
    frame["customer_id"] = frame["customer_id"].astype(str)
    frame = frame[(frame["customer_id"] == code)
                  & (frame["state"].isin(SUPPLYING_STATES))]
    return frame.drop(columns=["customer_id", "state"])


def class_profiles(archive: Path) -> pd.DataFrame:
    """Hourly shape, daily energy and daily spread for each community class with data."""
    rows = {}
    for klass, codes in COMMUNITY_METERS.items():
        shapes, daily, kept = [], [], []
        for code in codes:
            readings = _meter_readings(archive, code)
            if readings.empty or float(readings["kwh"].sum()) <= MIN_KWH:
                continue
            hourly = readings.set_index("timestamp")["kwh"].resample("h").sum()
            days = hourly.resample("D").sum()
            days = days[days > 0.01]          # days the use was not used say nothing of it
            if days.empty:
                continue
            shape = hourly.groupby(hourly.index.hour).mean().reindex(HOURS, fill_value=0.0)
            total = float(shape.sum())
            if total <= 0:
                continue
            shapes.append(shape / total)
            daily.append(float(days.mean()))
            kept.append(code)
        if not shapes:
            continue
        mean_shape = pd.concat(shapes, axis=1).mean(axis=1)
        mean_shape = mean_shape / float(mean_shape.sum())
        energy = float(np.mean(daily))
        rows[klass] = {
            **{str(hour): float(mean_shape.get(hour, 0.0) * energy) for hour in HOURS},
            "kwh_per_day": energy,
            "daily_cv": float(np.std(daily) / energy) if len(daily) > 1 and energy else 0.0,
            "n_meters": len(kept),
            "meters": " ".join(kept),
        }
    return pd.DataFrame(rows).T.rename_axis("community_class")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True,
                        help="directory holding the harmonised meter archive")
    parser.add_argument("--out", type=Path, default=REFERENCE_DIR)
    args = parser.parse_args(argv)

    profiles = class_profiles(args.archive)
    if profiles.empty:
        print("no community class carries enough metered energy to calibrate")
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    destination = args.out / "community_class_profiles.csv"
    profiles.to_csv(destination)
    print(f"written {destination}")
    for klass, row in profiles.iterrows():
        print(f"  {klass}: {row['kwh_per_day']:.3f} kWh/day from {int(row['n_meters'])} "
              f"meters, spread {row['daily_cv']:.2f}")
    missing = sorted(set(COMMUNITY_METERS) - set(profiles.index))
    for klass in missing:
        print(f"  {klass}: no metered energy; it stays a use to be declared")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
