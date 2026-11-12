"""Households come onto the grid in cohorts, and each cohort ages on its own clock.

The model connected the whole census at year 0, every household twelve months old, in the
certified year and in the tree alike. The two reference villages connected a fifth and three
fifths of theirs over two and a half years. These tests state what the progressive model has
to hold, and above all that the whole census, kept as its degenerate case and as the shipped
default, still produces exactly what it produced before.

Every simulated year here is a small synthetic village, so that the appliance library stays
quick; the reference villages are used only where nothing is simulated.
"""
from __future__ import annotations

import calendar
import dataclasses
import math

import numpy as np
import pandas as pd
import pytest

from microgrid_expansion.demand import connection as conn
from microgrid_expansion.demand.connection import ConnectionCurve, ConnectionSchedule
from microgrid_expansion.sites import Site, get_site

REFERENCE_SITES = ("Samionta", "Gbowele")


def _village(**extra) -> Site:
    """Three households and the plant's own room: enough to draw, quick to simulate."""
    return Site(name="Samionta", census={"HH1": 2, "HH2": 1, "HH3": 0}, **extra)


def _every_schedule():
    """Every schedule the shipped curves can draw, at both reference villages, with the
    month from which it may no longer fall: none for a curve, the record's last for a
    village's own record, whose departures are observed."""
    from microgrid_expansion.settings import default_settings

    settings = default_settings()
    curves = []
    for plateau in ("profile_lower_bound", "census"):
        settings.connection.high_plateau = plateau
        curves += list(conn.load_curves(settings).values())
    for name in REFERENCE_SITES:
        site = get_site(name)
        own = list(conn.own_curves(name).values())
        observed = conn.observed_state(name)
        for curve in curves + own:
            yield site, ConnectionSchedule.greenfield(site, curve), 0
            yield site, ConnectionSchedule.brownfield(site, observed, curve), \
                observed.last_age


# ------------------------------------------------------------ the degenerate case
def test_the_whole_census_reproduces_the_single_cohort_year() -> None:
    from microgrid_expansion.demand.generator import simulate_demand_year

    site = _village(community_mix={"place_of_worship": 1}, self_mix={"powerhouse": 1})
    for maturity in (0, 14):
        before = simulate_demand_year(site, 2025, seed=5, maturity_months=maturity,
                                      trajectory="fast")
        after = simulate_demand_year(site, 2025, seed=5, maturity_months=maturity,
                                     trajectory="fast",
                                     connection=ConnectionSchedule.whole_census(site))
        assert np.array_equal(before.hourly_kw, after.hourly_kw)
        assert before.composition == after.composition
        assert before.enterprises == after.enterprises
        for name in ("unbilled_kw", "at_plant_kw"):
            a, b = getattr(before, name), getattr(after, name)
            assert (a is None) == (b is None) and (a is None or np.array_equal(a, b)), name
        assert all(c == site.census for c in after.connected.values())


def test_the_instant_curve_is_the_whole_census() -> None:
    for site in (_village(), *(get_site(n) for n in REFERENCE_SITES)):
        drawn = ConnectionSchedule.greenfield(site, ConnectionCurve(1.0, math.inf, 0))
        assert drawn == ConnectionSchedule.whole_census(site)
        assert drawn.is_whole_census


# ---------------------------------------------------------------- the stock (I1, I2)
def test_the_connected_stock_never_decreases() -> None:
    for site, schedule, start in _every_schedule():
        census = site.census
        previous = schedule.connected(start)
        for age in range(start, conn.HORIZON_MONTHS + 1):
            stock = schedule.connected(age)
            for k, n in stock.items():
                assert isinstance(n, int) and previous[k] <= n <= census[k], (site.name, age)
            assert all(n >= 0 for n in schedule.cohort(age).values())
            previous = stock
        assert all(0 <= n <= census[k] for age in range(start)
                   for k, n in schedule.connected(age).items())


def test_a_departure_leaves_its_own_cohort() -> None:
    # Five join at month 0 and three at month 10; one of the first five leaves at month 30.
    stock = [(5,)] * 10 + [(8,)]
    stayed = ConnectionSchedule(("HH1",), (10,), tuple(stock))
    left = ConnectionSchedule(("HH1",), (10,), tuple(stock), departures=((0, 30, 0, 1),))
    assert left.connected(29) == {"HH1": 8} and left.connected(30) == {"HH1": 7}
    assert left.census_by_band(30) == {"13-24": {"HH1": 3}, "25+": {"HH1": 4}}
    assert stayed.census_by_band(30) == {"13-24": {"HH1": 3}, "25+": {"HH1": 5}}
    assert left.digest(29) == stayed.digest(29) and left.digest(30) != stayed.digest(30)
    assert not left.is_whole_census and left != stayed
    with pytest.raises(ValueError, match="more households leave"):
        ConnectionSchedule(("HH1",), (10,), tuple(stock), departures=((10, 30, 0, 4),))
    with pytest.raises(ValueError, match="after it joined"):
        ConnectionSchedule(("HH1",), (10,), tuple(stock), departures=((10, 10, 0, 1),))


