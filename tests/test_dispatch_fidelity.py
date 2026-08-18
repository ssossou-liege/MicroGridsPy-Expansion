"""Rule-fidelity check (core validation).

Feed MILP-optimal capacities into the actual uGrid ``GenControl()`` sequential
simulator on the full 8760 series and confirm the ``rule_faithful`` encoding
reproduces the heuristic PV/battery/generator split, and that representative-day
costs match full-year costs within tolerance (~5%). (Verification step 2 in the plan.)
"""
import pytest


@pytest.mark.skip(reason="Skeleton: requires the ported uGrid GenControl + filled model.")
def test_milp_matches_gencontrol_simulator():
    raise NotImplementedError
