"""A village with a plant starts from what each of its customers draws, households included.

Session 4 ter drew the record's productive users at their own levels and left the households
to the mixture law, which drew Samionta's 58 % above their meters and Gbowele's 33 % below.
Each household and place of worship the record holds now keeps its own level too; the law
composes only the households that connect after the record, and an anchored household's
level grows beyond it along the village's own trajectory, never past two years. A busy day
of an anchored customer runs longer rather than harder, within what its meter recorded.

The households are read with each reading over its own period, in the segmentation as in
the levels. These tests hold those properties on small synthetic villages, the appliance
library silenced wherever only the record's customers are being read.
"""
from __future__ import annotations

import calendar
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from microgrid_expansion.demand import growth
from microgrid_expansion.demand.connection import ConnectionSchedule, ObservedState, RecordUser
from microgrid_expansion.sites import Site


def _silent_households(monkeypatch) -> None:
    """The appliance library draws nothing, so that the anchored households are all there
    is to read."""
    from microgrid_expansion.demand import generator

    monkeypatch.setattr(generator, "_simulate_month",
                        lambda counts, appliances, year, month, seed, rng, scaling=None:
                        np.zeros(calendar.monthrange(year, month)[1] * 1440))


def _home(joined=0, left=None, level=0.3, monthly=(), kind="HH1", archetype="1",
          peak=None) -> RecordUser:
    return RecordUser(archetype, joined, left, level, monthly, daily_cv=0.0, peak_kw=peak,
                      kind=kind)


def _record(homes, months: int, after=()) -> ConnectionSchedule:
    """A record of ``months`` months whose households are ``homes``, and ``after`` the stock
    of each month beyond it."""
    stock = [(sum(u.joined <= a for u in homes),) for a in range(months)]
    departures = tuple((u.joined, u.left, 0, 1) for u in homes if u.left is not None)
    return ConnectionSchedule(("HH1",), (40,), tuple(stock) + tuple((n,) for n in after),
                              departures=departures, productive=(0,) * months,
                              household_users=tuple(homes))


def _monthly(series: np.ndarray, year: int) -> pd.Series:
    index = pd.date_range(f"{year}-01-01", periods=series.size, freq="h")
    return pd.Series(series, index=index).groupby(index.month).sum()


# ------------------------------------------------------------------ the households
def test_a_household_of_the_record_draws_its_own_level_and_months(monkeypatch) -> None:
    from microgrid_expansion.demand import generator

    _silent_households(monkeypatch)
    pattern = tuple(0.5 + m / 12 for m in range(12))
    pattern = tuple(f / (sum(f * calendar.monthrange(2025, m + 1)[1]
                             for m, f in enumerate(pattern)) / 365) for f in pattern)
    homes = [_home(level=0.4, monthly=pattern), _home(level=0.2), _home(joined=3, level=1.0)]
    site = Site(name="Village", census={"HH1": 40})
    year = generator.simulate_demand_year(site, 2025, seed=1, maturity_months=0,
                                          trajectory="central", include_productive=False,
                                          connection=_record(homes, 12))
    energy = _monthly(year.parts["households"], 2025)
    for month, value in energy.items():
        days = calendar.monthrange(2025, month)[1]
        expected = 0.4 * pattern[month - 1] + 0.2 + (1.0 if month >= 4 else 0.0)
        assert value == pytest.approx(expected * days, rel=1e-9)
    assert year.anchored[1] == {"HH1": 2} and year.anchored[4] == {"HH1": 3}
    assert all(n == 0 for counts in year.composition.values() for n in counts.values()), \
        "the mixture law composes none of the record's households"
    # The shape is the archetype's: a frugal evening household draws little at noon.
    day = year.parts["households"][:24]
    assert day[12] < day[20]


def test_the_households_that_connect_after_the_record_are_composed_by_the_law() -> None:
    homes = [_home(), _home(joined=2), _home(joined=1, left=4)]
    schedule = _record(homes, 6, after=(5, 5, 7))
    assert len(schedule.anchored_households(5)) == 2, "the one that left is gone"
    assert schedule.drawn_by_band(5) == {}
    # Village month 8: two households joined at month 6 and two at month 8, beside the two
    # of the record still on the grid.
    assert schedule.drawn_by_band(8) == {"0-3": {"HH1": 4}}
    assert sum(sum(c.values()) for c in schedule.census_by_band(8).values()) == 6
    # A record household without a level is composed by the law too.
    unread = _record([_home(), _home(level=None)], 3)
    assert unread.drawn_by_band(2) == {"0-3": {"HH1": 1}}


