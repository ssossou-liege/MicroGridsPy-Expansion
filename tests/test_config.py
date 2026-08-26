"""Config sanity checks that run without the (stubbed) heavy dependencies."""
import pytest

from microgrid_expansion.config import (
    ModelConfig,
    crf,
    battery_degradation_cost,
)


def test_crf_positive_and_bounded():
    r = crf(0.12, 25)
    assert 0 < r < 1


def test_battery_degradation_cost_reasonable():
    # Replacement / lifetime throughput should land near 0.05-0.10 $/kWh.
    c = battery_degradation_cost()
    assert 0.0 < c < 0.5


def test_config_validate_accepts_consistent_shape():
    cfg = ModelConfig(stage_years=(0, 5, 10), branching=(1, 3, 2))
    cfg.validate()


def test_config_validate_rejects_mismatched_branching():
    cfg = ModelConfig(stage_years=(0, 5, 10), branching=(1, 3))
    with pytest.raises(ValueError):
        cfg.validate()


def test_the_first_stage_holds_one_node():
    """Branching starts after the here-and-now decision, never at it.

    The first stage is the plant that gets built; a tree that branches there would be
    asking which of several plants was built, which is not a decision anybody makes.
    """
    with pytest.raises(ValueError, match="here-and-now"):
        ModelConfig(stage_years=(0, 5), branching=(2, 2)).validate()
    ModelConfig(stage_years=(0, 5), branching=(1, 2)).validate()


def test_a_node_needs_at_least_one_day():
    with pytest.raises(ValueError, match="representative day"):
        ModelConfig(n_rep_days=0).validate()
