"""Uses a village has that no calibration of ours measured.

The four household archetypes and the six activity classes cover what the two reference
villages contain. A school, a health centre, a place of worship and the street lighting are
none of those, and nor is a cold store or an internet kiosk. These tests hold the mechanism
that lets such a use be declared, and the two things the mechanism got wrong the first time:
a cycle longer than the window it is confined to, and a certain load put through a draw.
"""
from __future__ import annotations

import numpy as np
import pytest

from microgrid_expansion.demand.uses import (
    COMMUNITY_CATALOGUE, SELF_CONSUMPTION_CATALOGUE, CommunityCalibration, Device, UseSpec,
    community_catalogue, dusk_to_dawn, self_consumption_catalogue)


# ------------------------------------------------------------------ describing a use
def test_a_device_refuses_to_run_longer_than_its_window() -> None:
    """Said when the use is described, not when a sizing is already an hour in."""
    device = Device(name="pump", power_w=750, func_time_min=600,
                    window_start_min=0, window_end_min=60)
    with pytest.raises(ValueError, match="60 minutes wide"):
        device.validate()


def test_a_window_may_cross_midnight() -> None:
    """Which is how a night load is written, and the commonest community one is."""
    lamp = Device(name="lamp", power_w=60, func_time_min=690,
                  window_start_min=18 * 60 + 30, window_end_min=6 * 60)
    assert lamp.window_width_min == pytest.approx(690.0)
    lamp.validate()
    # Reaching the simulator the end is unwrapped past the day, as a meter's would be.
    assert lamp.as_row()["w1_end"] == 18 * 60 + 30 + 690


def test_a_use_survives_being_written_down_and_read_back() -> None:
    use = UseSpec(key="cold_store", label="Cold store", category="productive",
                  devices=(Device(name="compressor", power_w=900, number=2,
                                  func_time_min=480, func_cycle_min=20),))
    assert UseSpec.from_record(use.to_record()) == use
    assert use.daily_kwh == pytest.approx(900 * 2 * 480 / 60000)
    assert use.peak_w == pytest.approx(1800)


# ------------------------------------------------------------------ what is certain
def test_a_load_that_fills_its_window_every_day_is_certain() -> None:
    """And a certain load is placed, not drawn.

    Put through the appliance library, a street lamp came back with barely half the
    kilowatt-hours it burns: the library scatters a duty it was told was stochastic, and a
    lamp has nothing to scatter.
    """
    lamp = dusk_to_dawn(8, 60.0, source="test")
    assert lamp.devices[0].is_constant
    # A welding set worked three days in ten is not certain, and must be drawn.
    welder = Device(name="welder", power_w=4000, func_time_min=120,
                    window_start_min=480, window_end_min=1080, occasional_use=0.4)
    assert not welder.is_constant


def test_street_lighting_delivers_exactly_what_its_lamps_draw() -> None:
    from microgrid_expansion.demand.generator import _declared_use_minutes, _to_hourly_kw

    lamps = dusk_to_dawn(8, 60.0, source="test")
    minutes = _declared_use_minutes({lamps: 1}, 2025, 6, 30, seed=11)
    assert minutes is not None
    hourly = _to_hourly_kw(minutes)
    assert hourly.sum() == pytest.approx(lamps.daily_kwh * 30, rel=1e-6)
    assert hourly.max() == pytest.approx(lamps.peak_w / 1000.0, rel=1e-6)
    # And it falls at night, on both sides of midnight.
    day = hourly.reshape(-1, 24).mean(axis=0)
    assert day[0] > 0 and day[23] > 0, "the lamp does not cross midnight"
    assert day[12] == 0, "the lamp burns at noon"