def test_a_household_level_grows_along_the_trajectory_and_never_past_two_years() -> None:
    bands = ["0-3", "4-6", "7-12", "13-24", "25+"]
    energy = pd.Series([0.2, 0.3, 0.4, 0.5, 0.9],
                       index=pd.MultiIndex.from_tuples([(b, "HH1") for b in bands],
                                                       names=["maturity", "customer_type"]))
    assert growth.anchored_growth(energy, "HH1", 5, 10) == pytest.approx(0.4 / 0.3)
    assert growth.anchored_growth(energy, "HH1", 10, 40) == pytest.approx(0.5 / 0.4), \
        "held at two years: the 25+ band is never reached"
    assert growth.anchored_growth(energy, "HH1", 30, 60) == 1.0
    assert growth.anchored_growth(energy, "HH1", 10, 10) == 1.0
    assert growth.anchored_growth(energy, "HH3", 5, 10) == pytest.approx(0.4 / 0.3), \
        "a category the law lacks reads the mean over the ones it holds"
    assert growth.ANCHORED_GROWTH_MONTHS == 24


def test_beyond_the_record_an_anchored_household_grows_from_its_age_then(monkeypatch) -> None:
    from microgrid_expansion.demand import generator

    _silent_households(monkeypatch)
    homes = [_home(level=0.3)]
    site = Site(name="Village", census={"HH1": 40})
    year = generator.simulate_demand_year(site, 2025, seed=2, maturity_months=0,
                                          trajectory="fast", include_productive=False,
                                          connection=_record(homes, 6))
    energy = _monthly(year.parts["households"], 2025)
    law = growth.household_energy(growth.trajectory_law("fast"))
    for month in range(1, 13):
        days = calendar.monthrange(2025, month)[1]
        factor = growth.anchored_growth(law, "HH1", 5, month - 1)
        assert energy[month] == pytest.approx(0.3 * factor * days, rel=1e-9)
    assert growth.anchored_growth(law, "HH1", 5, 11) != 1.0, "the fast law grows by then"


def test_a_record_whose_households_disagree_with_its_stock_is_refused() -> None:
    with pytest.raises(ValueError, match="listed one by one"):
        ConnectionSchedule(("HH1",), (40,), ((2,),) * 3, productive=(0, 0, 0),
                           household_users=(_home(),))
    with pytest.raises(ValueError, match="build_own_levels"):
        ObservedState("Village", "2025-01", "2025-03", ("HH1",), ((2,),) * 3,
                      productive=(0, 0, 0), household_users=(_home(),))


def test_the_record_s_households_enter_the_digest_and_only_where_there_are_some() -> None:
    bare = ConnectionSchedule(("HH1",), (40,), ((1,),) * 3, productive=(0, 0, 0))
    homes = _record([_home()], 3)
    other = _record([_home(level=0.31)], 3)
    assert homes.digest(5) != bare.digest(5) and homes.digest(5) != other.digest(5)
    assert not homes.is_whole_census


# ------------------------------------------------------------- the places of worship
def test_a_place_of_worship_of_the_record_replaces_its_class_count(monkeypatch) -> None:
    from microgrid_expansion.demand import generator

    _silent_households(monkeypatch)
    site = Site(name="Village", census={"HH1": 40}, community_mix={"place_of_worship": 2})
    church = RecordUser("place_of_worship", 0, None, 0.25, (), daily_cv=0.0, kind="CHU")
    schedule = ConnectionSchedule(("HH1",), (40,), ((1,),) * 3, productive=(0, 0, 0),
                                  community_users=(church,))
    year = generator.simulate_demand_year(site, 2025, seed=3, maturity_months=0,
                                          include_productive=False, connection=schedule)
    energy = _monthly(year.parts["community:place_of_worship"], 2025)
    assert energy[1] == pytest.approx(0.25 * 31, rel=1e-9)
    assert energy[12] == pytest.approx(0.25 * 31, rel=1e-9), "beyond the record it stays"
    # Without it, the class's two buildings draw their measured mean day.
    plain = ConnectionSchedule(("HH1",), (40,), ((1,),))
    drawn = generator.simulate_demand_year(site, 2025, seed=3, maturity_months=0,
                                           include_productive=False, connection=plain)
    assert drawn.parts["community:place_of_worship"].sum() > 3 * year.parts[
        "community:place_of_worship"].sum()


