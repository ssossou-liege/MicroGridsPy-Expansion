"""The growth trajectory a path follows is drawn, and the draw is now stated.

Every tree this project has drawn weighted the three growth trajectories equally. That was
defensible and it was invisible: the thirds lived in a default argument of the sampler, no
setting carried them, no report mentioned them, and no reader could have disagreed with a
number they were never shown. A decision taken under uncertainty is only as good as the
statement of what was held uncertain.

These tests hold three things. The weights reach the sampler from the project's settings,
so that changing them changes the futures the year-0 plant is sized against. The default
reproduces every tree drawn before, bit for bit, so that stating the assumption did not
quietly alter it. And weights that are not a distribution are refused rather than rescaled,
because a reader who has changed one of three numbers and not the others has made a mistake
worth reporting, not an intention worth guessing.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import replace

import pytest

from microgrid_expansion.config import ModelConfig
from microgrid_expansion.scenarios import sample_scenario_paths
from microgrid_expansion.scenarios.demand_paths import TRAJECTORIES
from microgrid_expansion.scenarios.uncertainty_space import DemandAxis, space_from_settings
from microgrid_expansion.settings import default_settings

SMALL = dict(stage_years=(0, 5), branching=(1, 2), n_mc_paths=60, n_rep_days=2)


def _settings(slow: float, central: float, fast: float):
    settings = default_settings()
    settings.trajectory_weights.slow = slow
    settings.trajectory_weights.central = central
    settings.trajectory_weights.fast = fast
    return settings


def _drawn(settings, seed: int = 0) -> Counter:
    """What each path's growth trajectory came out as."""
    cfg = ModelConfig(seed=seed, **SMALL)
    paths = sample_scenario_paths(cfg, space_from_settings(settings))
    return Counter(path.draws[0].trajectory for path in paths)


def test_the_weights_reach_the_sampler() -> None:
    """A weight of one leaves no room for the other two."""
    assert set(_drawn(_settings(1.0, 0.0, 0.0))) == {"slow"}
    assert set(_drawn(_settings(0.0, 1.0, 0.0))) == {"central"}
    assert set(_drawn(_settings(0.0, 0.0, 1.0))) == {"fast"}


def test_a_lopsided_weight_tilts_the_draw_without_emptying_it() -> None:
    """Between the corners the weights have to behave like probabilities."""
    counts = _drawn(_settings(0.5, 0.25, 0.25))
    assert set(counts) == set(TRAJECTORIES), "a weight of a quarter is not a weight of zero"
    assert counts["slow"] > counts["central"] + counts["fast"] - counts["slow"], (
        "half the mass on slow did not show in the draw")


def test_the_default_draws_exactly_what_the_untold_thirds_drew() -> None:
    """Stating an assumption must not change it.

    Every archived tree was drawn with the sampler's own default, an equal third each. If
    carrying the same numbers through the settings moved a single path, every result
    computed before would have to be recomputed to be comparable, and the reason would be
    bookkeeping rather than anything about the villages.
    """
    space = space_from_settings(default_settings())
    stated = [p.draws[0].trajectory
              for p in sample_scenario_paths(ModelConfig(seed=0, **SMALL), space)]
    # The same space with the demand axis as it was: carrying no probabilities at all,
    # which is what every caller handed the sampler before the weights existed. Only that
    # axis is changed, because the grid axis consumes randomness of its own and swapping
    # the whole space would compare two different draws rather than two weightings.
    untold = [p.draws[0].trajectory
              for p in sample_scenario_paths(ModelConfig(seed=0, **SMALL),
                                             replace(space, demand=DemandAxis()))]
    assert stated == untold, "the stated thirds draw a different tree from the untold ones"


def test_weights_that_are_not_a_distribution_are_refused() -> None:
    """Rescaled silently, they would answer a question the reader did not ask."""
    for bad in ((0.5, 0.3, 0.3), (0.2, 0.2, 0.2), (-0.1, 0.6, 0.5), (0.0, 0.0, 0.0)):
        with pytest.raises(ValueError, match="trajectory weights"):
            _settings(*bad).validate()
    # And the one that is a distribution is not refused, or the test above proves nothing.
    _settings(0.5, 0.25, 0.25).validate()


def test_the_weights_survive_a_round_trip_through_a_saved_project(tmp_path) -> None:
    """A project reopened must be sized against the futures it was sized against."""
    from microgrid_expansion.settings import ProjectSettings

    written = _settings(0.5, 0.25, 0.25)
    path = written.save(tmp_path / "project.yaml")
    read = ProjectSettings.load(path)
    assert read.trajectory_weights.as_probabilities() == (0.5, 0.25, 0.25)


def test_the_prices_reach_the_sampler_too() -> None:
    """A project that prices its own equipment must be costed at its own prices.

    The weights above reached the sampler through the uncertainty space. The prices did
    not: they were read from the defaults whatever settings the caller had built, so a
    tree asked about one price list came back costed against another. Nothing looked
    wrong, because every figure in the answer was a consistent answer to the wrong
    question.
    """
    from dataclasses import replace as _replace

    settings = default_settings()
    dearer = default_settings()
    dearer.photovoltaic = _replace(dearer.photovoltaic,
                                   cost_usd_kw=3.0 * settings.photovoltaic.cost_usd_kw)
    dearer.battery = _replace(dearer.battery,
                              cost_usd_kwh=3.0 * settings.battery.cost_usd_kwh)

    cfg = ModelConfig(seed=0, **SMALL)
    base = sample_scenario_paths(cfg, space_from_settings(settings), settings)
    moved = sample_scenario_paths(cfg, space_from_settings(dearer), dearer)

    for key, factor in (("capex_pv", 3.0), ("capex_batt", 3.0)):
        before = base[0].draws[0].costs[key]
        after = moved[0].draws[0].costs[key]
        assert after == pytest.approx(factor * before), key
    # The cost trajectory still applies on top, so a later stage is not the base price.
    assert moved[0].draws[-1].costs["capex_pv"] != pytest.approx(
        moved[0].draws[0].costs["capex_pv"])
    # And what the caller did not change is unchanged.
    assert moved[0].draws[0].costs["fuel_price"] == pytest.approx(
        base[0].draws[0].costs["fuel_price"])
