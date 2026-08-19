"""Life-cycle cost accounting: net present cost and levelised cost of electricity.

The certificate compares designs, so what it compares them on must be the quantity a
planner actually decides by. That is the net present cost over the project horizon —
capital, maintenance, fuel, the replacements each asset needs before the horizon ends, and
the residual value of what is still serviceable at the end — and the levelised cost that
follows from it.

Assets are replaced whenever their life expires within the horizon, and the last vintage of
each is credited at the end in proportion to the life it has left. Ignoring either would
bias the comparison towards short-lived equipment: a battery lasting sixteen years against a
twenty-five-year horizon needs one replacement and leaves seven years of value on the table.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .. import config


def capital_recovery_factor(rate: float, years: int) -> float:
    """Factor turning a present cost into an equivalent annual payment."""
    if rate <= 0:
        return 1.0 / years
    return rate * (1 + rate) ** years / ((1 + rate) ** years - 1)


@dataclass(frozen=True)
class Asset:
    """One technology: what it costs, how long it lasts, what it costs to keep."""

    name: str
    unit_cost: float                 # per kW or per kWh
    lifetime_years: int
    om_rate: float                   # annual maintenance, as a fraction of capital

    def replacement_years(self, horizon: int) -> list[int]:
        """Years at which the asset must be replaced before the horizon ends."""
        return [y for y in range(self.lifetime_years, horizon, self.lifetime_years)]

    def present_cost(self, capacity: float, horizon: int, rate: float) -> dict:
        """Discounted capital, replacement, maintenance and salvage of one asset."""
        capital = self.unit_cost * capacity
        replacements = sum(capital / (1 + rate) ** year
                           for year in self.replacement_years(horizon))

        maintenance = sum(self.om_rate * capital / (1 + rate) ** year
                          for year in range(1, horizon + 1))

        # Residual value of the vintage still in service at the horizon, straight-line.
        installed = max([0, *self.replacement_years(horizon)])
        age = horizon - installed
        remaining = max(self.lifetime_years - age, 0) / self.lifetime_years
        salvage = capital * remaining / (1 + rate) ** horizon

        return {"capital": capital, "replacement": replacements,
                "maintenance": maintenance, "salvage": salvage,
                "total": capital + replacements + maintenance - salvage}


def assets_from_settings(settings=None) -> dict[str, Asset]:
    """The four technologies, described by the project's own equipment settings.

    Cost, lifetime and maintenance come from the same place: a lifetime drives replacement
    and salvage, so declaring it apart from the price it applies to invites the two to
    describe different equipment.
    """
    from ..settings import default_settings

    settings = default_settings() if settings is None else settings
    generator = max(settings.generators, key=lambda g: g.rating_kw)
    return {
        "pv": Asset("pv", settings.photovoltaic.cost_usd_kw,
                    settings.photovoltaic.lifetime_years, settings.photovoltaic.om_rate),
        "battery": Asset("battery", settings.battery.cost_usd_kwh,
                         settings.battery.lifetime_years, settings.battery.om_rate),
        "inverter": Asset("inverter", settings.inverter.cost_usd_kw,
                          settings.inverter.lifetime_years, settings.inverter.om_rate),
        "generator": Asset("generator", generator.cost_usd_kw,
                           generator.lifetime_years, generator.om_rate),
    }


def default_assets() -> dict[str, Asset]:
    """The technologies as configured for this project."""
    return assets_from_settings()


@dataclass
class LifeCycleCost:
    """Net present cost of one design and the levelised cost that follows."""

    net_present_cost: float
    annualised_cost: float
    lcoe_usd_kwh: float
    energy_served_kwh: float
    breakdown: dict = field(default_factory=dict)

    def __str__(self) -> str:
        return (f"NPC {self.net_present_cost:,.0f} $ | "
                f"annualisé {self.annualised_cost:,.0f} $/an | "
                f"LCOE {self.lcoe_usd_kwh:.4f} $/kWh")


def life_cycle_cost(
    capacities: dict[str, float],
    annual_operating_cost: float,
    energy_served_kwh: float,
    horizon_years: int = config.PROJECT_YEARS,
    discount_rate: float = config.DISCOUNT_RATE,
    assets: dict[str, Asset] | None = None,
) -> LifeCycleCost:
    """Net present cost and levelised cost of one design.

    ``annual_operating_cost`` is the recurring cost the dispatch produces — fuel, storage
    degradation and unserved energy — held constant over the horizon, the demand being
    represented by one operating year.
    """
    assets = default_assets() if assets is None else assets
    breakdown: dict[str, dict] = {}
    present = 0.0
    for name, capacity in capacities.items():
        if name not in assets:
            raise KeyError(f"no asset description for {name!r}")
        entry = assets[name].present_cost(capacity, horizon_years, discount_rate)
        breakdown[name] = entry
        present += entry["total"]

    annuity = sum(1.0 / (1 + discount_rate) ** year
                  for year in range(1, horizon_years + 1))
    operating_present = annual_operating_cost * annuity
    breakdown["operating"] = {"total": operating_present}
    present += operating_present

    crf = capital_recovery_factor(discount_rate, horizon_years)
    annualised = present * crf
    lcoe = annualised / energy_served_kwh if energy_served_kwh > 0 else math.inf
    return LifeCycleCost(net_present_cost=present, annualised_cost=annualised,
                         lcoe_usd_kwh=lcoe, energy_served_kwh=energy_served_kwh,
                         breakdown=breakdown)