# --------------------------------------------------------------- a busy day's shape
def test_a_busy_day_runs_longer_and_stays_within_the_recorded_power() -> None:
    from microgrid_expansion.demand.productive import longer_days

    mean_day = np.array([0.0] * 7 + [1.0, 2.0, 3.0, 3.0, 2.0, 1.0] + [0.2] * 5 + [0.0] * 6)
    factors = np.array([0.5, 1.0, 2.0, 3.0, 40.0])
    days = longer_days(mean_day, factors, cap=4.0)
    plain = factors[:, None] * mean_day[None, :]
    assert days.max() <= 4.0 + 1e-12
    np.testing.assert_allclose(days[:4].sum(axis=1), factors[:4] * mean_day.sum(), rtol=1e-12)
    np.testing.assert_array_equal(days[:2], plain[:2]), "a day within the cap is the plain one"
    # The busy days fill the hours their mean day leaves free, and leave idle hours idle.
    free = plain[2:4] < 4.0
    assert np.all(days[2:4][free] >= plain[2:4][free] - 1e-12)
    assert (days[3] > 0).sum() == (mean_day > 0).sum() and days[3][:7].sum() == 0.0
    # A day beyond every hour's cap is held at the cap.
    np.testing.assert_array_equal(days[4], np.where(mean_day > 0, 4.0, 0.0))
    np.testing.assert_array_equal(longer_days(mean_day, factors, None), plain)


# ------------------------------------------------------- readings over their own period
def test_a_household_month_counts_each_reading_over_its_own_period() -> None:
    from microgrid_expansion.demand.build_monthly_household_clusters import (
        compute_monthly_features)

    stamps = pd.date_range("2026-03-01 00:15", "2026-03-01 23:45", freq="15min")
    stamps = stamps[(stamps.hour < 10) | (stamps.hour >= 12) | (stamps == "2026-03-01 11:45")]
    readings = pd.DataFrame({"timestamp": stamps.append(pd.DatetimeIndex(["2026-03-02 00:00"])),
                             "customer_code": "0001SAM", "power_W": 100.0,
                             "site_name": "Samionta"})
    customers = pd.DataFrame({"customer_code": ["0001SAM"], "customer_type": ["HH1"],
                              "site_name": ["Samionta"],
                              "connection_date": [pd.Timestamp("2025-01-01")]})
    month = compute_monthly_features(readings, customers).set_index("month")
    march = month.loc["2026-03"]
    # The reading at 11:45 carries the gap since 09:45, two hours and not a quarter of one,
    # and the readings cover the day from midnight to midnight.
    assert march.total_kWh == pytest.approx(2.4)
    assert march.covered_days == pytest.approx(1.0)
    assert march.mean_daily_kWh == pytest.approx(2.4), "the meter's 100 W over a day"
    # A quarter-hour apiece over the dates read gave the gap nothing and halved the day.
    assert len(readings) * 0.025 < 2.3 and march.observed_days == 2


# --------------------------------------------------------------- the class tables
def test_the_class_tables_read_the_record_s_mill_as_a_mill() -> None:
    from microgrid_expansion.demand.build_productive_profiles import RECORD_CLASS, record_classes
    from microgrid_expansion.demand.productive import ProductiveCalibration

    classes, sources = record_classes(None, {"0097SAM", "0001SAM"})
    assert classes["0097SAM"] == RECORD_CLASS["0097SAM"] == "milling"
    assert sources["0097SAM"] == "record" and classes["0001SAM"] == "small_trade"
    # Samionta's fourteen enterprises of the roster include its two mills.
    assert ProductiveCalibration.load().mix.at["milling", "slow"] == pytest.approx(2 / 14,
                                                                                  abs=1e-6)