def test_each_cohort_ages_on_its_own_clock() -> None:
    stock = [(3,)] * 10 + [(7,)]
    schedule = ConnectionSchedule(("HH1",), (10,), tuple(stock))
    grouped = schedule.census_by_band(12)
    assert grouped == {"0-3": {"HH1": 4}, "7-12": {"HH1": 3}}
    assert list(grouped) == ["0-3", "7-12"], "bands must come in the order of the law"


def test_a_trajectory_never_disconnects() -> None:
    for name in REFERENCE_SITES:
        site, observed = get_site(name), conn.observed_state(name)
        below = ConnectionSchedule.brownfield(site, observed, ConnectionCurve(0.01, 0.2, 5))
        last = below.connected(observed.last_age)
        assert all(below.connected(age) == last
                   for age in range(observed.last_age, conn.HORIZON_MONTHS + 1))


# ------------------------------------------------------------------ the generator
def test_an_unconnected_household_draws_nothing(monkeypatch) -> None:
    from microgrid_expansion.demand import generator, productive

    seen = []
    original = productive.sample_units
    monkeypatch.setattr(productive, "sample_units",
                        lambda cal, n, *a, **k: seen.append(n) or original(cal, n, *a, **k))
    site = _village(community_mix={"place_of_worship": 1}, self_mix={"powerhouse": 1})
    nobody = ConnectionSchedule.greenfield(site, ConnectionCurve(1.0, math.inf, 1000))
    year = generator.simulate_demand_year(site, 2025, seed=1, maturity_months=0,
                                          connection=nobody)

    assert all(n == 0 for counts in year.composition.values() for n in counts.values())
    assert seen == [0] * 12, "the productive users were not counted on nobody"
    assert all(sum(units.values()) == 0 for units in year.enterprises.values())
    # What is left is the community and the plant's own use, there from the first month.
    first = year.monthly_energy_kwh()[1]
    assert first > 0.0 and year.at_plant_kw is not None and year.at_plant_kw[:744].any()


def _quiet_generator(monkeypatch, active_share: float = 1.0) -> None:
    """No appliance drawn, and a fixed share of every band's households active."""
    from microgrid_expansion.demand import generator

    def composition(law, census, month, rng, by_maturity=False):
        total = sum(census.values())
        active = int(round(active_share * total))
        return {"0": active, "1": 0, "2": 0, "3": 0, "inactive": total - active}

    monkeypatch.setattr(generator, "sample_composition", composition)
    monkeypatch.setattr(generator, "_simulate_month",
                        lambda counts, appliances, year, month, seed, rng, scaling=None:
                        np.zeros(calendar.monthrange(year, month)[1] * 1440))


def test_productive_users_follow_the_connected_households(monkeypatch) -> None:
    from microgrid_expansion.demand import generator, productive
    from microgrid_expansion.demand.growth import maturity_band

    # Half the connected households inactive and no appliance drawn: what is left to check
    # is the count the productive users are referred to, the connected stock.
    _quiet_generator(monkeypatch, active_share=0.5)
    calibration = productive.ProductiveCalibration.load()
    means = []
    original = productive.sample_units

    def recorded(cal, n, band, trajectory, rng, **kwargs):
        means.append((n, band, float(cal.intensity.loc[band, trajectory]) * n))
        return original(cal, n, band, trajectory, rng, **kwargs)

    monkeypatch.setattr(productive, "sample_units", recorded)
    site = Site(name="Samionta", census={"HH1": 40})
    single = [(2,), (2,), (5,), (5,), (9,)]
    double = [(2 * row[0],) for row in single]
    expected = []
    for stock in (single, double):
        means.clear()
        schedule = ConnectionSchedule(("HH1",), (40,), tuple(stock))
        year = generator.simulate_demand_year(site, 2025, seed=2, maturity_months=3,
                                              trajectory="central", connection=schedule)
        for month, (n, band, _) in enumerate(means, start=1):
            age = 3 + month - 1
            assert band == maturity_band(age), "the intensity is read on the village clock"
            assert n == sum(schedule.connected(age).values()), "the base is the stock"
            assert n > sum(v for k, v in year.composition[month].items() if k != "inactive")
        expected.append([mean for _, _, mean in means])
    assert expected[1] == pytest.approx([2 * m for m in expected[0]])
    assert calibration.intensity.loc["4-6", "central"] > 0

    # The whole census keeps the reading the model had: households outside the inactive
    # state, so that nothing drawn under it moves.
    means.clear()
    whole = Site(name="Samionta", census={"HH1": 12})
    year = generator.simulate_demand_year(whole, 2025, seed=2, maturity_months=3)
    assert [n for n, _, _ in means] == [6] * 12


