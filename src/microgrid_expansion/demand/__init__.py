"""Calibration of the demand inputs from measured meter readings.

Two steps, each usable as a library function or from the command line:

* :mod:`~microgrid_expansion.demand.build_monthly_household_clusters` — turns raw
  quarter-hourly meter readings into monthly household observations described by daily
  energy, peak power and load factor, and segments them into behavioural clusters that
  are stable across months and across the two reference sites.
* :mod:`~microgrid_expansion.demand.build_mixture_probabilities` — estimates, by site,
  household type and month, the hierarchical Dirichlet-multinomial posterior over
  behavioural clusters, with shrinkage towards a balanced cross-site reference and
  explicit credibility bounds.

The resulting mixture probabilities are what the stochastic demand generator samples
from when it composes a community; the per-cluster appliance parameters it then hands to
RAMP live in ``data/ramp_params/reference/cluster_params.csv``.
"""
from __future__ import annotations

from .build_monthly_household_clusters import (
    CENSUS_TOTALS,
    HOUSEHOLD_TYPES,
    SITE_FILES,
    assign_clusters,
    build_cluster_summary,
    compute_monthly_features,
    load_census,
    load_meter_readings,
)
from .build_mixture_probabilities import (
    REFERENCE_CLUSTER_FEATURES,
    assign_clusters_from_reference_profiles,
    build_probability_table,
)

__all__ = [
    "CENSUS_TOTALS",
    "HOUSEHOLD_TYPES",
    "SITE_FILES",
    "REFERENCE_CLUSTER_FEATURES",
    "assign_clusters",
    "assign_clusters_from_reference_profiles",
    "build_cluster_summary",
    "build_probability_table",
    "compute_monthly_features",
    "load_census",
    "load_meter_readings",
]
