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


def measured_monthly_energy(site) -> pd.Series:
    """Mean measured daily energy per household, by calendar month [kWh/household/day]."""
    features = pd.read_csv(REFERENCE_DIR / "monthly_household_features.csv")
    features = features[features["site_name"] == site.name].copy()
    features["calendar_month"] = pd.PeriodIndex(features["month"], freq="M").month
    return features.groupby("calendar_month")["mean_daily_kWh"].mean()


def mixture_predicted_energy(site) -> pd.Series:
    """Daily energy per household implied by the monthly mixture [kWh/household/day]."""
    mixture = load_monthly_mixture(site)
    profiles = pd.read_csv(REFERENCE_DIR / "global_cluster_profiles.csv")
    profiles["cluster"] = profiles["cluster"].astype(str)
    profiles = profiles.set_index("cluster")["cluster_mean_daily_kWh"]

    predicted = {}
    for month in range(1, 13):
        weights = mixture.xs(month, level="month").mean(axis=0)
        weights = _redistribute_outliers(weights)
        predicted[month] = sum(float(weights.get(c, 0.0)) * float(profiles[c])
                               for c in ARCHETYPES)
    return pd.Series(predicted)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", default="Samionta")
    parser.add_argument("--year", type=int, default=2025)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)
    site = get_site(args.site)

    measured = measured_monthly_energy(site)
    predicted = mixture_predicted_energy(site)
    comparison = pd.DataFrame({"mesuré": measured, "mélange": predicted})
    comparison["écart %"] = 100 * (comparison["mélange"] - comparison["mesuré"]) / comparison["mesuré"]

    print(f"=== {site.name} — la loi de mélange mensuelle reproduit-elle la saison ? ===")
    print(comparison.round(3).to_string())
    correlation = comparison["mélange"].corr(comparison["mesuré"])
    print(f"\ncorrélation                : {correlation:.3f}")
    print(f"amplitude saisonnière mesurée : {measured.max() / measured.min():.2f}x")
    print(f"amplitude saisonnière simulée : {predicted.max() / predicted.min():.2f}x")

    print(f"\n=== année stochastique complète (graine {args.seed}) ===")
    year = simulate_demand_year(site, year=args.year, seed=args.seed)
    days = {m: calendar.monthrange(args.year, m)[1] for m in range(1, 13)}
    measured_year = sum(measured[m] * site.n_households * days[m] for m in range(1, 13))
    print(f"heures                   : {year.hourly_kw.size}")
    print(f"énergie simulée          : {year.annual_energy_kwh:>10,.0f} kWh")
    print(f"énergie mesurée (extrap.): {measured_year:>10,.0f} kWh")
    print(f"écart                    : {100 * (year.annual_energy_kwh - measured_year) / measured_year:>+9.1f} %")
    print(f"pointe                   : {year.peak_kw:.2f} kW")
    print(f"facteur de charge        : {year.load_factor:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
