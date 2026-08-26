"""Economic-trajectory realisations: fuel price and per-technology investment cost.

A twenty-year plan cannot be costed at today's prices. Which way they move, and how fast,
is itself uncertain, so the rates are drawn rather than assumed: each path picks one of
three futures and holds it for the whole horizon, prices within a path moving coherently
rather than independently year by year. A world where storage learns quickly is a world
where converters do too, and pretending otherwise would manufacture a diversification the
market does not offer.

The rates themselves are declared in the project settings with their sources, so that a
project sizing a plant elsewhere replaces them without touching this module.
"""
from __future__ import annotations

import numpy as np

from ..settings import ProjectSettings, default_settings
from .uncertainty_space import EconomicAxis

#: The three futures, shared by every technology so that a draw is coherent.
COST_SCENARIOS = ("bas", "central", "haut")


def draw_cost_scenario(rng: np.random.Generator,
                       probabilities: tuple[float, ...] | None = None) -> str:
    """Pick the cost future a path will live in."""
    weights = probabilities or (1.0 / 3, 1.0 / 3, 1.0 / 3)
    return str(rng.choice(COST_SCENARIOS, p=weights))


def stage_costs(economic_axis: EconomicAxis, stage_year: int,
                rng: np.random.Generator | None = None,
                scenario: str | None = None,
                settings: ProjectSettings | None = None) -> dict[str, float]:
    """Unit prices at a stage, in real terms of the base year.

    ``scenario`` fixes the future; when it is omitted one is drawn, which is what the
    sampler does at the first stage before holding it for the rest of the path.
    """
    settings = default_settings() if settings is None else settings
    if scenario is None:
        scenario = draw_cost_scenario(rng or np.random.default_rng())
    trajectories = settings.cost_trajectories
    generator = max(settings.generators, key=lambda g: g.rating_kw)

    def at(name: str, base: float) -> float:
        return base * trajectories[name].factor(scenario, stage_year)

    return {
        "scenario": scenario,
        "fuel_price": at("diesel", settings.economics.diesel_price_usd_l),
        "capex_pv": at("pv", settings.photovoltaic.cost_usd_kw),
        "capex_batt": at("battery", settings.battery.cost_usd_kwh),
        "capex_ge": at("generator", generator.cost_usd_kw),
        "capex_inv": at("inverter", settings.inverter.cost_usd_kw),
        # Conversion on the array side is bought with the inverter under direct-current
        # coupling and separately under alternating; it learns with the converters either
        # way, so it follows the same trajectory rather than one of its own.
        "capex_conv_ac": at("inverter", settings.coupling.string_inverter_cost_usd_kw),
    }
