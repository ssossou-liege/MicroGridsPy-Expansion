"""Project parameters: user-supplied, validated, and declared exactly once.

Three defects in this project were traced to a quantity being defined in two places and
the two definitions drifting apart. These tests keep the remaining duplicates from coming
back, and check that a project file round-trips, rejects nonsense, and tells the user which
of its parameters nobody has sourced.
"""
from __future__ import annotations

import numpy as np
import pytest

from microgrid_expansion.settings import (
    GeneratorSpec,
    ProjectSettings,
    Provenance,
    default_generator_catalogue,
    default_settings,
    write_template,
)


# ------------------------------------------------------------------ round trip
def test_a_saved_project_reloads_identically(tmp_path):
    settings = default_settings()
    path = settings.save(tmp_path / "projet.yaml")
    assert ProjectSettings.load(path).to_dict() == settings.to_dict()


def test_a_user_edit_is_honoured(tmp_path):
    import yaml

    path = default_settings().save(tmp_path / "p.yaml")
    raw = yaml.safe_load(path.read_text())
    raw["economics"]["diesel_price_usd_l"] = 1.55
    raw["battery"]["chemistry"] = "lead_acid"
    raw["controller"]["lookahead_hours"] = 8
    path.write_text(yaml.safe_dump(raw))

    settings = ProjectSettings.load(path)
    assert settings.economics.diesel_price_usd_l == 1.55
    assert settings.battery.chemistry == "lead_acid"
    assert settings.controller.lookahead_hours == 8


def test_an_omitted_section_falls_back_to_the_default(tmp_path):
    path = tmp_path / "minimal.yaml"
    path.write_text("site: Gbowele\nyear: 2024\n")
    settings = ProjectSettings.load(path)
    assert settings.site == "Gbowele" and settings.year == 2024
    assert settings.battery.chemistry == "lfp"          # untouched default


def test_the_template_is_a_valid_project(tmp_path):
    path = write_template(tmp_path / "template.yaml")
    assert "provenance" in path.read_text()
    ProjectSettings.load(path).validate()


# ------------------------------------------------------------------ validation
@pytest.mark.parametrize(("section", "key", "value"), [
    ("battery", "chemistry", "nickel"),
    ("economics", "discount_rate", 1.5),
    ("economics", "horizon_years", 0),
])
def test_impossible_values_are_rejected(section, key, value):
    settings = default_settings()
    setattr(getattr(settings, section), key, value)
    with pytest.raises(ValueError):
        settings.validate()


def test_a_battery_with_inverted_limits_is_rejected():
    settings = default_settings()
    settings.battery.soc_min, settings.battery.soc_max = 0.9, 0.1
    with pytest.raises(ValueError, match="state-of-charge"):
        settings.validate()


def test_duplicate_generator_ratings_are_rejected():
    settings = default_settings()
    settings.generators.append(settings.generators[0])
    with pytest.raises(ValueError, match="duplicate generator ratings"):
        settings.validate()


def test_an_empty_catalogue_is_rejected():
    settings = default_settings()
    settings.generators = []
    with pytest.raises(ValueError, match="catalogue must not be empty"):
        settings.validate()


def test_an_unknown_demand_trajectory_is_rejected():
    settings = default_settings()
    settings.demand_trajectory = "galopante"
    with pytest.raises(ValueError, match="trajectory"):
        settings.validate()


# ------------------------------------------------------- equipment describes itself
def test_each_generator_carries_its_own_fuel_curve():
    """The certificate branches over generator size; one shared curve would blur them."""
    catalogue = default_generator_catalogue()
    assert len({g.rating_kw for g in catalogue}) == len(catalogue)
    for spec in catalogue:
        assert set(spec.fuel_l_per_h) == {0.5, 0.75, 1.0}
        # consumption must grow with load, and with rating at equal load
        loads = sorted(spec.fuel_l_per_h)
        assert all(spec.fuel_l_per_h[a] < spec.fuel_l_per_h[b]
                   for a, b in zip(loads, loads[1:]))
    big, small = max(catalogue, key=lambda g: g.rating_kw), min(catalogue, key=lambda g: g.rating_kw)
    assert big.fuel_l_per_h[1.0] > small.fuel_l_per_h[1.0]


def test_the_efficiency_curve_reproduces_the_datasheet():
    """The fit must return the consumption it was built from."""
    spec = GeneratorSpec(rating_kw=16.0, fuel_l_per_h={0.5: 3.0, 0.75: 4.0, 1.0: 5.3})
    from microgrid_expansion.exact.simulator import GeneratorModel

    model = GeneratorModel.from_spec(spec, fuel_price_usd_l=1.29)
    for load, reference in spec.fuel_l_per_h.items():
        assert float(model.fuel_litres(load * 16.0, 16.0)) == pytest.approx(reference, rel=1e-3)


def test_a_generator_without_enough_points_is_rejected():
    spec = GeneratorSpec(rating_kw=10.0, fuel_l_per_h={1.0: 3.0})
    with pytest.raises(ValueError, match="three fuel points"):
        spec.efficiency_coefficients()


