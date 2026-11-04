"""The four price sets, and the one thing that would make comparing them meaningless.

The sets are not four guesses. Three of them are the same procurement budget read on its
two price columns, with and without the landing it measures on its payment ledger, and the
fourth is the central one with the cells at the price the next extension is budgeted at. So
they stand in a known order, every one of them carries the balance of plant that scales with
its capacity, and the middle one has to be exactly what the rest of this work is computed
on. A central set that drifts from the settings would make every comparison in the study a
comparison with nothing.

The sets are also compared against the noise of the draw, and that comparison is the whole
of the study's caution: a root that moves less between two price sets than it moves between
two random seeds has not moved. The reading of that is held here too, because getting the
inequality backwards would turn the caution into its opposite.
"""
from __future__ import annotations

import pytest

from microgrid_expansion.exact.price_sensitivity import (PARTS, PRICE_SETS, REFERENCE,
                                                         derive, settings_at)
from microgrid_expansion.settings import default_settings

CAPACITIES = ("array_usd_kw", "storage_usd_kwh", "conversion_usd_kw", "generator_usd_kva")


def test_the_central_set_is_what_the_settings_carry() -> None:
    """Otherwise the study compares its variants against a plant nobody else sized."""
    settings = default_settings()
    central = PRICE_SETS[REFERENCE]

    assert central["array_usd_kw"] == pytest.approx(settings.photovoltaic.cost_usd_kw)
    assert central["storage_usd_kwh"] == pytest.approx(settings.battery.cost_usd_kwh)
    assert central["conversion_usd_kw"] == pytest.approx(settings.inverter.cost_usd_kw)
    assert central["generator_usd_kva"] == pytest.approx(
        settings.generators[0].cost_usd_kva)


@pytest.mark.parametrize("capacity", CAPACITIES)
def test_the_three_readings_of_the_budget_stand_in_order(capacity: str) -> None:
    """Offshore, then landed, then bought in Benin: the landing cannot be negative."""
    low = PRICE_SETS["low"][capacity]
    central = PRICE_SETS["central"][capacity]
    high = PRICE_SETS["high"][capacity]
    assert low < central < high, f"{capacity}: {low}, {central}, {high}"


def test_the_landing_between_the_low_and_central_sets_is_the_measured_uplift() -> None:
    """Both sets come from the same offshore column, so the ratio is one number.

    The array and the storage carry a balance of plant that is landed on the same basis as
    the units, so the ratio holds for them too; a set built by landing one and not the other
    would show up here as a capacity out of line with the rest.
    """
    from microgrid_expansion.build_equipment_prices import LANDING_UPLIFT

    for capacity in CAPACITIES:
        ratio = PRICE_SETS["central"][capacity] / PRICE_SETS["low"][capacity]
        assert ratio == pytest.approx(1.0 + LANDING_UPLIFT, rel=0.01), capacity


def test_the_byd_variant_moves_the_storage_and_nothing_else() -> None:
    """It is the central set asked one question, not a fourth price list."""
    central, byd = PRICE_SETS["central"], PRICE_SETS["byd"]
    assert byd["storage_usd_kwh"] > central["storage_usd_kwh"]
    for capacity in CAPACITIES:
        if capacity == "storage_usd_kwh":
            continue
        assert byd[capacity] == pytest.approx(central[capacity])


@pytest.mark.parametrize("name", list(PRICE_SETS))
def test_a_price_set_reaches_the_settings_the_sizing_reads(name: str) -> None:
    """A set that is recorded and not applied would be a study of one price list."""
    prices = PRICE_SETS[name]
    settings = settings_at(prices)

    assert settings.photovoltaic.cost_usd_kw == pytest.approx(prices["array_usd_kw"])
    assert settings.battery.cost_usd_kwh == pytest.approx(prices["storage_usd_kwh"])
    assert settings.inverter.cost_usd_kw == pytest.approx(prices["conversion_usd_kw"])
    for generator in settings.generators:
        assert generator.cost_usd_kva == pytest.approx(prices["generator_usd_kva"])
    # The catalogue keeps its ratings: only the price of a kilovolt-ampere moved.
    assert [g.rating_kw for g in settings.generators] == \
           [g.rating_kw for g in default_settings().generators]


def test_the_string_inverter_keeps_its_one_price_in_every_set() -> None:
    """There is one quotation for it, so no set can move it, and the study says so."""
    for name in PRICE_SETS:
        assert "string" not in " ".join(PRICE_SETS[name]), name
        assert settings_at(PRICE_SETS[name]).coupling.string_inverter_cost_usd_kw == \
               pytest.approx(default_settings().coupling.string_inverter_cost_usd_kw)


def _record(roots: dict[str, dict], costs: dict[str, float], noise_span: float) -> dict:
    """A stored study with two seeds that differ by ``noise_span`` kilowatts of field."""
    reference = roots[REFERENCE]
    shifted = dict(reference, pv_kw=reference["pv_kw"] + noise_span)
    span = {"expected_usd": {"span": 0.0, "span_pct": 0.0}}
    for part, read in PARTS:
        span[part] = {"least": read(reference), "most": read(shifted),
                      "span": abs(read(shifted) - read(reference))}
    return {
        "sets": {name: {oracle: {"root": root, "expected_usd": costs[name]}
                        for oracle in ("programme", "automaton")}
                 for name, root in roots.items()},
        "noise": {oracle: span for oracle in ("programme", "automaton")},
    }


def test_a_root_that_moves_less_than_the_draw_does_has_not_moved() -> None:
    """The reading the whole study rests on, in both directions."""
    plant = {"pv_kw": 40.0, "pv_ac_kw": 20.0, "battery_kwh": 180.0,
             "inverter_kw": 32.5, "generator_kw": 8.0}
    roots = {REFERENCE: plant,
             "low": dict(plant, pv_kw=42.0),            # 2 kW away
             "high": dict(plant, pv_kw=70.0)}           # 30 kW away
    costs = {REFERENCE: 80_000.0, "low": 74_000.0, "high": 190_000.0}

    derived = derive(_record(roots, costs, noise_span=6.0))["programme"]["sets"]

    assert not derived["low"]["parts"]["field_kw"]["beyond_the_noise"]
    assert not derived["low"]["any_part_beyond_the_noise"]
    assert derived["high"]["parts"]["field_kw"]["beyond_the_noise"]
    assert derived["high"]["any_part_beyond_the_noise"]
    # The reference is compared with itself, so nothing of it can be beyond the noise.
    assert not derived[REFERENCE]["any_part_beyond_the_noise"]
    assert derived["high"]["parts"]["field_kw"]["shift_from_reference"] == pytest.approx(
        30.0)