def test_the_productive_intensity_scale_moves_the_rule_and_nothing_at_one(monkeypatch) -> None:
    """The sensitivity of section 14, point 14, scales what the rule draws from.

    At one the year is the year drawn without the factor, to the last value, so nothing
    computed before it moves; away from one the mean the rule draws around moves by the
    factor and nothing else does.
    """
    from microgrid_expansion.demand import generator, productive

    _quiet_generator(monkeypatch, active_share=0.5)
    means = []
    original = productive.sample_units

    def recorded(cal, n, band, trajectory, rng, **kwargs):
        means.append(float(cal.intensity.loc[band, trajectory]) * n)
        return original(cal, n, band, trajectory, rng, **kwargs)

    monkeypatch.setattr(productive, "sample_units", recorded)
    site = Site(name="Samionta", census={"HH1": 40})
    schedule = ConnectionSchedule(("HH1",), (40,), ((10,), (20,), (30,)))
    drawn = {}
    for scale in (None, 1.0, 2.0):
        means.clear()
        kwargs = {} if scale is None else {"productive_scale": scale}
        year = generator.simulate_demand_year(site, 2025, seed=4, maturity_months=2,
                                              connection=schedule, **kwargs)
        drawn[scale] = (np.asarray(year.hourly_kw), list(means))
    assert np.array_equal(drawn[None][0], drawn[1.0][0])
    assert drawn[2.0][1] == pytest.approx([2.0 * m for m in drawn[1.0][1]])


def test_the_tree_refuses_a_productive_intensity_it_would_not_read() -> None:
    from microgrid_expansion.config import ModelConfig
    from microgrid_expansion.scenarios import sample_scenario_paths, space_from_settings
    from microgrid_expansion.settings import default_settings

    settings = default_settings()
    settings.productive_intensity_scale = 0.5
    cfg = ModelConfig(site="Samionta", n_mc_paths=2, stage_years=(0, 5), branching=(1, 2))
    with pytest.raises(ValueError, match="certified year alone"):
        sample_scenario_paths(cfg, space_from_settings(settings), settings)


def test_the_observed_productive_users_are_held_on_the_record(monkeypatch) -> None:
    from microgrid_expansion.demand import generator, productive
    from microgrid_expansion.demand.growth import maturity_band

    calibration = productive.ProductiveCalibration.load()
    for name in REFERENCE_SITES:
        observed = conn.observed_state(name)
        held = observed.productive[-1]
        units = generator._observed_units(calibration, name, held)
        own = {"Samionta": "slow", "Gbowele": "fast"}[name]
        # The record holds customers the activity survey never reached, so its count need
        # not be the count the mix was measured on: the split keeps the total and each
        # class stays within one of its share.
        assert sum(units.values()) == held
        assert (abs(pd.Series(units) - calibration.mix[own] * held) < 1.0).all(), name
        # On the enterprises the mix was measured on, the split is that state exactly.
        profiled = next(n for n in range(1, 500)
                        if np.allclose(calibration.mix[own] * n,
                                       np.round(calibration.mix[own] * n), atol=1e-4))
        exact = generator._observed_units(calibration, name, profiled)
        assert np.allclose(calibration.mix[own] * profiled, pd.Series(exact), atol=1e-4)

    _quiet_generator(monkeypatch)
    means = []
    original = productive.sample_units

    def recorded(cal, n, band, trajectory, rng, expected_units=None, declared_mix=None):
        means.append(expected_units)
        return original(cal, n, band, trajectory, rng, expected_units=expected_units,
                        declared_mix=declared_mix)

    monkeypatch.setattr(productive, "sample_units", recorded)
    # A record of six months, three productive users at its end, and two more households
    # connecting after it.
    site = Site(name="Samionta", census={"HH1": 40})
    schedule = ConnectionSchedule(("HH1",), (40,), ((4,),) * 6 + ((5,), (6,)),
                                  productive=(1, 1, 2, 2, 3, 3))
    year = generator.simulate_demand_year(site, 2025, seed=4, maturity_months=2,
                                          trajectory="central", connection=schedule)
    for month, mean in enumerate(means, start=1):
        age = 2 + month - 1
        if age <= 5:
            assert mean == 0.0 and sum(year.enterprises[month].values()) \
                == schedule.productive[age], "on the record nothing is drawn"
        else:
            rise = (generator._intensity(calibration, maturity_band(age), "central")
                    * sum(schedule.connected(age).values())
                    - generator._intensity(calibration, maturity_band(5), "central") * 4)
            assert mean == pytest.approx(max(0.0, rise))
            assert sum(year.enterprises[month].values()) >= 3, "the record is held"


