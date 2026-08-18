"""The authoritative segmentation of household-months into behavioural archetypes.

Two segmentations coexist in the calibration chain and they are not interchangeable.

The *exploratory* one clusters the observations by k-means and is what originally revealed
that four archetypes describe the measured behaviour. The *operative* one assigns each
observation to the nearest of the four reference profiles fixed by the RAMP appliance
calibration. They agree exactly on which observations are inactive or atypical, and differ
on 43 % of the archetype labels -- enough that statistics computed on one and appliance
parameters calibrated on the other describe different populations.

Everything downstream of the calibration must therefore use the *operative* partition: the
appliance parameters are defined for its archetypes, and the mixture law is estimated on
it. This module is the single place that partition is produced, so the question cannot be
answered inconsistently in two places again.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import numpy as np
import pandas as pd

from ..paths import DEMAND_DIR, REFERENCE_DIR
from .build_mixture_probabilities import assign_clusters_from_reference_profiles
from .build_monthly_household_clusters import (
    compute_monthly_features,
    load_census,
    load_meter_readings,
)

#: Behavioural archetypes carrying calibrated appliance parameters.
ARCHETYPES = ("0", "1", "2", "3")
INACTIVE = "inactive"
OUTLIER = "outlier"

#: Settings shared by both segmentations; they must agree or the two describe different
#: sets of inactive and atypical observations.
WINSOR_LOWER, WINSOR_UPPER = 0.01, 0.99
OUTLIER_MAD_THRESHOLD = 4.5

#: Minimum number of observations for an archetype's measured statistics to be usable as a
#: calibration target. Below it the statistics are reported but not fitted against.
MIN_SUPPORT = 30

PROFILES_PATH = REFERENCE_DIR / "archetype_profiles.csv"


@lru_cache(maxsize=1)
def _segment_cached() -> pd.DataFrame:
    """Segment once per process: the meter archive is re-read and re-featured otherwise."""
    return _segment_observations()


def segment_observations() -> pd.DataFrame:
    """Assign every measured household-month to its behavioural state.

    Cached for the life of the process. The segmentation reads the whole meter archive and
    recomputes the monthly features, which several callers need repeatedly; recomputing it
    each time dominated the cost of simulating a year.
    """
    return _segment_cached().copy()


def _segment_observations() -> pd.DataFrame:
    customers = load_census(DEMAND_DIR / "household_customers.csv")
    readings = load_meter_readings(DEMAND_DIR, customers)
    monthly = compute_monthly_features(readings, customers)
    segmented = assign_clusters_from_reference_profiles(
        monthly,
        winsor_lower_quantile=WINSOR_LOWER,
        winsor_upper_quantile=WINSOR_UPPER,
        outlier_mad_threshold=OUTLIER_MAD_THRESHOLD,
    )
    segmented["cluster"] = segmented["cluster"].astype(str)
    return segmented


def archetype_profiles(segmented: pd.DataFrame | None = None) -> pd.DataFrame:
    """Measured per-household statistics of each archetype, on the operative partition.

    These are the statistics the appliance parameters must reproduce, and the ones the
    moment-matching step targets. ``has_support`` marks the archetypes whose sample is
    large enough for that comparison to mean anything.
    """
    segmented = segment_observations() if segmented is None else segmented
    archetypes = segmented[segmented["cluster"].isin(ARCHETYPES)]
    profiles = archetypes.groupby("cluster").agg(
        n_observations=("mean_daily_kWh", "size"),
        mean_daily_kwh=("mean_daily_kWh", "mean"),
        median_daily_kwh=("mean_daily_kWh", "median"),
        mean_peak_w=("peak_power", "mean"),
        mean_load_factor=("load_factor", "mean"),
    )
    profiles = profiles.reindex(list(ARCHETYPES))
    profiles["has_support"] = profiles["n_observations"].fillna(0) >= MIN_SUPPORT
    return profiles


def state_shares(segmented: pd.DataFrame | None = None) -> pd.Series:
    """Share of observations in each behavioural state, including the non-archetypes."""
    segmented = segment_observations() if segmented is None else segmented
    return segmented["cluster"].value_counts(normalize=True).sort_index()


def load_archetype_profiles(path=PROFILES_PATH) -> pd.DataFrame:
    """Read the stored archetype profiles, producing them if absent."""
    if not path.exists():
        return write_archetype_profiles(path)
    profiles = pd.read_csv(path)
    profiles["cluster"] = profiles["cluster"].astype(str)
    return profiles.set_index("cluster")


def write_archetype_profiles(path=PROFILES_PATH) -> pd.DataFrame:
    """Compute the archetype profiles and store them next to the calibration."""
    profiles = archetype_profiles()
    path.parent.mkdir(parents=True, exist_ok=True)
    profiles.to_csv(path)
    return profiles


def main() -> int:
    segmented = segment_observations()
    profiles = archetype_profiles(segmented)
    write_archetype_profiles()

    print("Partition opérative (profils de référence RAMP)")
    print(profiles.round(3).to_string())
    print("\nRépartition de tous les états :")
    print((100 * state_shares(segmented)).round(1).to_string())

    weak = profiles.index[~profiles["has_support"]].tolist()
    if weak:
        print(f"\nArchétype(s) sans support empirique suffisant (< {MIN_SUPPORT} obs) : "
              f"{', '.join('C' + c for c in weak)}")
        print("  leurs paramètres d'appareils sont conservés tels quels, faute de mesure "
              "permettant de les corriger.")
    print(f"\nécrit {PROFILES_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
