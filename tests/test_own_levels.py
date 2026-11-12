"""A village with a plant starts from what its productive users draw, not from a class's mean.

The class profiles describe a unit of a class, and a village's units are not that unit: the
class ``milling`` averages one mill of Samionta at 14 kWh a day and two of Gbowele below one.
A brownfield year therefore draws each productive user its record holds at the level its
own meter measured, with its own month-to-month pattern where its readings cover a year,
on its class's hourly shape; the users the rule adds after the record keep the class
profile. These tests hold that, and that nothing changes for a year without the record's
levels.

Every simulated year is a small synthetic village with the appliance library silenced, so
that the productive users are all there is to read.
"""
from __future__ import annotations

import calendar
import dataclasses

import numpy as np
import pandas as pd
import pytest

from microgrid_expansion.demand import connection as conn
from microgrid_expansion.demand.connection import ConnectionSchedule, RecordUser
from microgrid_expansion.sites import Site

REFERENCE_SITES = ("Samionta", "Gbowele")


def _quiet(monkeypatch) -> None:
    """No household draws anything, and no community building is declared."""
    from microgrid_expansion.demand import generator

    monkeypatch.setattr(
        generator, "sample_composition",
        lambda law, census, month, rng, by_maturity=False:
        {"0": 0, "1": 0, "2": 0, "3": 0, "inactive": sum(census.values())})
    monkeypatch.setattr(generator, "_simulate_month",
                        lambda counts, appliances, year, month, seed, rng, scaling=None:
                        np.zeros(calendar.monthrange(year, month)[1] * 1440))


def _steady(monkeypatch):
    """The shipped calibration with every class's day-to-day spread at zero, so that a
    month's energy is its expectation exactly."""
    from microgrid_expansion.demand import productive

    calibration = productive.ProductiveCalibration.load()
    profiles = calibration.profiles.copy()
    profiles["daily_cv"] = 0.0
    steady = dataclasses.replace(calibration, profiles=profiles)
    monkeypatch.setattr(productive.ProductiveCalibration, "load", classmethod(lambda cls: steady))
    return steady


def _no_rule(monkeypatch) -> None:
    """The rule adds no user beyond the record."""
    from microgrid_expansion.demand import productive

    monkeypatch.setattr(productive, "sample_units",
                        lambda cal, n, band, trajectory, rng, expected_units=None,
                        declared_mix=None: {k: 0 for k in cal.mix.index})


def _class_day(calibration, klass: str) -> float:
    hours = [h for h in range(24) if h in calibration.profiles.columns]
    return float(calibration.profiles.loc[klass, hours].sum())


def _schedule(users, months: int = 6, households: int = 4) -> ConnectionSchedule:
    """A record of ``months`` months with ``households`` on the grid throughout."""
    count = tuple(sum(u.present(a) for u in users) for a in range(months))
    return ConnectionSchedule(("HH1",), (40,), ((households,),) * months,
                              productive=count, productive_users=tuple(users))


def _monthly(series: np.ndarray, year: int) -> pd.Series:
    index = pd.date_range(f"{year}-01-01", periods=series.size, freq="h")
    return pd.Series(series, index=index).groupby(index.month).sum()


# ---------------------------------------------------------------- the generator
def test_a_user_draws_its_own_level_and_its_own_months(monkeypatch) -> None:
    from microgrid_expansion.demand import generator

    _quiet(monkeypatch)
    _steady(monkeypatch)
    _no_rule(monkeypatch)
    pattern = tuple(0.5 + m / 12 for m in range(12))
    pattern = tuple(f / (sum(f * calendar.monthrange(2025, m + 1)[1]
                             for m, f in enumerate(pattern)) / 365) for f in pattern)
    users = [RecordUser("milling", 0, None, 14.0, pattern, daily_cv=0.0),
             RecordUser("small_trade", 2, None, 0.3)]
    site = Site(name="Samionta", census={"HH1": 40})
    year = generator.simulate_demand_year(site, 2025, seed=1, maturity_months=0,
                                          trajectory="central", connection=_schedule(users))
    mill = _monthly(year.parts["productive:milling"], 2025)
    for month, energy in mill.items():
        days = calendar.monthrange(2025, month)[1]
        assert energy == pytest.approx(14.0 * pattern[month - 1] * days, rel=1e-9)
    trade = _monthly(year.parts["productive:small_trade"], 2025)
    assert trade[1] == 0.0 and trade[2] == 0.0, "a user is drawn from the month it joined"
    assert trade[3] == pytest.approx(0.3 * 31, rel=1e-9)
    # The hourly shape is the class's: the mill draws nothing in the small hours.
    day = year.parts["productive:milling"][:24]
    assert day[:6].sum() < 0.01 * day.sum() and day.argmax() >= 7