# ------------------------------------------------------------- the observed state
def _roster_stock(name: str) -> tuple[str, dict[str, list[int]]]:
    """Households on the grid per category and village month, net of departures."""
    table = pd.read_csv(conn.OBSERVED_PATH, keep_default_na=False)
    rows = table[(table.site_name == name) & table.customer_type.str.startswith("HH")]
    roster = pd.read_parquet(conn.REFERENCE_DIR.parents[1] / "demand"
                             / "customer_info.parquet")
    origin = roster.loc[roster.site_name == name, "connection_date"].min().to_period("M")
    last = pd.Period(conn.curve_row(name, "estimate").last_month, freq="M")
    age = lambda m: (pd.Period(m, freq="M") - origin).n if m else 10 ** 6
    stock = {}
    for k, group in rows.groupby("customer_type"):
        stock[k] = [sum(int(r.customers) for r in group.itertuples()
                        if age(r.connection_month) <= a < age(r.departure_month))
                    for a in range((last - origin).n + 1)]
    return str(origin), stock


def test_the_brownfield_state_is_the_roster() -> None:
    for name in REFERENCE_SITES:
        site, observed = get_site(name), conn.observed_state(name)
        origin, expected = _roster_stock(name)
        assert observed.origin_month == origin
        assert observed.age_in(origin) == 0
        schedule = ConnectionSchedule.brownfield(site, observed, conn.own_curves(name)["high"])
        for age in range(observed.last_age + 1):
            stock = schedule.connected(age)
            for k in site.census:
                assert stock[k] == (expected[k][age] if k in expected else 0), (name, age, k)
        january = pd.Period("2026-01", freq="M")
        assert observed.year0_age(2026) == (january - pd.Period(origin, freq="M")).n


def test_a_stale_roster_is_refused() -> None:
    observed = conn.observed_state("Samionta")
    with pytest.raises(ValueError, match="extend the roster"):
        observed.year0_age(2028)


def test_a_brownfield_run_starts_from_the_roster_and_a_new_site_from_nothing() -> None:
    from microgrid_expansion.settings import default_settings, reference_plant

    settings = default_settings()
    assert settings.connection.mode == "progressive", "the shipped connection"
    settings.connection.mode = "census"
    assert conn.plan(get_site("Samionta"), settings).schedule("low").is_whole_census
    settings.connection.mode = "progressive"
    new = conn.plan(get_site("Samionta"), settings)
    assert new.year0_age is None and set(new.schedules) == set(conn.TRAJECTORIES)
    assert sum(new.schedule("central").connected(0).values()) < 231 / 4
    settings.installed = reference_plant("Samionta")
    standing = conn.plan(get_site("Samionta"), settings)
    observed = conn.observed_state("Samionta")
    assert standing.year0_age == observed.year0_age(settings.installed.base_year)
    stock = standing.schedule("low").connected(observed.last_age)
    assert {k: stock[k] for k in observed.categories} \
        == dict(zip(observed.categories, observed.connected(observed.last_age)))


# ---------------------------------------------------------------- the calibration
@pytest.fixture(scope="module")
def rebuilt():
    from microgrid_expansion.demand.build_connection_curves import build

    return build()


