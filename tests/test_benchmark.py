"""Benchmark anchor.

On a degenerate single-scenario tree, compare the optimal sizing and LCOE against the
reference MILP benchmark (PV 8.2 kW, battery 17.2 kWh, generator 5.85 kW,
LCOE 0.3211 $/kWh). (Verification step 3 in the plan.)
"""
import pytest

BENCH = dict(pv_kw=8.2, batt_kwh=17.2, gen_kw=5.85, lcoe=0.3211)


@pytest.mark.skip(reason="Skeleton: implement once model + KPIs are filled in.")
def test_single_scenario_matches_thesis_benchmark():
    raise NotImplementedError
