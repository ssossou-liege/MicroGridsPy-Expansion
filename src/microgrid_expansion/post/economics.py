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


def assets_from_settings(settings=None, architecture: str | None = None) -> dict[str, Asset]:
    """The technologies, described by the project's own equipment settings.

    Cost, lifetime and maintenance come from the same place: a lifetime drives replacement
    and salvage, so declaring it apart from the price it applies to invites the two to
    describe different equipment.
    """
    from ..settings import default_settings

    settings = default_settings() if settings is None else settings
    generator = max(settings.generators, key=lambda g: g.rating_kw)
    # The array's own conversion — controllers or string inverters — is sized to the array
    # and so is priced per kilowatt of it, alongside the modules rather than apart from
    # them. Which equipment, and therefore which price, follows from the architecture.
    coupling = settings.coupling
    architecture = (coupling.architecture if architecture is None else architecture)
    if architecture == "auto":
        architecture = "dc"
    conversion = Asset("conversion",
                       coupling.cost_usd_kw(architecture),
                       coupling.lifetime_years, coupling.om_rate)
    return {
        "conversion": conversion,
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
    """Net present cost of one design, and what tariff it implies.

    Two readings of the same figures. If the project must recover its full cost, the
    tariff *is* the levelised cost and there is nothing further to compute. If instead a
    tariff has been set as a policy target — as it usually is, an operator being unable to
    charge a rural community whatever the plant happens to cost — then the gap between the
    two has to be met by a capital grant, and its size is a result of the sizing rather
    than an input to it.
    """

    net_present_cost: float
    annualised_cost: float
    lcoe_usd_kwh: float
    energy_served_kwh: float
    breakdown: dict = field(default_factory=dict)
    tariff_target_usd_kwh: float | None = None
    subsidy_fraction: float = 0.0
    subsidy_usd: float = 0.0

    @property
    def cost_reflective_tariff_usd_kwh(self) -> float:
        """The tariff that recovers the full cost: the levelised cost itself."""
        return self.lcoe_usd_kwh

    @property
    def tariff_usd_kwh(self) -> float:
        """The tariff actually charged: the target if one is set, else full recovery."""
        return (self.lcoe_usd_kwh if self.tariff_target_usd_kwh is None
                else self.tariff_target_usd_kwh)

    def __str__(self) -> str:
        base = (f"NPC {self.net_present_cost:,.0f} $ | "
                f"annualisé {self.annualised_cost:,.0f} $/an | "
                f"LCOE {self.lcoe_usd_kwh:.4f} $/kWh")
        if self.tariff_target_usd_kwh is None:
            return base + " (tarif = LCOE, recouvrement intégral)"
        return (base + f" | tarif cible {self.tariff_target_usd_kwh:.4f} $/kWh"
                f" -> subvention {self.subsidy_fraction:.1%} "
                f"({self.subsidy_usd:,.0f} $)")


def life_cycle_cost(
    capacities: dict[str, float],
    annual_operating_cost: float,
    energy_served_kwh: float,
    horizon_years: int = config.PROJECT_YEARS,
    discount_rate: float = config.DISCOUNT_RATE,
    assets: dict[str, Asset] | None = None,
    tariff_target_usd_kwh: float | None = None,
) -> LifeCycleCost:
    """Net present cost and levelised cost of one design.

    ``annual_operating_cost`` is the recurring cost the dispatch produces — fuel, storage
    degradation and unserved energy — held constant over the horizon, the demand being
    represented by one operating year.

    When ``tariff_target_usd_kwh`` is given, the capital subsidy required to bring the
    levelised cost down to it is computed. A grant covering a share *s* of the net present
    cost lowers the levelised cost in the same proportion, so reaching a target *t* from a
    levelised cost *l* requires ``s = 1 - t / l``. A target already at or above the
    levelised cost needs no subsidy.
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

    fraction = 0.0
    if tariff_target_usd_kwh is not None and math.isfinite(lcoe) and lcoe > 0:
        fraction = max(0.0, 1.0 - tariff_target_usd_kwh / lcoe)
    return LifeCycleCost(net_present_cost=present, annualised_cost=annualised,
                         lcoe_usd_kwh=lcoe, energy_served_kwh=energy_served_kwh,
                         breakdown=breakdown,
                         tariff_target_usd_kwh=tariff_target_usd_kwh,
                         subsidy_fraction=fraction, subsidy_usd=fraction * present)