def test_the_connection_curves_are_admissible(rebuilt) -> None:
    curves, _, _, reports = rebuilt
    table = pd.read_csv(conn.CURVES_PATH)
    for name in REFERENCE_SITES:
        rows = table[table.site_name == name].set_index("variant")
        assert set(rows.index) == {"estimate", "profile_lower_bound", "profile_upper_bound",
                                   "census"}, name
        assert ((rows.plateau_share > 0) & (rows.plateau_share <= 1)).all()
        assert (rows.rate_per_month > 0).all()
        report = next(r for r in reports if r["site"] == name)
        identified = report["interval"][1] < int(rows.census_households.iloc[0])
        assert (rows.identified == identified).all(), (
            f"{name}: the table says identified={rows.identified.iloc[0]} and the profile "
            f"interval {report['interval']} says otherwise")
        assert (rows.loc["profile_lower_bound", "plateau_households"],
                rows.loc["profile_upper_bound", "plateau_households"]) == report["interval"]
        own = conn.own_curves(name)
        if identified:
            # The bracket of a village's own record is its plateau's profile interval.
            for trajectory, variant in (("low", "profile_lower_bound"),
                                        ("central", "estimate"),
                                        ("high", "profile_upper_bound")):
                assert own[trajectory].share == pytest.approx(rows.loc[variant,
                                                                       "plateau_share"])
                assert own[trajectory].rate_per_month == pytest.approx(
                    rows.loc[variant, "rate_per_month"])


def test_the_connection_tables_are_what_the_builder_writes(rebuilt) -> None:
    from microgrid_expansion.demand import build_connection_curves as build

    curves, observed, status, _ = rebuilt
    stored = pd.read_csv(conn.CURVES_PATH)
    assert list(stored.columns) == list(curves.columns)
    numeric = stored.select_dtypes("number").columns
    assert np.allclose(stored[numeric].to_numpy(float), curves[numeric].to_numpy(float),
                       atol=1e-5, equal_nan=True)
    assert stored.drop(columns=numeric).astype(str).equals(
        curves.drop(columns=numeric).astype(str))
    read = lambda path: pd.read_csv(path, dtype=str, keep_default_na=False)
    assert read(conn.OBSERVED_PATH).equals(observed.astype(str).reset_index(drop=True))
    assert read(conn.REFERENCE_DIR / build.STATUS_FILE).equals(
        status.astype(str).reset_index(drop=True))

    # The archive's own customers: the census types cannot be re-read here, the census
    # being outside the repository, but the first readings and the profile types can.
    roster = build.load_roster()
    for row in build.load_archive_customers().itertuples():
        meters = build.meter_summary(row.site_name)[0]
        assert row.connection_month == str(meters.loc[row.customer_code, "first"]
                                           .to_period("M"))
        if row.source == "profile":
            assert row.customer_type == build.classify_meter(
                meters.loc[row.customer_code],
                build._commonest_category(roster, row.site_name))


def test_a_silent_meter_leaves_the_stock(rebuilt) -> None:
    from microgrid_expansion.demand import build_connection_curves as build

    _, _, status, _ = rebuilt
    for name in REFERENCE_SITES:
        meters, _, end = build.meter_summary(name)
        rows = status[status.site_name == name].set_index("customer_code")
        recorded = rows[rows.status.isin(("failed", "recording"))]
        silent = meters.loc[recorded.index, "last"] \
            <= end - pd.DateOffset(months=build.SILENT_MONTHS)
        assert (recorded.status == "failed").equals(silent.rename("status")), name
        for code, row in rows[rows.status == "failed"].iterrows():
            assert row.departure_month == str(pd.Period(row.last_reading_month, freq="M")
                                              + 1), code
        # Neither a customer whose meter never recorded nor a code that is no customer's
        # enters either record.
        for record in build.RECORDS:
            held = build.record_customers(status, record)
            assert not held.status.isin(("never_recorded", "not_a_customer")).any()
        # The extended record's stock at its end is what joined less what left.
        origin, last = build.record_span(roster := build.load_roster(), "extended", name)
        held = build.record_customers(status, "extended")
        held = held[(held.site_name == name) & held.customer_type.str.startswith("HH")]
        stock = build.household_stock(held, origin, last)
        gone = held.departure_month.map(lambda m: bool(m) and pd.Period(m, freq="M") <= last)
        assert stock[-1] == len(held) - int(gone.sum())


def test_the_tables_hold_the_extended_record(rebuilt) -> None:
    from microgrid_expansion.demand import build_connection_curves as build

    _, observed, status, _ = rebuilt
    assert build.DEFAULT_RECORD == "extended"
    unlisted = set(build.load_archive_customers().customer_code)
    for name in REFERENCE_SITES:
        end = build.meter_summary(name)[2]
        assert conn.curve_row(name, "estimate").last_month \
            == str(build.last_complete_month(end)), name
    held = build.record_customers(status, "extended")
    assert unlisted & set(held.customer_code), "the archive's own customers are left out"
    # What the record feeds is the stock, and the profile's types move it by little.
    for row in build.profile_bound(status).itertuples():
        assert row.most_moved == max(row.profiled_households, row.profiled_others)
        assert row.most_moved <= 0.05 * row.households, row.site_name