def test_a_user_without_a_level_draws_its_class_profile(monkeypatch) -> None:
    from microgrid_expansion.demand import generator

    _quiet(monkeypatch)
    steady = _steady(monkeypatch)
    _no_rule(monkeypatch)
    users = [RecordUser("refrigeration", 0, None, None)]
    site = Site(name="Samionta", census={"HH1": 40})
    year = generator.simulate_demand_year(site, 2025, seed=2, maturity_months=0,
                                          trajectory="central", connection=_schedule(users))
    energy = _monthly(year.parts["productive:refrigeration"], 2025)
    assert energy[1] == pytest.approx(_class_day(steady, "refrigeration") * 31, rel=1e-9)


def test_the_users_the_rule_adds_after_the_record_keep_the_class_profile(monkeypatch) -> None:
    from microgrid_expansion.demand import generator, productive

    _quiet(monkeypatch)
    steady = _steady(monkeypatch)

    def added(cal, n, band, trajectory, rng, expected_units=None, declared_mix=None):
        units = {k: 0 for k in cal.mix.index}
        if expected_units:            # beyond the record: two small traders
            units["small_trade"] = 2
        return units

    monkeypatch.setattr(productive, "sample_units", added)
    # A record of six months and a household more after it, so that the rule adds users.
    users = [RecordUser("small_trade", 0, None, 1.0, daily_cv=0.0)]
    schedule = ConnectionSchedule(("HH1",), (40,), ((4,),) * 6 + ((40,),),
                                  productive=(1,) * 6, productive_users=tuple(users))
    site = Site(name="Samionta", census={"HH1": 40})
    year = generator.simulate_demand_year(site, 2025, seed=3, maturity_months=0,
                                          trajectory="central", connection=schedule)
    energy = _monthly(year.parts["productive:small_trade"], 2025)
    unit = _class_day(steady, "small_trade")
    assert energy[1] == pytest.approx(1.0 * 31, rel=1e-9), "on the record, the user alone"
    assert year.enterprises[1]["small_trade"] == 1
    assert energy[8] == pytest.approx((1.0 + 2 * unit) * 31, rel=1e-9)
    assert year.enterprises[8]["small_trade"] == 3, "the record's user stays"


def test_the_parts_add_up_to_the_billed_load() -> None:
    from microgrid_expansion.demand.generator import simulate_demand_year

    site = Site(name="Samionta", census={"HH1": 2, "HH2": 1, "HH3": 0},
                community_mix={"place_of_worship": 1}, self_mix={"powerhouse": 1})
    year = simulate_demand_year(site, 2025, seed=5, maturity_months=14)
    billed = year.hourly_kw - (0.0 if year.unbilled_kw is None else year.unbilled_kw)
    assert np.allclose(sum(year.parts.values()), billed, atol=1e-9)
    assert "households" in year.parts and "community:place_of_worship" in year.parts


def test_the_classes_drawn_apart_add_up_to_the_load_drawn_before() -> None:
    """Where no unit passes its class's ceiling, as on these thirty days, the parts are the
    single sum the generator drew before them, to the last bit."""
    from microgrid_expansion.demand import productive

    calibration = productive.ProductiveCalibration.load()
    counts = {"milling": 2, "small_trade": 5, "refrigeration": 0, "incubation": 1}
    apart = productive.monthly_profile_parts(counts, calibration, 30,
                                             np.random.default_rng(7))
    total = np.zeros(30 * 24)
    for part in apart.values():
        total += part
    # The single sum the generator drew before the parts, written out as it was.
    rng, before = np.random.default_rng(7), np.zeros(30 * 24)
    hours = [h for h in range(24) if h in calibration.profiles.columns]
    for klass, n in counts.items():
        if not n:
            continue
        shape = calibration.profiles.loc[klass, hours].to_numpy(dtype=float)
        spread = float(calibration.profiles.loc[klass].get("daily_cv", 0.0) or 0.0)
        sigma = float(np.sqrt(np.log1p(spread ** 2)))
        factors = rng.lognormal(-0.5 * sigma ** 2, sigma, size=(n, 30))
        before += (factors.sum(axis=0)[:, None] * shape[None, :]).ravel()
    assert np.array_equal(before, total), "to the last bit"
    assert set(apart) == {"milling", "small_trade", "incubation"}


