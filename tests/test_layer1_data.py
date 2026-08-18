"""Layer 1: the data layer that turns calibration into the model's two hourly series.

The tests check the properties the sizing model relies on -- lengths, physical bounds,
conservation of the community census, and the direction of each physical effect -- rather
than re-running the full stochastic year, which is exercised by the validation script.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from microgrid_expansion.demand import generator as G
from microgrid_expansion.paths import REFERENCE_DIR
from microgrid_expansion.resource import (
    ModuleSpec,
    battery_self_discharge,
    battery_usable_fraction,
    cell_temperature,
    simulate_resource_year,
    specific_yield,
)
from microgrid_expansion.sites import GBOWELE, SAMIONTA, SITES, get_site

pytestmark = pytest.mark.skipif(
    not (REFERENCE_DIR / "mixture_probabilities_type_month.csv").exists(),
    reason="demand calibration not available",
)


# --------------------------------------------------------------------- registry
def test_registry_exposes_both_reference_sites():
    assert set(SITES) == {"Samionta", "Gbowele"}
    assert SAMIONTA.n_households == 231
    assert GBOWELE.n_households == 159
    with pytest.raises(KeyError):
        get_site("Nowhere")


def test_missing_irradiance_is_reported_not_guessed():
    """A site without a registered series must fail clearly, not silently."""
    from microgrid_expansion.sites import Site

    unserved = Site(name="Nulle-part", census={"HH1": 10}, irradiance_file=None)
    with pytest.raises(FileNotFoundError, match="no irradiance series"):
        unserved.irradiance_path()


def test_both_reference_sites_have_a_complete_meteorological_series():
    """Each registered site resolves to a series carrying all four quantities."""
    import pandas as pd

    for site in (SAMIONTA, GBOWELE):
        frame = pd.read_csv(site.irradiance_path(), nrows=5)
        assert {"timestamp", "irradiance_w_m2", "temperature_c",
                "wind_speed_m_s"} <= set(frame.columns), site.name


# ---------------------------------------------------------------------- mixture
def test_monthly_mixture_covers_the_year_and_is_a_distribution():
    mixture = G.load_monthly_mixture(SAMIONTA)
    months = mixture.index.get_level_values("month").unique()
    assert sorted(months) == list(range(1, 13))
    assert np.allclose(mixture.sum(axis=1), 1.0)
    assert (mixture >= 0).all().all()


def test_outlier_mass_is_redistributed_over_archetypes_only():
    weights = pd.Series({"0": 0.2, "1": 0.3, "2": 0.1, "3": 0.2,
                         G.INACTIVE: 0.1, G.OUTLIER: 0.1})
    out = G._redistribute_outliers(weights)
    assert G.OUTLIER not in out.index
    assert out.sum() == pytest.approx(1.0)
    # the inactive state keeps its own mass, the outlier mass goes to the archetypes
    assert out[G.INACTIVE] == pytest.approx(0.1)
    assert out[["0", "1", "2", "3"]].sum() == pytest.approx(0.9)
    # redistribution is proportional: the ordering of archetypes is preserved
    assert out["1"] > out["0"] == out["3"] > out["2"]


def test_outlier_mass_falls_back_to_inactive_when_no_archetype_has_mass():
    weights = pd.Series({"0": 0.0, "1": 0.0, "2": 0.0, "3": 0.0,
                         G.INACTIVE: 0.8, G.OUTLIER: 0.2})
    out = G._redistribute_outliers(weights)
    assert out[G.INACTIVE] == pytest.approx(1.0)


def test_composition_allocates_every_household_of_the_census():
    mixture = G.load_monthly_mixture(SAMIONTA)
    rng = np.random.default_rng(0)
    for month in range(1, 13):
        counts = G.sample_composition(mixture, SAMIONTA.census, month, rng)
        assert sum(counts.values()) == SAMIONTA.n_households
        assert all(n >= 0 for n in counts.values())


# ------------------------------------------------------------------- appliances
def test_appliance_specs_respect_ramp_window_and_duty_bounds():
    """RAMP rejects a duty cycle that cannot fit its randomised window."""
    for archetype, appliances in G.load_archetype_appliances().items():
        for _, row in appliances.iterrows():
            spec = G._appliance_spec(row)
            if spec is None:
                continue
            start, end = spec["window"]
            width = end - start
            assert 0 <= start < end <= G.MINUTES_PER_DAY
            assert 1 <= spec["func_cycle"] <= spec["func_time"]
            assert spec["func_time"] <= 0.99 * width
            worst_case_width = (1.0 - 2.0 * spec["window_var"]) * width
            assert spec["func_cycle"] <= 0.99 * worst_case_width + 1e-9
            assert 0.0 <= spec["occasional_use"] <= 1.0


def test_fractional_appliance_counts_are_realised_in_expectation():
    """A calibrated mean of 1.33 lamps must not be rounded to one."""
    rng = np.random.default_rng(0)
    draws = [G._realise_count(1.33, rng) for _ in range(4000)]
    assert set(draws) <= {1, 2}
    assert np.mean(draws) == pytest.approx(1.33, abs=0.03)


def test_appliance_power_and_duration_scale_as_requested():
    row = pd.Series({"power": 10.0, "func_time": 60.0, "func_cycle": 10.0,
                     "number": 1.0, "occasional_use": 1.0,
                     "w1_start": 0.0, "w1_end": 1440.0}, name="test")
    plain = G._appliance_spec(row)
    scaled = G._appliance_spec(row, power_scale=2.0, time_scale=0.5)
    assert scaled["power"] == pytest.approx(2.0 * plain["power"])
    assert scaled["func_time"] == pytest.approx(0.5 * plain["func_time"], abs=1)


# ----------------------------------------------------------------------- demand
def test_one_simulated_month_is_physical():
    appliances = G.load_archetype_appliances()
    rng = np.random.default_rng(1)
    minutes = G._simulate_month({"1": 10, "2": 10}, appliances, 2025, 3, seed=1, rng=rng)
    assert minutes.size == 31 * G.MINUTES_PER_DAY
    assert (minutes >= 0).all()
    hourly = G._to_hourly_kw(minutes)
    assert hourly.size == 31 * 24
    # hourly mean power cannot exceed the highest minute of the same hour
    assert hourly.max() <= minutes.max() / 1000.0 + 1e-9


def test_a_community_of_inactive_households_draws_nothing():
    appliances = G.load_archetype_appliances()
    rng = np.random.default_rng(1)
    minutes = G._simulate_month({G.INACTIVE: 50}, appliances, 2025, 2, seed=1, rng=rng)
    assert minutes.sum() == 0.0


# --------------------------------------------------------------------- resource
def test_specific_yield_is_bounded_and_grows_with_irradiance():
    ghi = np.array([0.0, 250.0, 500.0, 800.0, 1000.0])
    y = specific_yield(ghi, np.full(ghi.shape, 25.0))
    assert y[0] == 0.0
    assert np.all(np.diff(y) > 0)
    assert np.all(y >= 0.0) and y.max() < 1.0        # derating keeps it below unity


def test_hotter_cells_produce_less():
    ghi = np.full(24, 800.0)
    cool = specific_yield(ghi, np.full(24, 20.0))
    hot = specific_yield(ghi, np.full(24, 40.0))
    assert (hot < cool).all()
    assert (cell_temperature(ghi, np.full(24, 20.0)) > 20.0).all()


def test_battery_derating_and_self_discharge_follow_temperature():
    mild = battery_usable_fraction(np.array([25.0]))[0]
    assert mild == pytest.approx(1.0)
    assert battery_usable_fraction(np.array([0.0]))[0] < mild      # cold derating
    assert battery_usable_fraction(np.array([50.0]))[0] < mild     # hot derating
    a25 = battery_self_discharge(np.array([25.0]))[0]
    a35 = battery_self_discharge(np.array([35.0]))[0]
    assert a35 == pytest.approx(2.0 * a25, rel=1e-6)               # doubles per 10 K
    assert 0.0 < a25 < 1.0


def test_resource_year_requires_a_stated_temperature():
    """A series without temperature must fail, not fall back to an invented value."""
    from microgrid_expansion.paths import IRRADIANCE_DIR
    from microgrid_expansion.sites import Site

    series = IRRADIANCE_DIR / "_test_without_temperature.csv"
    hours = pd.date_range("2024-01-01", periods=48, freq="h")
    pd.DataFrame({"timestamp": hours, "irradiance_w_m2": np.zeros(48)}).to_csv(
        series, index=False)
    try:
        site = Site(name="Nu", census={"HH1": 1}, irradiance_file=series.name)
        with pytest.raises(ValueError, match="ambient-temperature"):
            simulate_resource_year(site, 2024)
    finally:
        series.unlink(missing_ok=True)


def test_measured_temperature_and_wind_drive_a_faiman_cell_model():
    """With wind available the convective cooling must actually be used."""
    year = simulate_resource_year(SAMIONTA, 2024)
    assert year.isothermal is False
    assert year.cell_model == "faiman"
    assert 1000 < year.annual_yield_kwh_per_kw < 2000
    assert 15.0 < year.t_amb_c.mean() < 40.0


def test_wind_cooling_raises_yield_relative_to_still_air():
    """Faiman with wind must give a cooler cell, hence more power, than without."""
    from microgrid_expansion.resource import specific_yield

    ghi = np.full(24, 900.0)
    t_amb = np.full(24, 30.0)
    still = specific_yield(ghi, t_amb, wind_m_s=np.zeros(24))
    breezy = specific_yield(ghi, t_amb, wind_m_s=np.full(24, 4.0))
    assert (breezy > still).all()


def test_resource_year_under_an_isothermal_assumption_is_flagged():
    year = simulate_resource_year(SAMIONTA, 2024, t_amb_c=28.0)
    assert year.isothermal is True
    assert year.specific_yield.size == 8784                        # 2024 is a leap year
    assert 800 < year.annual_yield_kwh_per_kw < 2200               # plausible for Benin
    assert year.usable_fraction.shape == year.specific_yield.shape
    assert year.self_discharge.shape == year.specific_yield.shape


def test_unknown_year_is_reported_with_the_available_ones():
    with pytest.raises(ValueError, match="available"):
        simulate_resource_year(SAMIONTA, 1990, t_amb_c=28.0)
