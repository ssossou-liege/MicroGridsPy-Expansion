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

#: The futures the shipped trajectories declare, shared by every technology so that a draw
#: is coherent. It is the fallback for a space built by hand; what a project declares is
#: read from the trajectories themselves by :func:`cost_scenarios`.
COST_SCENARIOS = ("low", "central", "high")


def cost_scenarios(settings: ProjectSettings | None = None) -> tuple[str, ...]:
    """The price futures a project declares, in the order its weights are given in.

    These three names were hard-coded, and ``CostTrajectory.scenarios`` -- the method that
    reports what a project declares -- was called by nobody. So the sampler drew a name the
    project had never heard of and handed it to ``factor``, which refuses it: the only
    projects that worked were those whose futures happened to be called low, central and
    high.

    Every technology must declare the same futures, and each of them a rate on both sides
    of the break year. A path picks one future and holds it across all the technologies, so
    a future one of them has no rate for is not a future.
    """
    settings = default_settings() if settings is None else settings
    trajectories = getattr(settings, "cost_trajectories", None) or {}
    if not trajectories:
        return COST_SCENARIOS
    declared = {name: trajectory.scenarios() for name, trajectory in trajectories.items()}
    first = next(iter(declared.values()))
    uneven = {name: names for name, names in declared.items() if names != first}
    if uneven:
        raise ValueError(
            "the cost trajectories declare different futures, and a path holds one future "
            f"across all of them: {list(first)} against "
            + "; ".join(f"{name} {list(names)}" for name, names in uneven.items()))
    half = {name: trajectory for name, trajectory in trajectories.items()
            if set(trajectory.late) != set(trajectory.early)}
    if half:
        raise ValueError(
            "these trajectories declare a future on one side of the break year only: "
            + ", ".join(sorted(half)))
    return first


def draw_cost_scenario(rng: np.random.Generator,
                       probabilities: tuple[float, ...] | None = None,
                       settings: ProjectSettings | None = None,
                       names: tuple[str, ...] = ()) -> str:
    """Pick the cost future a path will live in, among the ones declared.

    ``names`` is what the uncertainty space carries, so that the sampler does not need the
    settings object to know what it is drawing from; empty falls back to the project's.
    """
    scenarios = tuple(names) if names else cost_scenarios(settings)
    weights = probabilities or tuple(1.0 / len(scenarios) for _ in scenarios)
    return str(rng.choice(scenarios, p=weights))


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
        scenario = draw_cost_scenario(rng or np.random.default_rng(), settings=settings)
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