# ---------------------------------------------------------------- the schedule
def test_the_levels_enter_the_digest_and_only_where_there_are_some() -> None:
    users = (RecordUser("milling", 0, None, 14.0),)
    with_levels = _schedule(users)
    other = _schedule((RecordUser("milling", 0, None, 13.0),))
    bare = ConnectionSchedule(("HH1",), (40,), ((4,),) * 6, productive=(1,) * 6)
    assert with_levels.digest(11) != other.digest(11)
    assert with_levels.digest(11) != bare.digest(11)
    assert not with_levels.is_whole_census
    # A user joining after the year's last month does not move its key.
    late = _schedule((RecordUser("milling", 0, None, 14.0),
                      RecordUser("milling", 5, None, 1.0)))
    assert late.digest(3) == with_levels.digest(3) and late.digest(5) != with_levels.digest(5)


def test_a_schedule_refuses_levels_that_disagree_with_its_count() -> None:
    with pytest.raises(ValueError, match="listed one by one"):
        ConnectionSchedule(("HH1",), (40,), ((4,),) * 3, productive=(2, 2, 2),
                           productive_users=(RecordUser("milling", 0, None, 1.0),))


def test_beyond_the_record_the_users_of_its_last_month_stay() -> None:
    users = (RecordUser("milling", 0, None, 1.0), RecordUser("milling", 1, 3, 1.0),
             RecordUser("small_trade", 4, None, 1.0))
    schedule = _schedule(users)
    assert len(schedule.held_users(2)) == 2 and len(schedule.held_users(3)) == 1
    assert schedule.held_users(30) == schedule.held_users(5)
    assert len(schedule.held_users(30)) == 2


# ---------------------------------------------------------------- the record
@pytest.mark.parametrize("name", REFERENCE_SITES)
def test_the_shipped_levels_are_the_users_the_record_holds(name) -> None:
    observed = conn.observed_state(name)
    users = observed.productive_users
    assert users, f"{name} has no productive user at its own level"
    for age, count in enumerate(observed.productive):
        assert sum(u.present(age) for u in users) == count
    for age in range(observed.last_age + 1):
        stock = dict(zip(observed.categories, observed.connected(age)))
        for kind, n in stock.items():
            assert sum(u.present(age) for u in observed.household_users
                       if u.kind == kind) == n
    assert observed.community_users, f"{name}'s places of worship are on its record"
    table = conn.load_levels(name).set_index("customer_code")
    from microgrid_expansion.demand.build_own_levels import MIN_LEVEL_DAYS
    from microgrid_expansion.demand.growth import seasonal_index

    season = seasonal_index().to_numpy()
    for code, row in table.iterrows():
        if row.level_source == "laws":
            # Too few days for a level of its own: drawn from the laws, never one that left.
            assert row.kwh_per_day == "" and float(row.days_read) < MIN_LEVEL_DAYS
            assert row.departure_month == ""
        else:
            assert row.level_source == "own" and row.kwh_per_day != ""
            assert row.departure_month != "" or float(row.days_read) >= MIN_LEVEL_DAYS
    drawn = sum(u.kwh_per_day is None for u in (*users, *observed.household_users,
                                                *observed.community_users))
    assert drawn == int((table.level_source == "laws").sum()), \
        "the customers without a level are those drawn from the laws"
    days = [calendar.monthrange(2025, m)[1] for m in range(1, 13)]
    for code, row in table.iterrows():
        factors = np.array([float(row[f"f{m:02d}"]) for m in range(1, 13)]) \
            if row.factor_source else None
        if row.factor_source == "own":
            # The level is the year's mean: the factors average to one over its days.
            assert np.average(factors, weights=days) == pytest.approx(1.0, abs=1e-5)
        elif row.factor_source == "season":
            # A household without a year follows the households' index, rescaled.
            assert row.customer_type in ("HH1", "HH2", "HH3")
            np.testing.assert_allclose(factors / season, factors[0] / season[0], rtol=1e-5)
        else:
            assert row.customer_type in ("PUE", "CHU") or row.level_source != "own"