def test_the_census_type_column_is_believed_before_its_category(tmp_path) -> None:
    from microgrid_expansion.demand import build_connection_curves as build

    code, (kind, category) = build.CENSUS_CODE_COLUMN["Gbowele"], build.CENSUS_TYPE_COLUMNS
    assert kind.startswith("Type")
    sheet = pd.DataFrame({code: ["0001GBO", "0002GBO", "0003GBO", "0004GBO", "nobody"],
                          kind: ["HH1", None, "SME", "?", "HH2"],
                          category: ["HH2", "HH3", "HH1", None, "HH2"]})
    path = tmp_path / "census.xlsx"
    sheet.to_excel(path, sheet_name=build.CENSUS_SHEET, index=False)
    typed = build.read_census(path, "Gbowele")[0].set_index("customer_code").census_type
    assert typed.dropna().to_dict() == {"0001GBO": "HH1", "0002GBO": "HH3",
                                        "0003GBO": "PUE"}
    assert pd.isna(typed["0004GBO"]), "a type the census does not use leaves it untyped"


def test_a_reading_belongs_to_the_code_that_held_the_meter() -> None:
    from microgrid_expansion.demand.build_meter_archive import FROM_UTC, harmonise

    stamp = lambda h: pd.Timestamp("2026-01-01") + pd.Timedelta(hours=h)
    rows = [  # (hour, code as recorded, meter)
        (0, "test1", "M1"), (1, "TEST 3", "M1"),      # a bench meter's code: no one's
        (2, " 0074GBO", "M2"),                       # readable: the code at the time
        (3, "", "M3"), (4, "GBO", "M3"),             # unreadable: the meter's owner
        (5, "0193GBO", "BENCH"), (6, "", "BENCH"),   # a known customer on a bench meter
        (7, "0999GBO", "BENCH"), (9, "", "PLANT"),   # nobody known on one
        (8, "0005GBO", "M3"), (8, "", "M3"),         # a recovery never displaces a record
    ]
    frame = pd.DataFrame({"timestamp": [stamp(h) for h, _, _ in rows],
                          "code_as_recorded": [c for _, c, _ in rows],
                          "power_W": [float(i) for i in range(len(rows))],
                          "meter_serial": [m for _, _, m in rows]})
    owners = {"M1": "0074GBO", "M2": "0173GBO", "M3": "0005GBO", "BENCH": "0193GBO"}
    built = harmonise([frame], "GBO", owners, {"BENCH", "PLANT"}, frozenset({"0193GBO"}))
    got = {(t - FROM_UTC).hour: (c, p) for t, c, p in
           zip(built.timestamp, built.customer_code, built.power_W)}
    # The recorded reading of hour 8 is the tenth row, the recovered one the eleventh.
    assert got == {2: ("0074GBO", 2.0), 3: ("0005GBO", 3.0), 4: ("0005GBO", 4.0),
                   5: ("0193GBO", 5.0), 6: ("0193GBO", 6.0), 8: ("0005GBO", 9.0)}


def test_the_archive_holds_the_corrected_codes(rebuilt) -> None:
    _, _, status, _ = rebuilt
    rows = status.set_index("customer_code")
    # Recorded under "test1" in 2025, 0074GBO's own code starts in December 2025.
    assert rows.at["0074GBO", "connection_month"] == "2025-12"
    # A productive user of the roster recording on a bench meter is a customer.
    assert rows.at["0193GBO", "status"] == "recording"
    assert rows.at["0193GBO", "customer_type"] == "PUE"
    # The customers who now hold the meters of the test period no longer inherit their
    # months under a test code: each record starts with its own customer.
    for code in ("0074GBO", "0079GBO", "0169GBO", "0187GBO", "0190GBO", "0205GBO"):
        first = pd.Period(rows.at[code, "first_reading_month"], freq="M")
        assert first >= pd.Period(rows.at[code, "connection_month"], freq="M") - 1, code


def test_the_templates_declare_the_churches_their_record_holds(rebuilt) -> None:
    """A plan for a reference village carries its places of worship as the record has them."""
    from microgrid_expansion.demand import build_connection_curves as build
    from microgrid_expansion.demand.uses import CommunityCalibration
    from microgrid_expansion.settings import reference_plant

    _, _, status, _ = rebuilt
    held = build.record_customers(status, build.DEFAULT_RECORD)
    assert "place_of_worship" in CommunityCalibration.load().profiles.index
    for name in REFERENCE_SITES:
        last = pd.Period(conn.curve_row(name, "estimate").last_month, freq="M")
        churches = held[(held.site_name == name) & (held.customer_type == "CHU")]
        on_grid = churches[churches.departure_month.map(
            lambda m: not m or pd.Period(m, freq="M") > last)]
        assert (get_site(name).community_mix or {}).get("place_of_worship") == len(on_grid)
        # Connected before the plan's year 0, so there from its first month.
        first = pd.Period(f"{reference_plant(name).base_year}-01", freq="M")
        assert (on_grid.connection_month.map(lambda m: pd.Period(m, freq="M")) < first).all()