def test_a_cycle_is_bounded_by_the_window_segment_it_must_fit_in() -> None:
    """A dusk-to-dawn window reaches the simulator as two segments, 330 and 360 minutes.

    A cycle longer than either can never be placed and the lamp silently never lit. Bounded
    by the longer, only the small hours lit. It is the shorter that binds.
    """
    import pandas as pd

    from microgrid_expansion.demand.generator import _appliance_spec

    lamp = dusk_to_dawn(1, 60.0, source="test").devices[0]
    spec = _appliance_spec(pd.Series(lamp.as_row(), name="lamp"))
    assert spec is not None
    segments = [spec["window"][1] - spec["window"][0]]
    if spec.get("window_2"):
        segments.append(spec["window_2"][1] - spec["window_2"][0])
    assert len(segments) == 2, "the night window did not split at midnight"
    assert spec["func_cycle"] <= min(segments)


# ------------------------------------------------------------------ the catalogue
def test_the_community_catalogue_names_three_buildings_and_invents_none() -> None:
    """All three are known to exist and to no figure, and must say so.

    A plant sized on invented occupancy is not improved by the confidence with which it was
    sized, and this project's rule is that no number enters without a record behind it.
    """
    assert set(COMMUNITY_CATALOGUE) == {"school", "health_centre", "place_of_worship"}
    empty = community_catalogue()
    assert all(value is None for value in empty.values()), (
        "the catalogue supplied a default nobody measured")


def test_self_consumption_is_its_own_catalogue_and_carries_the_lighting() -> None:
    """Street lighting is the one load in either catalogue that two numbers settle."""
    assert set(SELF_CONSUMPTION_CATALOGUE) == {"public_lighting", "powerhouse"}
    assert all(entry["billable"] is False
               for entry in SELF_CONSUMPTION_CATALOGUE.values()), (
        "self consumption is what nobody is billed for")
    # The two differ in where they sit, which is what decides whether a loss reaches them.
    assert SELF_CONSUMPTION_CATALOGUE["public_lighting"]["on_network"] is True
    assert SELF_CONSUMPTION_CATALOGUE["powerhouse"]["on_network"] is False

    empty = self_consumption_catalogue()
    assert all(value is None for value in empty.values())
    filled = self_consumption_catalogue(lamps=8, watts=60.0, source="test")
    assert filled["public_lighting"] is not None
    # The powerhouse is measured, but what it has is a shape rather than a device list, so
    # there is no specification to return for it either.
    assert filled["powerhouse"] is None


def test_the_place_of_worship_is_the_one_class_the_meters_could_speak_to() -> None:
    """Its day is measured; the school's cannot be, and the reason is worth holding.

    One school is metered across the two reference villages and its relay has never closed:
    it is equipped, not supplied. There is no load there to calibrate.
    """
    calibration = CommunityCalibration.load()
    if calibration is None:
        pytest.skip("the community table has not been built in this checkout")
    assert "place_of_worship" in calibration.classes
    assert "school" not in calibration.classes
    row = calibration.profiles.loc["place_of_worship"]
    assert 0.1 < float(row["kwh_per_day"]) < 5.0
    assert int(row["n_meters"]) >= 3
    hours = [h for h in range(24) if h in calibration.profiles.columns]
    shape = calibration.profiles.loc["place_of_worship", hours].astype(float)
    assert shape.idxmax() in range(17, 22), "a place of worship peaks in the evening"


# ------------------------------------------------------------- who pays for a use
def test_the_street_lighting_is_served_and_sold_to_nobody() -> None:
    """A use says whether a customer is invoiced for it, and the lighting says no.

    The distinction decides the revenue. A village of twenty households with eight street
    lamps delivers two fifths of its kilowatt-hours to the lamps, and a tariff collected on
    everything delivered would invoice the commune's lighting at the household rate.
    """
    lighting = dusk_to_dawn(8, 60.0, source="test")
    assert lighting.billable is False
    assert lighting.category == "self_consumption"
    # Everything else is a metered connection, and a use declared without an opinion is one.
    assert UseSpec(key="mill", label="Mill", category="productive",
                   devices=(Device(name="motor", power_w=2200, func_time_min=240),)).billable