def test_each_reading_counts_over_its_own_period() -> None:
    from microgrid_expansion.demand.build_meter_archive import LONGEST_PERIOD_S, with_periods

    times = pd.to_datetime(["2026-06-01 00:15", "2026-06-01 00:30", "2026-06-01 02:30",
                            "2026-06-05 02:30"])
    readings = pd.DataFrame({"timestamp": times, "customer_code": "0001SAM",
                             "power_W": [400.0, 400.0, 400.0, 400.0]})
    timed = with_periods(readings)
    assert timed.seconds.tolist() == [900.0, 900.0, 7200.0, LONGEST_PERIOD_S]
    # A reading after a gap holds the gap's energy, which a quarter-hour apiece drops.
    assert timed.kwh.iloc[2] == pytest.approx(0.8)
    quarter = (readings.power_W * 0.25 / 1000).sum()
    assert timed.kwh.sum() > quarter


def test_a_level_is_the_mean_over_the_time_the_readings_cover(monkeypatch) -> None:
    from microgrid_expansion.demand import build_own_levels as B
    from microgrid_expansion.demand import readings

    # Two users: one at 100 W through a whole year, twice as much in March, one connected
    # four months before the record's end with a gap of an hour every day.
    stamps = pd.date_range("2025-11-01 00:15", "2026-10-31 23:45", freq="15min")
    steady = pd.DataFrame({"timestamp": stamps, "customer_code": "0001SAM",
                           "power_W": np.where(stamps.month == 3, 200.0, 100.0)})
    late = pd.date_range("2026-07-01 00:15", "2026-10-31 23:45", freq="15min")
    late = late[(late.hour != 3) | (late.minute == 45)]
    gappy = pd.DataFrame({"timestamp": late, "customer_code": "0002SAM", "power_W": 50.0})
    archive = readings.with_periods(pd.concat([steady, gappy]))
    monkeypatch.setattr(readings, "timed_readings", lambda site: archive)
    users = pd.DataFrame({"site_name": "Samionta", "customer_code": ["0001SAM", "0002SAM"],
                          "connection_month": ["2025-06", "2026-07"],
                          "departure_month": ["", ""], "record_end": "2026-10"})
    table = B.own_levels(users, pd.Series({"0001SAM": "small_trade"})).set_index(
        "customer_code")
    days = np.array([30, 31, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31])     # Nov to Oct
    expected = (100.0 * days.sum() + 100.0 * 31) / days.sum() * 24 / 1000
    assert table.at["0001SAM", "kwh_per_day"] == pytest.approx(expected, rel=1e-6)
    assert table.at["0001SAM", "f03"] / table.at["0001SAM", "f04"] == pytest.approx(2.0)
    # The gap's catch-up reading carries the hour, so the level is the meter's 50 W.
    assert table.at["0002SAM", "kwh_per_day"] == pytest.approx(1.2, rel=1e-6)
    assert np.isnan(table.at["0002SAM", "f01"]), "four months make no seasonal pattern"
    assert table.at["0001SAM", "shape"] == "small_trade" and table.at["0002SAM", "shape"] == ""
    assert table.at["0001SAM", "customer_type"] == "PUE"
    # The peak is the highest hourly mean of the readings: March's 200 W.
    assert table.at["0001SAM", "peak_kw"] == pytest.approx(0.2)


def test_a_held_out_level_stops_where_it_is_told() -> None:
    from microgrid_expansion.demand import record_check

    observed = record_check.held_out_state("Samionta", last="2026-04")
    shipped = conn.observed_state("Samionta")
    assert len(observed.productive_users) == len(shipped.productive_users)
    late = [u for u in observed.productive_users if u.joined > observed.age_in("2026-04")]
    assert late and all(u.kwh_per_day is None for u in late), \
        "a user connected after the levels' last month draws its class's profile"
    assert any(a.kwh_per_day != b.kwh_per_day
               for a, b in zip(observed.productive_users, shipped.productive_users))
    # Gbowele connected 35 households in May 2026.
    gbowele = record_check.held_out_state("Gbowele", last="2026-04")
    homes = [u for u in gbowele.household_users if u.joined > gbowele.age_in("2026-04")]
    assert homes and all(u.kwh_per_day is None for u in homes), \
        "a household connected after the levels' last month is drawn from the mixture law"
