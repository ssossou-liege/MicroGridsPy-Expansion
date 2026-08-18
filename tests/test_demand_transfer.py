"""Transferability of the demand model to a site with no meter record.

The reference villages exist to calibrate archetypes, not to be sized; every site the
model is meant to serve has a census and nothing else. These tests cover the machinery that
makes that possible: one authoritative partition, a mixture conditioned on connection
maturity rather than on site identity, and an explicit envelope for the growth that the two
reference sites do not agree on.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from microgrid_expansion.demand import growth as GR
from microgrid_expansion.demand import maturity as MT
from microgrid_expansion.demand import partition as PT
from microgrid_expansion.demand.generator import simulate_demand_year
from microgrid_expansion.paths import DEMAND_DIR
from microgrid_expansion.sites import Site

pytestmark = pytest.mark.skipif(
    not (DEMAND_DIR / "household_customers.csv").exists(),
    reason="measured meter readings not available",
)


# --------------------------------------------------------------- one partition
@pytest.fixture(scope="module")
def segmented():
    return PT.segment_observations()


def test_the_two_segmentations_agree_on_the_non_archetype_states(segmented):
    """Inactive and atypical come from the shared feature preparation, so they must match."""
    from microgrid_expansion.demand import assign_clusters, compute_monthly_features
    from microgrid_expansion.demand import load_census, load_meter_readings

    customers = load_census(DEMAND_DIR / "household_customers.csv")
    monthly = compute_monthly_features(load_meter_readings(DEMAND_DIR, customers), customers)
    kmeans, _ = assign_clusters(monthly, n_clusters=4,
                                winsor_lower_quantile=PT.WINSOR_LOWER,
                                winsor_upper_quantile=PT.WINSOR_UPPER,
                                outlier_mad_threshold=PT.OUTLIER_MAD_THRESHOLD)
    for state in (PT.INACTIVE, PT.OUTLIER):
        assert (kmeans["cluster"] == state).sum() == (segmented["cluster"] == state).sum()


def test_archetype_profiles_report_their_support(segmented):
    """An archetype with too few observations must be marked, not silently trusted."""
    profiles = PT.archetype_profiles(segmented)
    assert list(profiles.index) == list(PT.ARCHETYPES)
    assert profiles["has_support"].sum() >= 3          # three well-populated archetypes
    weak = profiles.index[~profiles["has_support"]]
    for archetype in weak:
        assert profiles.loc[archetype, "n_observations"] < PT.MIN_SUPPORT


def test_calibration_targets_the_operative_partition():
    """The moment-matching must compare appliances with their own partition's statistics."""
    from microgrid_expansion.demand.calibration import measured_statistics

    stats = measured_statistics()
    assert "mean_daily_kwh" in stats.columns and "has_support" in stats.columns


# ------------------------------------------------------------------- maturity
def test_maturity_bands_cover_every_age():
    assert GR.maturity_band(0) == "0-3"
    assert GR.maturity_band(3) == "0-3"
    assert GR.maturity_band(4) == "4-6"
    assert GR.maturity_band(18) == "13-24"
    assert GR.maturity_band(600) == "25+"
    with pytest.raises(ValueError):
        GR.maturity_band(-1)


def test_maturity_mixture_is_a_distribution_for_every_stratum():
    matrix = MT.mixture_matrix()
    assert np.allclose(matrix.sum(axis=1), 1.0)
    assert (matrix >= 0).all().all()


def test_newly_connected_households_are_the_most_inactive():
    """The ramp-up after connection is the signal maturity conditioning exists to capture."""
    matrix = MT.mixture_matrix().xs("HH1", level="customer_type")
    assert matrix.loc["0-3", MT.INACTIVE] > matrix.loc["7-12", MT.INACTIVE]
    assert matrix.loc["0-3", MT.INACTIVE] > 0.05


# --------------------------------------------------------------------- growth
def test_the_three_trajectories_are_available_and_distinct():
    laws = {name: GR.trajectory_law(name) for name in GR.TRAJECTORIES}
    assert set(laws) == {"lente", "centrale", "rapide"}
    for law in laws.values():
        assert np.allclose(law.sum(axis=1), 1.0)
    slow = laws["lente"].xs("HH1", level="customer_type")
    fast = laws["rapide"].xs("HH1", level="customer_type")
    # the fast trajectory must put more mass on the high-consumption archetype by 2 years
    assert fast.loc["13-24", "2"] > slow.loc["13-24", "2"]


def test_unknown_trajectory_is_rejected():
    with pytest.raises(ValueError, match="unknown trajectory"):
        GR.trajectory_law("galopante")


def test_growth_envelope_brackets_the_two_observed_behaviours():
    envelope = GR.growth_envelope()
    assert set(envelope.factors.columns) == {"Gbowele", "Samionta"}
    assert np.allclose(envelope.factors.loc["0-3"], 1.0)     # each site is its own base
    assert envelope.spread > 1.5                             # they genuinely disagree


def test_seasonal_index_is_centred_on_one():
    index = GR.seasonal_index()
    assert len(index) == 12
    assert index.mean() == pytest.approx(1.0)
    assert (index > 0).all()


# ------------------------------------------------------------------- transfer
def test_a_site_with_only_a_census_can_be_simulated():
    """The case the model exists for: a locality with no meter record of its own."""
    new_site = Site(name="Sans-compteur", census={"HH1": 15, "HH2": 2, "HH3": 1})
    year = simulate_demand_year(new_site, year=2025, seed=3, maturity_months=0)
    assert year.hourly_kw.size == 8760
    assert (year.hourly_kw >= 0).all()
    assert year.annual_energy_kwh > 0


def test_the_community_ages_through_the_simulated_year():
    """A site connected at the start of the year must mature within it."""
    new_site = Site(name="Sans-compteur", census={"HH1": 40})
    year = simulate_demand_year(new_site, year=2025, seed=3, maturity_months=0)
    assert sum(year.composition[1].values()) == 40
    assert year.composition[1].get(MT.INACTIVE, 0) >= year.composition[12].get(MT.INACTIVE, 0)


def test_every_household_of_the_census_is_allocated_each_month():
    new_site = Site(name="Sans-compteur", census={"HH1": 12, "HH2": 5, "HH3": 3})
    year = simulate_demand_year(new_site, year=2025, seed=1, maturity_months=6)
    for month, counts in year.composition.items():
        assert sum(counts.values()) == 20, month
