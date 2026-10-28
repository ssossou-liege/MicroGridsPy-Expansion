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


def _normalise(frame: pd.DataFrame) -> pd.DataFrame:
    """Make a computed frame comparable with the same table read back from CSV.

    Round-tripping through CSV turns timestamps and cluster labels into strings, so both
    sides are cast to text before comparison; the numeric columns are compared as numbers.
    """
    out = frame.reset_index(drop=True).copy()
    for column in ("connection_date", "cluster", "month"):
        if column in out.columns:
            out[column] = out[column].astype(str)
    return out


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


def test_monthly_features_reproduce_committed_reference(clustering):
    """The per-observation feature table must match the committed calibration."""
    customers = clustering[0]
    readings = load_meter_readings(DEMAND_DIR, customers)
    got = _normalise(compute_monthly_features(readings, customers))
    expected = _normalise(pd.read_csv(REFERENCE_DIR / "monthly_household_features.csv"))
    pd.testing.assert_frame_equal(got, expected, check_dtype=False, rtol=1e-9)


def test_cluster_assignments_reproduce_committed_reference(clustering):
    """The per-observation cluster assignment must match the committed calibration.

    This table is the bridge between the segmentation and everything estimated from it;
    a stale copy would describe a different partition of the same households while every
    aggregate table still looked right.
    """
    _, clustered, _ = clustering
    columns = list(pd.read_csv(REFERENCE_DIR / "monthly_household_cluster_assignments.csv").columns)
    got = _normalise(clustered[columns].sort_values(
        ["site_name", "month", "customer_code"]))
    expected = _normalise(
        pd.read_csv(REFERENCE_DIR / "monthly_household_cluster_assignments.csv"))
    pd.testing.assert_frame_equal(got, expected, check_dtype=False, rtol=1e-9)


def test_every_observation_is_assigned_exactly_one_state(clustering):
    """Each household-month is either inactive, an outlier, or in one cluster."""
    _, clustered, _ = clustering
    states = set(clustered["cluster"].unique())
    assert states <= {"inactive", "outlier", *(str(i) for i in range(N_CLUSTERS))}
    assert clustered["cluster"].notna().all()
    # inactive and outlier are mutually exclusive by construction
    assert not (clustered["is_inactive"] & clustered["is_outlier"]).any()


# ------------------------------------------------- whose load, not which hardware
def test_a_class_is_selected_by_its_customer_and_never_by_a_meter_serial() -> None:
    """A meter is movable plant; what it recorded last year may belong to somebody else.

    The operator lifts a meter and reassigns it. The one the register lists today as the
    Samionta powerhouse was metering a place of worship in July 2024, and keyed on that
    serial those readings would have entered the calibration as the plant's own supply. In
    the other direction the Samionta powerhouse has been through three meters under two
    spellings. A serial answers "what hardware"; a calibration asks "whose load".

    Checked on the specification rather than on the data, because the data this runs
    against is not in the repository and the rule has to hold whatever it contains.
    """
    import inspect

    from microgrid_expansion.demand import build_community_profiles as build

    for klass, spec in build.METERS.items():
        assert "serials" not in spec, (
            f"{klass} is selected by meter serial; select it by the customer each reading "
            "names, because the meter may have been somebody else's")
        assert spec.get("codes") or spec.get("names_by_site"), (
            f"{klass} names no customer at all")

    source = inspect.getsource(build)
    assert "meter/customer/name" in source, (
        "the exports must be read on the customer each reading names")
    # The archive's own recovery of a malformed code goes through the meter register, which
    # is the same unreliable inference by another route.
    assert "code_recovered" in inspect.getsource(build._customer_readings)