def test_a_use_written_before_the_distinction_existed_reads_as_invoiced() -> None:
    """Which is what it was: a site saved earlier declared nothing but customers."""
    record = {"key": "kiosk", "label": "Kiosk", "category": "productive",
              "devices": [{"name": "router", "power_w": 12.0, "func_time_min": 900.0}]}
    assert UseSpec.from_record(record).billable is True
    # And the flag survives the round trip a saved site makes.
    lighting = dusk_to_dawn(8, 60.0, source="test")
    assert UseSpec.from_record(lighting.to_record()) == lighting

def test_self_consumption_cannot_be_billed_to_anybody() -> None:
    """Said when the use is described. A use somebody pays for is a customer."""
    use = UseSpec(key="plant_room", label="Plant room", category="self_consumption",
                  billable=True,
                  devices=(Device(name="air conditioner", power_w=900,
                                  func_time_min=600),))
    with pytest.raises(ValueError, match="nobody is billed for"):
        use.validate()


def test_the_street_lighting_is_on_the_network_and_the_plant_room_is_not() -> None:
    """The two are both unbilled and they are not the same load.

    A distribution loss reaches whatever travels the conductor. The village's lamps do; the
    air conditioning of the room the inverters stand in draws from the busbar beside them
    and carries no loss at all, so applying one share to both would charge a loss to a load
    that never crossed the network.
    """
    assert dusk_to_dawn(8, 60.0, source="test").on_network is True
    room = UseSpec(key="plant_room", label="Plant room", category="self_consumption",
                   billable=False, on_network=False,
                   devices=(Device(name="router", power_w=10, func_time_min=1440,
                                   func_cycle_min=1440),))
    room.validate()
    # And it survives being written down, as the billing flag does.
    assert UseSpec.from_record(room.to_record()) == room
    # A record written before the distinction existed described a load on the network,
    # which is what every load but this one is.
    assert UseSpec.from_record({"key": "k", "label": "l", "category": "community",
                                "devices": [{"name": "d", "power_w": 10.0,
                                             "func_time_min": 60.0}]}).on_network is True


def test_a_described_class_replaces_its_measured_shape_rather_than_adding_to_it() -> None:
    """Both are offered on purpose, and they are alternatives.

    A measured shape is what a village with none of its own needs; a village that knows its
    own place of worship is better evidence than five meters in two other villages. Taken
    together they counted one building twice.
    """
    from microgrid_expansion.demand.generator import _measured_groups
    from microgrid_expansion.sites import Site

    if CommunityCalibration.load() is None:
        pytest.skip("the community table has not been built in this checkout")

    plain = Site(name="t", census={"HH1": 1},
                 community_mix={"place_of_worship": 2}, origin="user")
    groups = _measured_groups(plain)
    assert [g[0] for g in groups] == [{"place_of_worship": 2}], (
        "the measured shape should be used")

    own = UseSpec(key="place_of_worship", label="Place of worship", category="community",
                  devices=(Device(name="lamp", power_w=20, number=6, func_time_min=240),))
    described = Site(name="t", census={"HH1": 1},
                     community_mix={"place_of_worship": 2},
                     declared_uses=(own,), origin="user")
    assert _measured_groups(described) == [], (
        "a described class must not also carry its measured shape")


def test_a_measured_class_is_grouped_by_who_pays_and_where_it_sits() -> None:
    """The grouping is read off the calibration table, not held as a list of keys here.

    A place of worship is a customer out on the network; the plant's own supply is neither,
    and a distribution loss must not reach it. Routed together they would have billed the
    inverter room's air conditioning at the household tariff and charged it a network loss
    it never incurred.
    """
    from microgrid_expansion.demand.generator import _measured_groups
    from microgrid_expansion.sites import Site

    calibration = CommunityCalibration.load()
    if calibration is None or "powerhouse" not in calibration.classes:
        pytest.skip("the table in this checkout carries no measured powerhouse")

    site = Site(name="t", census={"HH1": 1},
                community_mix={"place_of_worship": 1},
                self_mix={"powerhouse": 1}, origin="user")
    groups = {tuple(g[0]): (g[2], g[3]) for g in _measured_groups(site)}
    assert groups[("place_of_worship",)] == (True, True)
    assert groups[("powerhouse",)] == (False, False)