def test_the_active_households_are_counted_over_the_observed_ones(rebuilt) -> None:
    from microgrid_expansion.demand import build_connection_curves as build

    _, _, status, _ = rebuilt
    roster = build.load_roster()
    for name in REFERENCE_SITES:
        row = build.active_check(status, roster, build.DEFAULT_RECORD, name)
        # A household without any reading in the month leaves both sides.
        assert row["expected_observed"] <= row["expected"]
        assert row["unobserved"] < row["households"]
        assert row["within"] == (abs(row["metered"] - row["expected_observed"])
                                 <= 2.0 * row["sd_observed"])
        assert row["within"], (name, row)                     # S2-A5 on the shipped record
        if row["unobserved"] == 0:
            assert row["expected"] == pytest.approx(row["expected_observed"])


# --------------------------------------------------------------------- the keys
def test_the_pool_key_covers_what_decides_the_pool() -> None:
    from microgrid_expansion.scenarios.demand_paths import _pool_key

    site = get_site("Samionta")
    curve = conn.load_curves()["low"]
    schedule = ConnectionSchedule.greenfield(site, curve)
    key = _pool_key(site, "central", 12, 2025, 0, schedule)

    # One household more from village month 5 on, inside the year the key covers.
    more = ConnectionSchedule(schedule.categories, schedule.census,
                              tuple(r if a < 5 else (r[0] + 1, *r[1:])
                                    for a, r in enumerate(schedule.stock)))
    assert _pool_key(site, "central", 12, 2025, 0, more) != key, "one household more"
    edited = dataclasses.replace(site, community_mix={"place_of_worship": 3})
    assert _pool_key(edited, "central", 12, 2025, 0, schedule) != key, "the description"
    assert _pool_key(site, "central", 12, 2024, 0, schedule) != key, "the year"
    assert _pool_key(site, "central", 12, 2025, 1, schedule) != key, "the seed"
    renamed = ConnectionSchedule(schedule.categories, schedule.census, schedule.stock,
                                 label="high")
    assert _pool_key(site, "central", 12, 2025, 0, renamed) == key, (
        "the trajectory's name decides nothing its schedule does not")


def test_the_instance_key_covers_the_schedule() -> None:
    from microgrid_expansion.instances import _cache_key, _connection_fingerprint

    site = get_site("Samionta")
    assert _connection_fingerprint(None, 12) == ""
    assert _connection_fingerprint(ConnectionSchedule.whole_census(site), 12) == ""
    low = ConnectionSchedule.greenfield(site, conn.load_curves()["low"])
    high = ConnectionSchedule.greenfield(site, conn.load_curves()["high"])
    keys = {_cache_key("Samionta", 2025, "central", 12, 0, "lfp",
                       connection=_connection_fingerprint(s, 12))
            for s in (None, ConnectionSchedule.whole_census(site), low, high)}
    assert len(keys) == 3, "whole census twice, then one key per schedule"


# ------------------------------------------------------------------ the paths
def test_the_connection_draw_leaves_the_stream_alone() -> None:
    from microgrid_expansion.config import ModelConfig
    from microgrid_expansion.scenarios import mc_sampler
    from microgrid_expansion.scenarios.uncertainty_space import DemandAxis, UncertaintySpace

    cfg = ModelConfig(n_mc_paths=40, seed=3)
    census = mc_sampler.sample_paths(
        cfg, UncertaintySpace(demand=DemandAxis(connection_mode="census")))
    drawn = mc_sampler.sample_paths(cfg, UncertaintySpace())
    paired = mc_sampler.sample_paths(
        cfg, UncertaintySpace(demand=DemandAxis(connection_mode="progressive",
                                                connection_pairing="paired")))
    strip = lambda paths: [[{k: v for k, v in s.items() if k != "connection"} for s in p]
                           for p in paths]
    assert strip(census) == strip(drawn) == strip(paired)
    assert all(s["connection"] == "census" for p in census for s in p)
    for path in drawn:
        assert len({s["connection"] for s in path}) == 1
    assert {p[0]["connection"] for p in drawn} == set(conn.TRAJECTORIES)
    assert all(s["connection"] == conn.PAIRED_WITH_GROWTH[s["trajectory"]]
               for p in paired for s in p)


