"""Productive uses: the tables, the connection trajectory and what they change."""
from __future__ import annotations

import numpy as np
import pytest

from microgrid_expansion.demand import productive as P


@pytest.fixture(scope="module")
def calibration():
    return P.ProductiveCalibration.load()


def test_the_activity_taxonomy_separates_what_the_meters_separate():
    """Class names must map the declared activities, accents and case notwithstanding.

    The strings tested against are the survey's own, transcribed as the enumerators wrote
    them. They are data, not untranslated text: changing them would test a survey nobody
    ran.
    """
    assert P.classify("MOULIN À MAÏS") == "milling"
    assert P.classify("Ventes de glace, eau glacée") == "refrigeration"
    assert P.classify("Couvaison des oeufs") == "incubation"
    assert P.classify("TAILLEUR") == "tailoring"
    assert P.classify("Scierie") == "sawmill"
    assert P.classify("commerçant") == P.UNSURVEYED     # the survey did not reach these


def test_classes_differ_in_shape_and_not_merely_in_size(calibration):
    """A single average enterprise would erase the daytime load that decides the coupling.

    Milling runs in daylight, incubation runs around the clock, and the many small trading
    activities keep a household's evening profile. If the classes were mere rescalings of
    one another there would be nothing to gain by distinguishing them.
    """
    hours = [h for h in range(24) if h in calibration.profiles.columns]
    shapes = calibration.profiles[hours]
    daytime = shapes[[h for h in hours if 7 <= h <= 18]].sum(axis=1) / shapes.sum(axis=1)

    assert daytime["milling"] > 0.75                    # a mill runs in daylight
    assert daytime["incubation"] < 0.50                  # incubators run through the night
    # and the classes span a real range rather than sitting on one another
    assert daytime.max() - daytime.min() > 0.25


def test_enterprises_are_counted_against_connections_not_against_the_census(calibration):
    """Intensity is per connected household: enterprises appear beside existing supply."""
    rng = np.random.default_rng(0)
    few = [sum(P.sample_units(calibration, 20, "25+", "central", rng).values())
           for _ in range(60)]
    many = [sum(P.sample_units(calibration, 200, "25+", "central", rng).values())
            for _ in range(60)]
    assert np.mean(many) > 5 * np.mean(few)


def test_the_connection_trajectory_is_ordered_and_grows(calibration):
    """The envelope must bracket, and maturity must not reduce the count."""
    intensity = calibration.intensity
    assert (intensity["slow"] <= intensity["central"] + 1e-9).all()
    assert (intensity["central"] <= intensity["fast"] + 1e-9).all()
    # beyond the first months, in which one household and one shop can be the whole village
    settled = intensity.loc[["4-6", "7-12", "13-24", "25+"]]
    assert settled["fast"].is_monotonic_increasing


def test_the_mix_belongs_to_the_trajectory(calibration):
    """The reference villages hold different populations, not merely different numbers.

    One has few large enterprises — mills, a sawmill, ice makers — the other many small
    ones. Drawing both from a pooled mix reproduces neither.
    """
    mix = calibration.mix
    for column in ("slow", "central", "fast"):
        assert abs(mix[column].sum() - 1.0) < 1e-9      # exact: a draw depends on it
    assert mix.loc[P.UNSURVEYED, "fast"] > mix.loc[P.UNSURVEYED, "slow"]


def test_repeating_a_mean_day_would_flatten_the_peak(calibration):
    """Day-to-day spread is carried, so the month is not twenty-eight identical days."""
    rng = np.random.default_rng(1)
    counts = {"milling": 4, P.UNSURVEYED: 10}
    profile = P.monthly_profile_kw(counts, calibration, days=28, rng=rng)

    assert profile.size == 28 * 24
    daily = profile.reshape(28, 24).sum(axis=1)
    assert daily.std() > 0.0
    # and the drawn days average to the measured day rather than drifting from it
    hours = [h for h in range(24) if h in calibration.profiles.columns]
    expected = sum(n * calibration.profiles.loc[k, hours].sum() for k, n in counts.items())
    assert daily.mean() == pytest.approx(expected, rel=0.25)


def test_productive_uses_change_the_shape_of_the_community_load():
    """The point of the exercise: they move the load into the day."""
    from microgrid_expansion.demand.generator import simulate_demand_year
    from microgrid_expansion.sites import get_site

    site = get_site("Samionta")
    without = simulate_demand_year(site, 2025, seed=3, maturity_months=24,
                                   trajectory="central", include_productive=False)
    with_pue = simulate_demand_year(site, 2025, seed=3, maturity_months=24,
                                    trajectory="central", include_productive=True)

    assert with_pue.annual_energy_kwh > without.annual_energy_kwh
    assert with_pue.enterprises and not without.enterprises

    daytime = lambda y: y.hourly_kw.reshape(-1, 24)[:, 7:19].sum() / y.hourly_kw.sum()
    assert daytime(with_pue) > daytime(without)


def test_a_surveyed_roster_is_taken_as_stated_and_not_drawn(calibration):
    """When the developer counted the enterprises, the model must not guess at them.

    The mix is otherwise drawn from the two calibration villages, which is the right
    answer for a community nobody has visited and the wrong one for a community somebody
    has: a village with six mills and no cold room is not the average of Samionta and
    Gbowele, and a sizing that averages it away loses exactly the daytime load that decides
    how the array is coupled.
    """
    rng = np.random.default_rng(0)
    declared = {"milling": 6, "refrigeration": 0, "small_trade": 11}
    units = P.sample_units(calibration, 180, "central", "central", rng,
                           declared_mix=declared)
    assert units["milling"] == 6
    assert units["refrigeration"] == 0
    assert units["small_trade"] == 11
    # Every class the model knows is reported, so that a class the survey did not mention
    # reads as none rather than as missing.
    assert set(units) == set(calibration.mix.index)
    assert all(v == 0 for k, v in units.items() if k not in declared)
    # And it is a statement, not a seed: the same roster returns the same counts whatever
    # the draw would have been.
    again = P.sample_units(calibration, 180, "central", "central",
                           np.random.default_rng(99), declared_mix=declared)
    assert again == units


def test_a_negative_count_is_read_as_none_rather_than_as_a_credit(calibration):
    """A form can send a negative number; a village cannot have minus two mills."""
    units = P.sample_units(calibration, 120, "central", "central",
                           np.random.default_rng(1), declared_mix={"milling": -2})
    assert units["milling"] == 0
