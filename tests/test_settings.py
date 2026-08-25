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
    assert "economics.diesel_provenance" in unverified    # central value of an axis
    assert all(not p.verified for p in unverified.values())


def test_every_generator_carries_its_own_measured_curve():
    """The catalogue must be sourced unit by unit, not one curve stretched over sizes.

    A single curve rescaled to every rating would make the sizes indistinguishable on
    efficiency, and the certificate arbitrates precisely between them. The guard is that
    specific consumption is *not* an affine function of the rating: real engines depart
    from that, extrapolated ones cannot.
    """
    catalogue = default_generator_catalogue()
    assert catalogue and all(g.provenance.verified for g in catalogue)
    assert all("Perkins" in g.provenance.source for g in catalogue)

    specific = [g.fuel_l_per_h[1.0] / g.rating_kw for g in catalogue]
    assert len(set(specific)) == len(specific), "one curve rescaled, not measured units"
    assert not (specific[0] > specific[1] > specific[2]), "monotone: looks extrapolated"


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


# --------------------------------------------------- tariff target and subsidy
def test_a_generator_is_quoted_per_kva_and_sized_per_kw():
    """Conflating the two would understate the generator by the power factor."""
    from microgrid_expansion.settings import GeneratorSpec

    spec = GeneratorSpec(rating_kw=10.0, fuel_l_per_h={0.5: 2.0, 0.75: 2.6, 1.0: 3.4},
                         cost_usd_kva=400.0, power_factor=0.8)
    assert spec.cost_usd_kw == pytest.approx(500.0)
    assert spec.cost_usd_kw > spec.cost_usd_kva


def test_the_subsidy_closes_the_gap_between_cost_and_target():
    """A grant covering a share of the investment lowers the levelised cost in proportion."""
    from microgrid_expansion.post.economics import life_cycle_cost

    capacities = {"pv": 20.0, "battery": 60.0, "inverter": 8.0, "generator": 10.0}
    full = life_cycle_cost(capacities, 3000.0, 20_000.0)
    target = full.lcoe_usd_kwh / 2.0
    subsidised = life_cycle_cost(capacities, 3000.0, 20_000.0,
                                 tariff_target_usd_kwh=target)
    assert subsidised.subsidy_fraction == pytest.approx(0.5, rel=1e-9)
    assert subsidised.subsidy_usd == pytest.approx(0.5 * full.net_present_cost, rel=1e-9)
    assert subsidised.tariff_usd_kwh == pytest.approx(target)


def test_a_target_above_the_cost_needs_no_subsidy():
    from microgrid_expansion.post.economics import life_cycle_cost

    capacities = {"pv": 20.0, "battery": 60.0, "inverter": 8.0, "generator": 10.0}
    full = life_cycle_cost(capacities, 3000.0, 20_000.0)
    generous = life_cycle_cost(capacities, 3000.0, 20_000.0,
                               tariff_target_usd_kwh=full.lcoe_usd_kwh * 2)
    assert generous.subsidy_fraction == 0.0
    assert generous.subsidy_usd == 0.0


def test_without_a_target_the_tariff_is_the_levelised_cost():
    """Full cost recovery: the project charges what it costs."""
    from microgrid_expansion.post.economics import life_cycle_cost

    result = life_cycle_cost({"pv": 10.0, "battery": 20.0, "inverter": 5.0,
                              "generator": 5.0}, 1000.0, 10_000.0)
    assert result.tariff_target_usd_kwh is None
    assert result.tariff_usd_kwh == pytest.approx(result.lcoe_usd_kwh)
    assert result.cost_reflective_tariff_usd_kwh == pytest.approx(result.lcoe_usd_kwh)
    assert result.subsidy_fraction == 0.0


def test_the_discount_rate_is_sourced_and_lowering_it_reduces_the_annualised_cost():
    from microgrid_expansion.post.economics import life_cycle_cost

    settings = default_settings()
    assert settings.economics.discount_rate == pytest.approx(0.08)
    assert settings.economics.discount_provenance.verified
    assert "World Bank" in settings.economics.discount_provenance.source

    capacities = {"pv": 10.0, "battery": 20.0, "inverter": 5.0, "generator": 5.0}
    cheap = life_cycle_cost(capacities, 1000.0, 10_000.0, discount_rate=0.08)
    dear = life_cycle_cost(capacities, 1000.0, 10_000.0, discount_rate=0.12)
    assert cheap.annualised_cost < dear.annualised_cost


def test_the_tariff_target_can_be_switched_off():
    settings = default_settings()
    assert settings.economics.tariff_is_target is True
    settings.economics.tariff_is_target = False
    settings.validate()          # still a valid project


def test_an_unsourced_parameter_survives_a_round_trip(tmp_path):
    """Reloading a project must not quietly promote its placeholders to measurements.

    The guarantee this module makes is that an unsourced value announces itself. That
    guarantee lived only in memory: reconstruction keyed on the field *name* ``provenance``,
    so records named otherwise — the diesel price, the value of lost load — came back as
    plain mappings and the report came back empty. A project that reads its settings from a
    file, which is to say every real project, was told everything was sourced.
    """
    from microgrid_expansion.settings import ProjectSettings, Provenance, default_settings

    settings = default_settings()
    before = dict(settings.unverified())
    assert before, "the fixture needs at least one unsourced parameter"

    path = tmp_path / "projet.yaml"
    settings.save(path)
    reloaded = ProjectSettings.load(path)

    assert dict(reloaded.unverified()).keys() == before.keys()
    assert isinstance(reloaded.economics.diesel_provenance, Provenance)
    assert not reloaded.economics.diesel_provenance.verified
    # and a sourced one stays sourced, rather than everything being reported
    assert reloaded.photovoltaic.provenance.verified
