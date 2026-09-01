"""What a lender asks after the engineer has answered.

The sizing settles what the plant costs. A financing decision turns on a different question:
when the money comes back, and at what rate. Both are read off the same cash flows, so they
belong beside the levelised cost rather than in a spreadsheet somebody rebuilds by hand.

Everything here is nominal-free and pre-tax, which is what a first screening needs: a project
that does not clear the hurdle before tax and before leverage will not clear it after.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .. import config
from .economics import Asset, assets_from_settings


@dataclass
class CashFlow:
    """One year of the project's money."""

    year: int
    capital: float = 0.0            # negative outflow, positive nothing
    operating: float = 0.0
    revenue: float = 0.0
    #: Residual value of what is still serviceable at the horizon. On its own line because
    #: it is not revenue: nobody pays it, and a lender strips it before reading the return.
    #: Carried in ``net`` all the same, a plant being worth something when the study ends.
    salvage: float = 0.0

    @property
    def net(self) -> float:
        return self.revenue + self.salvage - self.operating - self.capital

    @property
    def net_without_salvage(self) -> float:
        return self.revenue - self.operating - self.capital


@dataclass
class Financials:
    """The figures a credit committee reads."""

    years: list[CashFlow] = field(default_factory=list)
    initial_capital: float = 0.0
    annual_revenue: float = 0.0
    annual_operating: float = 0.0
    salvage: float = 0.0
    demand_growth_rate: float = 0.0
    collection_rate: float = 1.0
    irr: float | None = None
    #: The same return with the residual value struck out, which is how a lender reads it.
    irr_without_salvage: float | None = None
    payback_years: float | None = None
    discounted_payback_years: float | None = None
    net_present_value: float = 0.0
    subsidy_usd: float = 0.0

    def to_dict(self) -> dict:
        return {
            "initial_capital_usd": self.initial_capital,
            "annual_revenue_usd": self.annual_revenue,
            "annual_operating_usd": self.annual_operating,
            "irr": self.irr, "irr_without_salvage": self.irr_without_salvage,
            "collection_rate": self.collection_rate,
            "payback_years": self.payback_years,
            "discounted_payback_years": self.discounted_payback_years,
            "net_present_value_usd": self.net_present_value,
            "subsidy_usd": self.subsidy_usd,
            "salvage_usd": self.salvage,
            "demand_growth_rate": self.demand_growth_rate,
            "cash_flows": [{"year": c.year, "capital": c.capital,
                            "operating": c.operating, "revenue": c.revenue,
                            "salvage": c.salvage, "net": c.net} for c in self.years],
        }


def _irr(flows: list[float], lo: float = -0.95, hi: float = 4.0) -> float | None:
    """The rate at which the flows are worth nothing today, by bisection.

    Bisection rather than a root-finder: the sign pattern here is one outflow followed by
    inflows, so the present value is monotone in the rate and a bracket is all that is
    needed. A project that never turns positive has no rate, and is reported as having none
    rather than as having a very bad one.
    """
    def npv(rate: float) -> float:
        return sum(f / (1.0 + rate) ** k for k, f in enumerate(flows))

    if npv(lo) * npv(hi) > 0:
        return None
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if npv(lo) * npv(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)


def _crossing(cumulative: list[float]) -> float | None:
    """The year the cumulative flow first turns positive, interpolated within it."""
    for k in range(1, len(cumulative)):
        if cumulative[k - 1] < 0 <= cumulative[k]:
            step = cumulative[k] - cumulative[k - 1]
            return (k - 1) + (-cumulative[k - 1] / step if step else 0.0)
    return None


def appraise(
    capacities: dict[str, float],
    annual_operating_cost: float,
    energy_served_kwh: float,
    tariff_usd_kwh: float,
    horizon_years: int = config.PROJECT_YEARS,
    discount_rate: float = config.DISCOUNT_RATE,
    assets: dict[str, Asset] | None = None,
    subsidy_usd: float = 0.0,
    demand_growth_rate: float = 0.0,
    collection_rate: float = 1.0,
) -> Financials:
    """Build the project's cash flows and read the usual measures off them.

    ``subsidy_usd`` is a capital grant received at year zero, which is how these projects are
    actually financed: the tariff a rural community can pay rarely recovers the plant, and the
    question a lender then asks is whether what remains is bankable. Without it the return is
    the return of an unsubsidised project, which is worth seeing too.
    """
    assets = assets_from_settings() if assets is None else assets

    capital_by_asset = {name: assets[name].unit_cost * capacity
                        for name, capacity in capacities.items() if name in assets}
    initial = sum(capital_by_asset.values())
    maintenance = sum(assets[name].om_rate * capital
                      for name, capital in capital_by_asset.items())
    # Billed and collected, not merely delivered. A rural mini-grid loses some energy to
    # non-technical losses and some of its billing to arrears, and an appraisal that assumes
    # every kilowatt-hour served is paid for is optimistic in exactly the place the tariff
    # discussion happens.
    collected = max(0.0, min(collection_rate, 1.0))
    revenue = tariff_usd_kwh * energy_served_kwh * collected

    # An asset replaced late still has life in it when the horizon ends, and the levelised
    # cost already credits that. Leaving it out here put two figures on one page computed on
    # different conventions -- a sixteen-year battery replaced once on a twenty-five-year
    # horizon leaves nine years of value the one counted and the other did not.
    salvage = 0.0
    for name, capital in capital_by_asset.items():
        life = assets[name].lifetime_years
        used = horizon_years % life
        if used:
            salvage += capital * (life - used) / life

    flows = [CashFlow(year=0, capital=initial - subsidy_usd)]
    for year in range(1, horizon_years + 1):
        replacement = sum(
            capital for name, capital in capital_by_asset.items()
            if year in assets[name].replacement_years(horizon_years)
        )
        # Revenue follows the demand the developer expects, not the demand of the sizing
        # year held for a quarter of a century. The rate is stated rather than derived: the
        # growth law is a mixture over behaviours by connection age, and turning it into an
        # energy multiplier would mean simulating every year of the horizon.
        grown = revenue * (1.0 + demand_growth_rate) ** (year - 1)
        flows.append(CashFlow(year=year, capital=replacement,
                              operating=annual_operating_cost + maintenance,
                              revenue=grown))
    flows[-1].salvage = salvage

    net = [c.net for c in flows]
    bare = [c.net_without_salvage for c in flows]
    cumulative, running = [], 0.0
    for value in net:
        running += value
        cumulative.append(running)
    discounted, running = [], 0.0
    for k, value in enumerate(net):
        running += value / (1.0 + discount_rate) ** k
        discounted.append(running)

    return Financials(
        years=flows, initial_capital=initial,
        annual_revenue=revenue, annual_operating=annual_operating_cost + maintenance,
        irr=_irr(net), irr_without_salvage=_irr(bare),
        payback_years=_crossing(cumulative),
        discounted_payback_years=_crossing(discounted),
        net_present_value=discounted[-1], subsidy_usd=subsidy_usd,
        salvage=salvage, demand_growth_rate=demand_growth_rate,
        collection_rate=collected,
    )