# ----------------------------------------------------------- the village's own growth
def test_a_run_from_a_village_s_record_follows_its_own_growth() -> None:
    from microgrid_expansion.exact.certify import growth_trajectory
    from microgrid_expansion.scenarios.assemble import own_growth_space
    from microgrid_expansion.scenarios.uncertainty_space import UncertaintySpace

    assert growth.own_trajectory("Samionta") == "slow"
    assert growth.own_trajectory("Gbowele") == "fast"
    assert growth.own_trajectory("Elsewhere") is None
    record, bare = SimpleNamespace(year0_age=31), SimpleNamespace(year0_age=None)
    assert growth_trajectory("Samionta", record) == "slow"
    assert growth_trajectory("Gbowele", record) == "fast"
    assert growth_trajectory("Samionta", bare) == "central"
    assert growth_trajectory("Samionta", record, "central") == "central"
    space = UncertaintySpace()
    assert own_growth_space(space, "Gbowele", record).demand.trajectory_probabilities \
        == (0.0, 0.0, 1.0)
    assert own_growth_space(space, "Gbowele", bare) is space


# ------------------------------------------------- session 4 quater: the author's rules
def test_a_level_needs_four_weeks_of_readings_or_the_laws_draw_it(monkeypatch) -> None:
    from microgrid_expansion.demand import build_own_levels as B
    from microgrid_expansion.demand import readings

    def meter(code, start, end, watts):
        stamps = pd.date_range(start, end, freq="15min")
        return pd.DataFrame({"timestamp": stamps, "customer_code": code, "power_W": watts})

    archive = readings.with_periods(pd.concat([
        meter("0001SAM", "2026-10-20 00:15", "2026-10-31 23:45", 500.0),   # twelve days
        meter("0002SAM", "2026-09-01 00:15", "2026-10-31 23:45", 20.0),    # two months
        meter("0003SAM", "2026-10-20 00:15", "2026-10-31 23:45", 90.0),    # twelve days
        meter("0004SAM", "2026-09-10 00:15", "2026-09-14 23:45", 0.0),     # five, then gone
    ]))
    monkeypatch.setattr(readings, "timed_readings", lambda site: archive)
    users = pd.DataFrame({"site_name": "Samionta",
                          "customer_code": ["0001SAM", "0002SAM", "0003SAM", "0004SAM"],
                          "customer_type": ["HH1", "HH1", "PUE", "HH1"],
                          "connection_month": ["2026-10", "2026-09", "2026-10", "2026-09"],
                          "departure_month": ["", "", "", "2026-10"],
                          "record_end": "2026-10"})
    season = pd.Series(np.linspace(1.3, 0.7, 12), index=range(1, 13))
    table = B.own_levels(users, season=season).set_index("customer_code")
    assert B.MIN_LEVEL_DAYS == 28
    for code in ("0001SAM", "0003SAM"):
        assert table.at[code, "level_source"] == "laws" and np.isnan(table.at[code,
                                                                          "kwh_per_day"])
        assert table.at[code, "days_read"] < 28 and np.isnan(table.at[code, "f01"])
    assert table.at["0002SAM", "level_source"] == "own"
    assert table.at["0002SAM", "kwh_per_day"] == pytest.approx(0.48, rel=1e-6)
    assert table.at["0004SAM", "level_source"] == "own", "a customer that left keeps its level"
    assert table.at["0004SAM", "kwh_per_day"] == 0.0
    # Without the rule, the twelve days make a level.
    loose = B.own_levels(users, season=season, min_days=0.0).set_index("customer_code")
    assert loose.at["0001SAM", "kwh_per_day"] == pytest.approx(12.0, rel=1e-3)
    assert loose.at["0001SAM", "level_source"] == "own"


