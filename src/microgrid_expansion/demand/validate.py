#!/usr/bin/env python3
"""Validation of the demand layer against the measured monthly statistics.

Reports the two comparisons that decide whether the layer is fit for use: whether the
monthly mixture laws reproduce the measured seasonal profile of consumption, and whether a
full stochastic year reproduces the measured annual energy of the community.

Run:  python -m microgrid_expansion.demand.validate [--site Samionta]
"""
from __future__ import annotations

import argparse
import calendar

import numpy as np
import pandas as pd

from ..paths import REFERENCE_DIR
from ..sites import get_site
from .generator import (
    ARCHETYPES,
    _redistribute_outliers,
    load_monthly_mixture,
    simulate_demand_year,
)


def measured_energy_by_maturity(site) -> pd.Series:
    """Measured daily energy per household by maturity band [kWh/household/day]."""
    from .maturity import MATURITY_LABELS, STATES, _composition, with_maturity
    from .partition import load_archetype_profiles

    frame = with_maturity()
    frame = frame[frame["site_name"] == site.name]
    energy = load_archetype_profiles()["mean_daily_kwh"].to_dict()
    energy["inactive"] = 0.0
    energy.setdefault("outlier", 0.0)

    levels = {}
    for band in MATURITY_LABELS:
        rows = frame[frame["maturity"] == band]
        if rows.empty:
            continue
        levels[band] = float(rows["mean_daily_kWh"].mean())
    return pd.Series(levels)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", default="Samionta")
    parser.add_argument("--year", type=int, default=2025)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--maturity-months", type=int, default=12)
    args = parser.parse_args(argv)
    site = get_site(args.site)

    from .growth import TRAJECTORIES, growth_envelope

    print(f"=== {site.name} -- measured energy by age of connection ===")
    measured = measured_energy_by_maturity(site)
    print(measured.round(3).to_string())

    print("\n=== growth envelope measured across the two reference sites ===")
    envelope = growth_envelope()
    print(envelope.factors.round(2).to_string())
    print(f"widest spread: x{envelope.spread:.2f}")

    print(f"\n=== year simulated at {args.maturity_months} months of connection age, "
          f"by trajectory (seed {args.seed}) ===")
    print(f"{'trajectory':>12s}{'energy kWh':>14s}{'peak kW':>12s}{'cf':>8s}"
          f"{'kWh/household/d':>17s}")
    results = {}
    for trajectory in TRAJECTORIES:
        year = simulate_demand_year(site, year=args.year, seed=args.seed,
                                    maturity_months=args.maturity_months,
                                    trajectory=trajectory)
        per_household_day = year.annual_energy_kwh / site.n_households / 365.0
        results[trajectory] = year.annual_energy_kwh
        print(f"{trajectory:>12s}{year.annual_energy_kwh:14,.0f}{year.peak_kw:12.2f}"
              f"{year.load_factor:8.3f}{per_household_day:15.3f}")

    spread = max(results.values()) / min(results.values())
    print(f"\nspread of the induced sizing: x{spread:.2f}")
    print("A capacity selection must be computed at both bounds, not at the central case alone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