# ------------------------------------------------- what the settings actually change
def _village_with_its_own_supply():
    """Samionta's weather and a handful of households, with the two unbilled loads."""
    import dataclasses

    from microgrid_expansion.sites import get_site

    base = get_site("Samionta")
    return dataclasses.replace(
        base, census={"HH1": 6, "HH2": 4},
        self_mix={"public_lighting": 1, "powerhouse": 1},
        declared_uses=(dusk_to_dawn(6, 60.0, source="test"),),
        productive_mix=None, productive_units=None, community_mix=None)


def test_a_network_loss_changes_the_plant_load_and_not_the_energy_sold() -> None:
    """The one check that the wiring is not merely present but connected.

    Every other test of this reads the source: whether a setting is named, whether it is
    reachable, whether the bridge to the tree carries it. None of them notices a loss
    plumbed as far as the instance and then dropped, and a mutation proved it -- tearing the
    loss out of ``build_site_year`` left the whole suite green. So this one builds the same
    village twice, under two losses, and looks at what comes out.

    Three things must hold, and each is a separate claim. The plant must produce more. Every
    kilowatt-hour of that excess must be unbilled, because a network loss reaches no meter.
    And the energy a customer is invoiced for must not move at all: a loss is not a smaller
    sale, it is the same sale with more generated behind it.
    """
    import pytest as _pytest

    from microgrid_expansion.instances import build_site_year
    from microgrid_expansion.paths import IRRADIANCE_DIR

    site = _village_with_its_own_supply()
    if not site.irradiance_file or not (IRRADIANCE_DIR / site.irradiance_file).exists():
        _pytest.skip("the reference weather series is not in this checkout")

    loss = 0.15
    lossless = build_site_year(site, 2025, maturity_months=12, use_cache=False,
                               network_loss_fraction=0.0)
    lossy = build_site_year(site, 2025, maturity_months=12, use_cache=False,
                            network_loss_fraction=loss)

    extra = lossy.demand_kwh - lossless.demand_kwh
    assert extra > 0, "the loss did not reach the demand the plant must produce"
    assert extra == pytest.approx(lossy.unbilled_kwh - lossless.unbilled_kwh), (
        "a network loss reaches no meter; all of it must be unbilled")
    assert lossy.billable_kwh == pytest.approx(lossless.billable_kwh, rel=1e-9), (
        "the loss moved what a customer is billed for")

    # And the plant's own supply carried none of it: applied to everything, the excess would
    # be the full share of the load, and it is strictly less.
    assert extra < lossless.demand_kwh * loss / (1.0 - loss) * 0.999, (
        "the loss was charged to the powerhouse, which never crosses the network")


def test_declaring_the_unbilled_loads_is_what_moves_the_billable_share() -> None:
    """The share is a consequence of what the village declared, never a parameter.

    A village that declares neither street lighting nor a plant room sells everything it is
    served, and its share is exactly one -- not approximately one. One that declares both
    sells distinctly less, and the difference is a quantity rather than a fraction, which is
    the whole reason it is carried as load.
    """
    import dataclasses

    import pytest as _pytest

    from microgrid_expansion.instances import build_site_year
    from microgrid_expansion.paths import IRRADIANCE_DIR

    site = _village_with_its_own_supply()
    if not site.irradiance_file or not (IRRADIANCE_DIR / site.irradiance_file).exists():
        _pytest.skip("the reference weather series is not in this checkout")

    bare = dataclasses.replace(site, self_mix=None, declared_uses=None)
    plain = build_site_year(bare, 2025, maturity_months=12, use_cache=False)
    assert plain.unbilled_kwh == 0.0
    assert plain.billable_fraction == 1.0

    declared = build_site_year(site, 2025, maturity_months=12, use_cache=False)
    assert declared.billable_fraction < 0.95, (
        "declaring the street lighting and the plant room changed nothing")
    assert declared.unbilled_kwh > plain.unbilled_kwh