def test_a_household_without_a_year_follows_the_index_around_its_own_level(monkeypatch) -> None:
    from microgrid_expansion.demand import build_own_levels as B
    from microgrid_expansion.demand import readings

    stamps = pd.date_range("2026-05-01 00:15", "2026-10-31 23:45", freq="15min")
    stamps = stamps[(stamps.month != 7) | (stamps.day <= 10)]          # July read in part
    archive = readings.with_periods(pd.DataFrame({"timestamp": stamps,
                                                  "customer_code": "0001SAM",
                                                  "power_W": 15.0}))
    monkeypatch.setattr(readings, "timed_readings", lambda site: archive)
    users = pd.DataFrame({"site_name": "Samionta", "customer_code": ["0001SAM"],
                          "customer_type": ["HH1"], "connection_month": ["2026-05"],
                          "departure_month": [""], "record_end": "2026-10"})
    season = pd.Series([1.35, 1.26, 1.24, 1.11, 0.92, 0.82, 0.86, 0.77, 0.73, 0.91, 1.06, 0.96],
                       index=range(1, 13))
    row = B.own_levels(users, season=season).iloc[0]
    factors = np.array([row[f"f{m:02d}"] for m in range(1, 13)])
    assert row.factor_source == "season"
    np.testing.assert_allclose(factors / season.to_numpy(), factors[0] / season[1])
    # Over the months it was read, each weighted by the time its readings cover in it, the
    # household draws its measured level; it draws more in the dry season it was not read.
    covered = archive.groupby("month").seconds.sum()
    weights = np.array([covered.get(pd.Period(f"2026-{m:02d}", freq="M"), 0.0)
                        for m in range(1, 13)])
    assert np.average(factors, weights=weights) == pytest.approx(1.0, rel=1e-9)
    assert factors[0] > 1.4 and np.average(factors, weights=[
        calendar.monthrange(2026, m)[1] for m in range(1, 13)]) > 1.1
    # A productive user without a year keeps no factors: the index is the households'.
    user = B.own_levels(users.assign(customer_type="PUE"), season=season).iloc[0]
    assert user.factor_source == "" and np.isnan(user.f01)


def test_a_class_unit_runs_longer_days_under_its_class_s_ceiling(tmp_path) -> None:
    import dataclasses

    from microgrid_expansion.demand import productive
    from microgrid_expansion.demand.uses import CommunityCalibration

    levels = pd.DataFrame({
        "customer_code": ["0001SAM", "0002SAM", "0003SAM", "0004SAM", "0005SAM"],
        "customer_type": ["PUE", "PUE", "PUE", "HH1", "PUE"],
        "shape": ["milling", "milling", "milling", "1", "milling"],
        "kwh_per_day": [2.4, 4.8, 1.2, 0.5, None],
        "peak_kw": [0.5, 2.0, 1.0, 5.0, None]})
    path = tmp_path / "own_levels.csv"
    levels.to_csv(path, index=False)
    ratios = productive.peak_ratios(path)
    # Ratios 5, 10 and 20: the median of the class's metered units, households aside.
    assert ratios.at["milling", "units"] == 3
    assert ratios.at["milling", "peak_ratio"] == pytest.approx(10.0)

    calibration = productive.ProductiveCalibration.load()
    profiles = productive.with_ceilings(calibration.profiles, path)
    profiles.loc["milling", "daily_cv"] = 3.0
    busy = dataclasses.replace(calibration, profiles=profiles)
    shape, sigma = productive._class_day(busy, "milling")
    cap = productive.class_cap(busy, "milling", shape)
    assert cap == pytest.approx(10.0 * shape.sum() / 24.0)
    part = productive.monthly_profile_parts({"milling": 1}, busy, 365,
                                            np.random.default_rng(3))["milling"]
    days = part.reshape(365, 24)
    factors = np.random.default_rng(3).lognormal(-0.5 * sigma ** 2, sigma, size=(1, 365))[0]
    plain = factors[:, None] * shape[None, :]
    assert plain.max() > cap and days.max() <= cap + 1e-9
    within = (plain <= cap).all(axis=1)
    np.testing.assert_array_equal(days[within], plain[within])
    held = factors * shape.sum() >= cap * (shape > 0).sum()
    np.testing.assert_allclose(days[~held].sum(axis=1), plain[~held].sum(axis=1), rtol=1e-9)
    # A customer of the record without a level is a unit of its class, under the same cap.
    unit = RecordUser("milling", 0, None, None)
    drawn = productive.own_level_parts([unit], busy, 1, 365, np.random.default_rng(4))
    assert drawn["milling"].max() <= cap + 1e-9
    # The plant's own supply has no metered units, and keeps the plain scaling.
    community = CommunityCalibration.load().profiles.peak_ratio
    assert community["place_of_worship"] > 0 and np.isnan(community["powerhouse"])
