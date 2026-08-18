"""The declared uncertainty space must stay a valid probability model.

The resource axis is a categorical draw over climate pathways, and the Monte-Carlo
sampler hands its weights straight to the random generator: weights that do not form a
distribution would fail there, far from where the mistake was made. These tests pin the
retained pathways and check that the weights are always normalised.
"""
from __future__ import annotations

import numpy as np
import pytest

from microgrid_expansion.scenarios.uncertainty_space import (
    SSP_PATHWAYS,
    PolicyAxis,
    ResourceAxis,
    UncertaintySpace,
)


def test_high_forcing_pathway_is_excluded():
    """SSP5-8.5 is deliberately not part of the resource axis."""
    assert "ssp585" not in SSP_PATHWAYS
    assert SSP_PATHWAYS == ("ssp126", "ssp245", "ssp370")


def test_default_weights_are_uniform_and_normalised():
    axis = ResourceAxis()
    assert len(axis.probabilities) == len(axis.pathways)
    assert sum(axis.probabilities) == pytest.approx(1.0)
    assert all(w == pytest.approx(1 / len(SSP_PATHWAYS)) for w in axis.probabilities)


def test_explicit_weights_are_normalised():
    """Unnormalised weights are accepted and rescaled rather than silently misused."""
    axis = ResourceAxis(pathways=("a", "b"), probabilities=(3.0, 1.0))
    assert sum(axis.probabilities) == pytest.approx(1.0)
    assert axis.probabilities[0] == pytest.approx(0.75)


@pytest.mark.parametrize(
    ("pathways", "probabilities"),
    [
        (("a", "b", "c"), (0.5, 0.5)),      # length mismatch
        (("a", "b"), (-0.5, 1.5)),          # negative weight
        (("a", "b"), (0.0, 0.0)),           # degenerate
        ((), None),                          # no pathway at all
    ],
)
def test_invalid_specifications_are_rejected(pathways, probabilities):
    with pytest.raises(ValueError):
        ResourceAxis(pathways=pathways, probabilities=probabilities)


def test_axis_weights_are_usable_by_the_sampler():
    """The weights must be directly acceptable to the random generator."""
    space = UncertaintySpace()
    rng = np.random.default_rng(0)
    for axis, values in (
        (space.resource, space.resource.pathways),
        (space.policy, space.policy.penetration_levels),
    ):
        draw = rng.choice(values, p=axis.probabilities)
        assert draw in values


def test_policy_axis_weights_form_a_distribution():
    axis = PolicyAxis()
    assert len(axis.probabilities) == len(axis.penetration_levels)
    assert sum(axis.probabilities) == pytest.approx(1.0)