def test_the_battery_model_is_built_from_the_pack_settings():
    from microgrid_expansion.exact.simulator import BatteryModel

    settings = default_settings()
    settings.battery.c_rate = 0.4
    settings.battery.initial_soc_fraction = 0.3
    model = BatteryModel.from_spec(settings.battery)
    assert model.c_rate == 0.4 and model.initial_soc_fraction == 0.3
    assert model.chemistry == settings.battery.chemistry


# ------------------------------------------------------------------- provenance
def test_unsourced_parameters_are_reported():
    """A placeholder must announce itself rather than pass as a measurement."""
    unverified = dict(default_settings().unverified())
    assert "economics.voll_provenance" in unverified      # argued, not measured
    assert "photovoltaic.provenance" in unverified        # generic datasheet values
    assert all(not p.verified for p in unverified.values())


def test_the_measured_generator_is_marked_verified():
    catalogue = default_generator_catalogue()
    measured = [g for g in catalogue if g.provenance.verified]
    assert len(measured) == 1 and measured[0].rating_kw == 16.0


def test_a_sourced_parameter_stops_being_reported():
    settings = default_settings()
    settings.inverter.provenance = Provenance(source="catalogue", verified=True)
    assert "inverter.provenance" not in dict(settings.unverified())


# --------------------------------------------------- no duplicated definitions
def test_the_census_has_a_single_definition():
    from microgrid_expansion.demand.build_monthly_household_clusters import CENSUS_TOTALS
    from microgrid_expansion.sites import SITES

    assert CENSUS_TOTALS == {name: dict(site.census) for name, site in SITES.items()}


def test_the_meter_files_have_a_single_definition():
    from microgrid_expansion.demand.build_monthly_household_clusters import SITE_FILES
    from microgrid_expansion.sites import SITES

    assert SITE_FILES == {n: s.meter_file for n, s in SITES.items() if s.meter_file}


def test_no_second_linear_fuel_model_survives_in_the_configuration():
    """A linear pair here once disagreed with the fitted curve by 59 % on the intercept."""
    from microgrid_expansion import config

    assert not hasattr(config, "FUEL_F0")
    assert not hasattr(config, "FUEL_F1")


def test_the_reference_profiles_live_with_the_data():
    """Twelve numbers defining the operative partition belong beside the calibration."""
    from microgrid_expansion.paths import REFERENCE_DIR

    assert (REFERENCE_DIR / "archetype_reference_profiles.csv").exists()


def test_the_site_carries_its_own_time_zone():
    from microgrid_expansion.sites import SITES

    assert all(isinstance(s.utc_offset_hours, int) for s in SITES.values())


# ------------------------------------------------------------------- currency
def test_costs_convert_between_the_field_and_the_model_currency():
    """Equipment is quoted in CFA francs; the model computes in dollars."""
    settings = default_settings()
    currency = settings.currency
    assert currency.local_code == "XOF"
    # the peg is fixed; only the euro-dollar rate moves
    assert currency.xof_per_eur == pytest.approx(655.957)
    assert currency.to_local(currency.to_usd(250_000.0)) == pytest.approx(250_000.0)
    # the inverter price restates to the figure it was quoted at
    assert currency.to_local(settings.inverter.cost_usd_kw) == pytest.approx(250_000, rel=0.01)
    assert currency.to_local(settings.economics.tariff_usd_kwh) == pytest.approx(160, rel=0.01)


# --------------------------------------------------- value of lost load
def test_the_value_of_lost_load_cannot_fall_below_the_tariff():
    """Households pay the tariff, so they value a kilowatt-hour at least that much."""
    settings = default_settings()
    settings.economics.value_of_lost_load_usd_kwh = 0.10
    settings.economics.value_of_lost_load_range_usd_kwh = (0.05, 3.0)
    with pytest.raises(ValueError, match="below the tariff"):
        settings.validate()


def test_the_value_of_lost_load_must_lie_inside_its_reported_range():
    settings = default_settings()
    settings.economics.value_of_lost_load_usd_kwh = 5.0
    with pytest.raises(ValueError, match="inside its own reported range"):
        settings.validate()


def test_the_value_of_lost_load_exceeds_the_marginal_cost_of_generation():
    """Below it the optimiser would shed load rather than run the generator."""
    from microgrid_expansion.exact.lower_bound import fuel_minorant
    from microgrid_expansion.exact.simulator import GeneratorModel

    settings = default_settings()
    price = settings.economics.diesel_price_usd_l
    for spec in settings.generators:
        model = GeneratorModel.from_spec(spec, price)
        _, slope = fuel_minorant(model, spec.rating_kw)
        marginal = slope * price
        assert settings.economics.value_of_lost_load_usd_kwh > marginal, spec.rating_kw


def test_the_value_of_lost_load_is_reported_as_a_range_not_a_point():
    """It sets the reliability the design aims at, so the sizing is reported across it."""
    settings = default_settings()
    low, high = settings.economics.value_of_lost_load_range_usd_kwh
    assert low < settings.economics.value_of_lost_load_usd_kwh < high
    assert not settings.economics.voll_provenance.verified   # still an argued choice


def test_the_inverter_price_is_now_sourced():
    assert "inverter.provenance" not in dict(default_settings().unverified())
    assert default_settings().inverter.provenance.verified