# ---------------------------------------------------------------- the settings
def test_connection_settings_round_trip(tmp_path) -> None:
    from microgrid_expansion.settings import ConnectionWeights, ProjectSettings, \
        default_settings

    settings = default_settings()
    settings.connection.mode = "progressive"
    settings.connection.trajectory = "high"
    settings.connection.weights = ConnectionWeights(0.5, 0.25, 0.25)
    settings.connection.pairing = "paired"
    settings.connection.high_plateau = "census"
    settings.connection.brownfield_bracket = "between_villages"
    reloaded = ProjectSettings.load(settings.save(tmp_path / "project.yaml"))
    assert reloaded == settings
    assert isinstance(reloaded.connection.weights, ConnectionWeights)

    for field, value in (("mode", "partial"), ("trajectory", "slow"),
                         ("pairing", "joined"), ("high_plateau", "estimate"),
                         ("brownfield_bracket", "neighbour")):
        wrong = default_settings()
        setattr(wrong.connection, field, value)
        with pytest.raises(ValueError, match=f"connection.{field}"):
            wrong.validate()
    wrong = default_settings()
    wrong.connection.weights = ConnectionWeights(0.5, 0.5, 0.5)
    with pytest.raises(ValueError, match="sum to one"):
        wrong.validate()


def test_the_defaults_are_the_progressive_model() -> None:
    """Switched together, so that no default runs half of one model and half of another."""
    from microgrid_expansion.config import ModelConfig
    from microgrid_expansion.scenarios.uncertainty_space import UncertaintySpace
    from microgrid_expansion.settings import default_settings

    settings, cfg = default_settings(), ModelConfig()
    assert settings.connection.mode == UncertaintySpace().demand.connection_mode \
        == "progressive"
    assert (cfg.tree_mode, cfg.node_year, cfg.centre_features) == ("persistent", "last",
                                                                   True)
    assert (cfg.regime_branches, cfg.fan()) == (3, (1, 1, 2, 2, 2)), \
        "a fan within each regime, as the formulation's tree has it"
    assert cfg.maturity_months == settings.maturity_months == 0, "a site being energised"
    with pytest.raises(ValueError, match="'both' is not built"):
        ModelConfig(node_year="both").validate()


def test_the_certified_year_is_the_root_s() -> None:
    import inspect

    from microgrid_expansion.config import ModelConfig
    from microgrid_expansion.exact import certify
    from microgrid_expansion.ui import engine

    # The root's span is the plan's years 0 to 4: its first year, or its last.
    assert certify.certified_year(0, "first") == (0, 0)
    assert certify.certified_year(0, "last") == (4, 48)
    assert certify.certified_year(31) == (4, 31 + 48), "the default is the node year's"
    assert certify.certified_year(7, "last") == (ModelConfig().demand_year(0),
                                                 7 + 12 * ModelConfig().demand_year(0))
    # Both callers take it from the same place.
    for function in (certify.main, engine.size_site):
        assert "certified_year(" in inspect.getsource(function)


def test_the_network_loss_has_a_provenance() -> None:
    from microgrid_expansion.config import ModelConfig
    from microgrid_expansion.settings import Provenance, default_settings

    settings = default_settings()
    provenance = settings.infrastructure.network_loss_provenance
    assert isinstance(provenance, Provenance) and provenance.source
    assert "infrastructure.network_loss_provenance" in dict(settings.unverified())
    assert ModelConfig().network_loss_fraction \
        == settings.infrastructure.network_loss_fraction == 0.13


# ---------------------------------------------------------------- the interface
def test_the_interface_offers_the_connection_trajectory() -> None:
    from microgrid_expansion.settings import default_settings
    from microgrid_expansion.ui import schema

    for lang in ("en", "fr"):
        fields = {f["path"]: f for group in schema.describe(lang=lang)
                  for f in group["fields"]}
        field = fields["connection.trajectory"]
        assert field["choices"] == list(conn.TRAJECTORIES) and field["value"] == "central"
        assert field["label"] != "f.connection_trajectory" and field["hint"], lang
    settings = schema.apply(default_settings(), {"connection.trajectory": "high"})
    assert settings.connection.trajectory == "high"
    with pytest.raises(ValueError, match="connection.trajectory"):
        schema.apply(default_settings(), {"connection.trajectory": "fast"})
