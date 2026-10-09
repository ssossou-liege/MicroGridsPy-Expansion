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
    COMMUNITY_CATALOGUE, CommunityCalibration, Device, UseSpec, community_catalogue,
    dusk_to_dawn)


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
def test_the_catalogue_names_four_uses_and_invents_none() -> None:
    """Three of the four are known to exist and to no figure, and must say so.

    A plant sized on invented occupancy is not improved by the confidence with which it was
    sized, and this project's rule is that no number enters without a record behind it.
    """
    assert set(COMMUNITY_CATALOGUE) == {"school", "health_centre", "place_of_worship",
                                        "public_lighting"}
    empty = community_catalogue()
    assert all(value is None for value in empty.values()), (
        "the catalogue supplied a default nobody measured")
    # Street lighting is the one it can carry, and only once given lamps and a rating.
    filled = community_catalogue(lamps=8, watts=60.0, source="test")
    assert filled["public_lighting"] is not None
    assert filled["school"] is None


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
