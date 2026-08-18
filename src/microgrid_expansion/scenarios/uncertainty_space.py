"""Declarative specification of the four uncertainty families and their marginals.

The four families (formulation, Section "Uncertainty space"):

* **demand**    -- RAMP trajectories: connections per customer type, appliance
  stock (name, count, rated power) and usage patterns (functioning time, time per
  event, time-of-use windows, occasional-use probability).
* **resource**  -- climate pathway in {ssp126, ssp245, ssp370}.
* **economic**  -- diesel-price and per-technology investment-cost trajectories.
* **policy**    -- minimum solar-penetration target.

Each entry describes how a value is drawn at a given stage; the concrete
distributions are calibrated from surveys and meter readings.
"""
from __future__ import annotations

from dataclasses import dataclass, field

#: Climate pathways retained for the resource axis. The high-forcing pathway SSP5-8.5 is
#: deliberately excluded: its emission trajectory is now widely regarded as implausible
#: rather than as a business-as-usual baseline, so including it would widen the resource
#: spread without informing the sizing decision.
SSP_PATHWAYS = ("ssp126", "ssp245", "ssp370")


@dataclass
class DemandAxis:
    """Demand uncertainty: parameters handed to the RAMP generator per stage."""

    customer_types: tuple[str, ...] = ("residential", "commercial", "productive")
    # Distribution handles (filled by calibration); placeholders for the skeleton.
    connections_dist: dict = field(default_factory=dict)
    appliance_stock_dist: dict = field(default_factory=dict)
    usage_pattern_dist: dict = field(default_factory=dict)


@dataclass
class ResourceAxis:
    """Renewable-resource uncertainty: a categorical draw over SSP pathways.

    ``probabilities`` defaults to a uniform draw over :data:`SSP_PATHWAYS`; supplying a
    non-uniform prior over the pathways is a matter of assigning it explicitly. The
    weights are normalised on construction so that they always form a distribution.
    """

    pathways: tuple[str, ...] = SSP_PATHWAYS
    probabilities: tuple[float, ...] | None = None

    def __post_init__(self) -> None:
        n = len(self.pathways)
        if n == 0:
            raise ValueError("ResourceAxis requires at least one pathway")
        if self.probabilities is None:
            self.probabilities = tuple([1.0 / n] * n)
            return
        if len(self.probabilities) != n:
            raise ValueError(
                f"probabilities has {len(self.probabilities)} entries for {n} pathways"
            )
        if any(w < 0 for w in self.probabilities):
            raise ValueError("pathway probabilities must be non-negative")
        total = sum(self.probabilities)
        if total <= 0:
            raise ValueError("pathway probabilities must sum to a positive value")
        self.probabilities = tuple(w / total for w in self.probabilities)


@dataclass
class EconomicAxis:
    """Economic uncertainty: fuel-price and cost-trajectory drivers."""

    fuel_price_growth_dist: dict = field(default_factory=dict)
    capex_learning_dist: dict = field(default_factory=dict)  # per technology


@dataclass
class PolicyAxis:
    """Policy uncertainty: minimum renewable-penetration target."""

    penetration_levels: tuple[float, ...] = (0.0, 0.5, 0.7)
    probabilities: tuple[float, ...] = (0.34, 0.33, 0.33)


@dataclass
class UncertaintySpace:
    """Container bundling the four families."""

    demand: DemandAxis = field(default_factory=DemandAxis)
    resource: ResourceAxis = field(default_factory=ResourceAxis)
    economic: EconomicAxis = field(default_factory=EconomicAxis)
    policy: PolicyAxis = field(default_factory=PolicyAxis)
