"""Pricing a certified design, in one place.

The certificate settles which plant is cheapest. What that plant costs a customer is a
second question, and it was answered twice: once by the interface and once by the
command line, in two blocks of near-identical code. They drifted, as duplicated
arithmetic does. When the storage double-charge was corrected in one, the other went on
reporting a levelised cost that still carried it, and the certificates written to
``results/`` were wrong in a way no test could see because each path was internally
consistent.

So there is one function now, and both callers use it. That is the same rule the rest of
this project already follows: figures shown side by side are computed side by side.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .economics import (LifeCycleCost, assets_from_settings, infrastructure_assets,
                        life_cycle_cost)
from .finance import Financials, appraise


@dataclass(frozen=True)
class Appraisal:
    """Everything a developer is asked about one certified design."""

    cost: LifeCycleCost
    finance: Financials
    finance_unsubsidised: Financials
    #: Life that ends the storage pack, calendar or cycles, whichever comes first.
    battery_life_years: float
    #: Capital of the network, connections, civil works and development, at year zero.
    infrastructure_usd: float
    #: Energy the plant actually delivered over the year simulated.
    energy_served_kwh: float
    #: Recurring cost of running it: fuel, unserved energy, the grid's net bill.
    operating_usd_yr: float
    #: Array ratios the certified plant sits exactly on, if any.
    binding_ceilings: tuple[str, ...] = ()


def price_certified_design(instance, design, settings, dispatch, generator) -> Appraisal:
    """Life-cycle cost and financial appraisal of one design, on one dispatch.

    ``dispatch`` is passed in rather than simulated here so that the caller prices the run
    it already has -- and, more to the point, so that the grid link the search assumed is
    the grid link the pricing sees. Simulating again inside would invite the two to differ.

    ``generator`` carries the fuel price, so it has to be the project's own unit and not a
    default: costing a litre at the library's price rather than the study's is precisely
    the kind of quiet divergence this function exists to end.
    """
    from ..exact.certify import _grid_capital_usd_yr

    horizon = settings.economics.horizon_years
    rate = settings.economics.discount_rate

    # Storage wear is charged through the replacement interval, never per kilowatt-hour:
    # the two together bought the same pack twice.
    operating = dispatch.operating_cost(
        generator, voll_usd_kwh=settings.economics.value_of_lost_load_usd_kwh)
    battery_life = settings.battery.effective_lifetime_years(
        design.battery_kwh, float(dispatch.discharge_kw.sum()))
    served = instance.demand_kwh - float(dispatch.unserved_kw.sum())
    target = (settings.economics.tariff_usd_kwh
              if settings.economics.tariff_is_target else None)

    balance_assets = infrastructure_assets(settings, horizon)
    assets = assets_from_settings(settings, architecture="ac",
                                  battery_lifetime_years=battery_life)
    assets.update(balance_assets)

    plant = {"pv": design.pv_total_kw, "battery": design.battery_kwh,
             "inverter": design.inverter_kw, "generator": design.generator_kw,
             "conversion": getattr(design, "pv_ac_kw", 0.0)}
    balance = {name: 1.0 for name in balance_assets}
    capacities: dict[str, float] = {**plant, **balance}

    cost = life_cycle_cost(
        capacities, operating + _grid_capital_usd_yr(settings), served,
        horizon_years=horizon, discount_rate=rate, tariff_target_usd_kwh=target,
        assets=assets, collection_rate=settings.economics.collection_rate)

    common: dict[str, Any] = dict(
        tariff_usd_kwh=settings.economics.tariff_usd_kwh, horizon_years=horizon,
        discount_rate=rate, assets=assets,
        demand_growth_rate=settings.economics.demand_growth_rate,
        collection_rate=settings.economics.collection_rate)
    finance = appraise(capacities, operating, served,
                       subsidy_usd=cost.subsidy_usd or 0.0, **common)
    bare = appraise(capacities, operating, served, subsidy_usd=0.0, **common)

    # A constraint the optimum sits exactly on is a number deciding the answer. Both array
    # ratios are single sourced figures, and when the certified plant saturates one the
    # result is as sensitive to that figure as to anything the developer entered.
    coupling = settings.coupling
    ceilings = {
        "dc_ratio": (design.pv_kw, design.inverter_kw * coupling.dc_ac_ratio_max),
        "ac_ratio": (getattr(design, "pv_ac_kw", 0.0),
                     design.inverter_kw * coupling.ac_ratio_max),
    }
    binding = tuple(sorted(name for name, (value, limit) in ceilings.items()
                           if limit > 0 and value >= limit - 1e-6))

    return Appraisal(cost=cost, finance=finance, finance_unsubsidised=bare,
                     battery_life_years=battery_life,
                     infrastructure_usd=sum(a.unit_cost for a in balance_assets.values()),
                     energy_served_kwh=served, operating_usd_yr=operating,
                     binding_ceilings=binding)
