"""Reproducibility of the demand-calibration layer.

The behavioural clustering of the measured meter readings is the foundation every
downstream demand quantity rests on: the mixture probabilities, the RAMP appliance
calibration, and ultimately the community load profiles the sizing model consumes. It
must therefore be exactly reproducible from the committed inputs with the documented
default settings -- otherwise the calibration in ``data/ramp_params/reference/`` and the
code that claims to produce it silently drift apart.

These tests re-run the clustering from the raw meter readings and compare it with the
committed reference outputs.
"""
from __future__ import annotations

import pandas as pd
import pytest

from microgrid_expansion.demand import (
    assign_clusters,
    build_cluster_summary,
    compute_monthly_features,
    load_census,
    load_meter_readings,
)
from microgrid_expansion.paths import DEMAND_DIR, REFERENCE_DIR

# Defaults of build_monthly_household_clusters.parse_args; kept in one place so a change
# to either the script or this test is visible as a deliberate recalibration.
N_CLUSTERS = 4
WINSOR_LOWER, WINSOR_UPPER = 0.01, 0.99
OUTLIER_MAD_THRESHOLD = 4.5

pytestmark = pytest.mark.skipif(
    not (DEMAND_DIR / "household_customers.csv").exists(),
    reason="measured meter readings not available",
)


@pytest.fixture(scope="module")
def clustering():
    """Re-run the segmentation from the raw readings with the default settings."""
    customers = load_census(DEMAND_DIR / "household_customers.csv")
    readings = load_meter_readings(DEMAND_DIR, customers)
    monthly = compute_monthly_features(readings, customers)
    clustered, profiles = assign_clusters(
        monthly,
        n_clusters=N_CLUSTERS,
        winsor_lower_quantile=WINSOR_LOWER,
        winsor_upper_quantile=WINSOR_UPPER,
        outlier_mad_threshold=OUTLIER_MAD_THRESHOLD,
    )
    return customers, clustered, profiles


def test_cluster_profiles_reproduce_committed_reference(clustering):
    """The global cluster profiles must match the committed calibration exactly."""
    _, _, profiles = clustering
    expected = pd.read_csv(REFERENCE_DIR / "global_cluster_profiles.csv")
    got = profiles.reset_index(drop=True)
    expected["cluster"] = expected["cluster"].astype(str)
    got["cluster"] = got["cluster"].astype(str)
    pd.testing.assert_frame_equal(
        got.sort_values("cluster").reset_index(drop=True),
        expected.sort_values("cluster").reset_index(drop=True),
        check_dtype=False,
        rtol=1e-9,
    )


@pytest.mark.parametrize(
    ("site", "filename"),
    [("Gbowele", "gbowele_monthly_cluster_summary.csv"),
     ("Samionta", "samionta_monthly_cluster_summary.csv")],
)
def test_monthly_summaries_reproduce_committed_reference(clustering, site, filename):
    """Each site's monthly cluster composition must match the committed calibration."""
    customers, clustered, _ = clustering
    got = build_cluster_summary(clustered, customers, site).reset_index(drop=True)
    expected = pd.read_csv(REFERENCE_DIR / filename)
    got["cluster"] = got["cluster"].astype(str)
    expected["cluster"] = expected["cluster"].astype(str)
    pd.testing.assert_frame_equal(got, expected, check_dtype=False, rtol=1e-9)


def test_every_observation_is_assigned_exactly_one_state(clustering):
    """Each household-month is either inactive, an outlier, or in one cluster."""
    _, clustered, _ = clustering
    states = set(clustered["cluster"].unique())
    assert states <= {"inactive", "outlier", *(str(i) for i in range(N_CLUSTERS))}
    assert clustered["cluster"].notna().all()
    # inactive and outlier are mutually exclusive by construction
    assert not (clustered["is_inactive"] & clustered["is_outlier"]).any()
