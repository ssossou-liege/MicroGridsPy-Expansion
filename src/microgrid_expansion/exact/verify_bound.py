#!/usr/bin/env python3
"""Verification of the inequality the certificate rests on.

Proposition 1 asserts that at any design point the cost-optimal dispatch costs no more than
the rule-based controller, and that relaxing the commitment binary lowers it further. The
certificate is worthless if that ordering fails anywhere, so it is checked directly:

    relaxation  <=  mixed-integer optimum  <=  rule-based controller

at a sample of design points. A failure would mean either that the controller leaves the
feasible set — Assumption 1 — or that the linear fuel curve overestimates consumption
somewhere, and the report distinguishes the two.

Run:  python -m microgrid_expansion.exact.verify_bound --days 30
"""
from __future__ import annotations

import argparse
import math
import time

import numpy as np

from .. import config
from ..battery import usable_fraction
from ..instances import SiteYear, build_site_year
from .lower_bound import CapacityBox, Economics, cost_optimal_dispatch
from .simulator import BatteryModel, Capacities, GeneratorModel, simulate


def truncate(instance: SiteYear, hours: int) -> SiteYear:
    """The first ``hours`` of an instance, for a tractable mixed-integer solve."""
    from dataclasses import replace

    return replace(instance,
                   demand_kw=instance.demand_kw[:hours],
                   specific_yield=instance.specific_yield[:hours],
                   t_amb_c=instance.t_amb_c[:hours],
                   usable_fraction=instance.usable_fraction[:hours],
                   self_discharge=instance.self_discharge[:hours])


def sample_designs(instance: SiteYear, n: int = 6) -> list[Capacities]:
    """Design points spanning the plausible range for the instance.

    The converter is sized from the array as well as from the peak. Holding it at a fixed
    multiple of the peak while the array grows produces designs no installer could wire:
    past ``DC_AC_RATIO_MAX`` kilowatts of modules per kilowatt of conversion the coupling
    constraint is violated, the relaxation is infeasible, and the point contributes a NaN
    rather than a test of the ordering. Every sampled design is admissible by construction.

    The sweep also stops short of the capacities at which the generator never starts. Past
    roughly the daily consumption in storage, operating cost collapses to the residue of
    battery wear, the three quantities coincide, and the point stops saying anything about
    an ordering it satisfies only by equality.
    """
    peak = float(instance.demand_kw.max())
    daily = float(instance.demand_kw.sum()) / (instance.demand_kw.size / 24.0)
    yield_per_kw = float(instance.specific_yield.sum()) / (instance.demand_kw.size / 24.0)

    designs = []
    for factor in np.linspace(0.3, 1.0, n):
        pv = round(max(daily / max(yield_per_kw, 1e-6) * factor, 1.0), 1)
        # Rounded up, not to nearest: at the ceiling exactly, rounding the converter down
        # by a tenth of a kilowatt puts the array back outside what it can admit.
        inverter = math.ceil(max(peak * 1.2, pv / config.DC_AC_RATIO_MAX) * 10.0) / 10.0
        designs.append(Capacities(pv_kw=pv,
                                  battery_kwh=round(daily * factor, 1),
                                  inverter_kw=inverter,
                                  generator_kw=round(peak * 1.3, 1)))
    return designs


def verify(instance: SiteYear, designs: list[Capacities],
           economics: Economics = Economics(),
           with_milp: bool = True) -> list[dict]:
    """Evaluate the three quantities at each design point."""
    battery, generator = BatteryModel(), GeneratorModel()
    annualised = economics.annualised()
    rows = []
    for design in designs:
        capital = (annualised[0] * design.pv_kw + annualised[1] * design.battery_kwh
                   + annualised[2] * design.inverter_kw
                   + annualised[3] * design.generator_kw)

        started = time.time()
        dispatch = simulate(instance.demand_kw, instance.specific_yield,
                            instance.t_amb_c, design, battery, generator)
        feasible = dispatch.feasibility(battery, generator,
                                        usable_fraction(instance.t_amb_c))
        scale = 8760.0 / instance.demand_kw.size
        rule = dispatch.operating_cost() * scale + capital
        rule_time = time.time() - started

        box = CapacityBox.at(design)
        started = time.time()
        relaxed = cost_optimal_dispatch(instance, box, economics, battery, generator,
                                        relax_commitment=True, terminal="free",
                                        initial_soc_fraction=0.5)
        lp_value = (relaxed.value - relaxed.capital_cost) * scale + capital
        lp_time = time.time() - started

        milp_value, milp_time = float("nan"), float("nan")
        if with_milp:
            started = time.time()
            tight = cost_optimal_dispatch(instance, box, economics, battery, generator,
                                          relax_commitment=False, terminal="free",
                                          initial_soc_fraction=0.5)
            milp_value = (tight.value - tight.capital_cost) * scale + capital
            milp_time = time.time() - started

        rows.append({
            "design": design, "capital": capital,
            "relaxation": lp_value, "mixed_integer": milp_value, "rule": rule,
            "feasible": all(feasible.values()), "checks": feasible,
            "times": (lp_time, milp_time, rule_time),
        })
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", default="Samionta")
    parser.add_argument("--year", type=int, default=2025)
    parser.add_argument("--days", type=int, default=30,
                        help="horizon in days; the mixed-integer solve grows with it")
    parser.add_argument("--designs", type=int, default=6)
    parser.add_argument("--no-milp", action="store_true")
    args = parser.parse_args(argv)

    instance = build_site_year(args.site, args.year, maturity_months=12)
    window = truncate(instance, 24 * args.days)
    designs = sample_designs(window, args.designs)

    print(f"{args.site} {args.year} -- {args.days} days, {len(designs)} designs")
    print(f"{'PV':>7s}{'batt':>8s}{'group':>7s}"
          f"{'relaxation':>13s}{'mixed':>12s}{'rule':>12s}"
          f"{'order':>8s}{'feasible':>10s}")
    rows = verify(window, designs, with_milp=not args.no_milp)
    ordered = True
    # Relative tolerance: the quantities are annualised costs of several thousand dollars,
    # against which an absolute tolerance of a millionth is solver noise, not a violation.
    def below(a: float, b: float, rtol: float = 1e-7) -> bool:
        return a <= b + rtol * max(abs(a), abs(b), 1.0)

    for row in rows:
        d = row["design"]
        milp = row["mixed_integer"]
        chain = (below(row["relaxation"], milp) and below(milp, row["rule"])
                 if milp == milp else below(row["relaxation"], row["rule"]))
        ordered &= bool(chain) and row["feasible"]
        print(f"{d.pv_kw:7.1f}{d.battery_kwh:8.1f}{d.generator_kw:7.1f}"
              f"{row['relaxation']:13,.0f}{milp:12,.0f}{row['rule']:12,.0f}"
              f"{'ok' if chain else 'FAIL':>8s}{'ok' if row['feasible'] else 'FAIL':>10s}")
        if not row["feasible"]:
            print("      ", {k: v for k, v in row["checks"].items() if not v})

    print(f"\nProposition 1 holds at every point: {ordered}")
    gaps = [100 * (r["rule"] - r["mixed_integer"]) / r["mixed_integer"]
            for r in rows if r["mixed_integer"] == r["mixed_integer"]]
    if gaps:
        print(f"rule / optimum gap: {min(gaps):.1f} to {max(gaps):.1f} %")
    return 0 if ordered else 1


if __name__ == "__main__":
    raise SystemExit(main())
