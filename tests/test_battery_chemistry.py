"""Storage chemistry: selectable, and consistent across every layer that uses it.

The usable-capacity ceiling appears on both sides of the certificate — the controller
reacts to it, and the lower bound is computed over it — so the two must always resolve to
the same curve for the same chemistry. They previously did not, and Assumption 1 failed as
a result; these tests keep that from recurring, and keep the default matching the pack the
configuration actually specifies.
"""
from __future__ import annotations

import numpy as np
import pytest

from microgrid_expansion import config
from microgrid_expansion.battery import (
    CHEMISTRIES,
    DEFAULT_CHEMISTRY,
    LEAD_ACID,
    LFP,
    get_chemistry,
    self_discharge_fraction,
    usable_fraction,
)


def test_the_default_chemistry_matches_the_configured_pack():
    """The configuration specifies a lithium-iron-phosphate pack; the default must agree."""
    assert config.BATTERY_CHEMISTRY == "lfp"
    assert DEFAULT_CHEMISTRY is LFP
    assert get_chemistry() is LFP


def test_lithium_iron_phosphate_loses_capacity_in_cold_and_in_heat():
    """Flat across the temperate band, falling at both ends — the LFP behaviour."""
    cold = float(LFP.usable_fraction(0.0))
    mild = float(LFP.usable_fraction(25.0))
    warm = float(LFP.usable_fraction(30.0))
    hot = float(LFP.usable_fraction(45.0))
    assert cold < 0.90                      # roughly 85 % of nameplate at freezing
    assert mild == pytest.approx(1.0, abs=0.01)
    assert warm == pytest.approx(1.0, abs=0.01)
    assert hot < mild                       # the management system derates in heat
    assert 0.90 < hot < 0.98


def test_lead_acid_follows_the_ieee_curve_and_rises_with_temperature():
    """Retained for reproducing the reference controller, not for this study's pack."""
    assert float(LEAD_ACID.usable_fraction(15.0)) < float(LEAD_ACID.usable_fraction(25.0))
    assert float(LEAD_ACID.usable_fraction(40.0)) == pytest.approx(1.0, abs=1e-9)
    assert float(LEAD_ACID.usable_fraction(0.0)) < float(LFP.usable_fraction(0.0))


def test_the_two_chemistries_differ_where_it_matters():
    """If they agreed, selecting between them would be pointless."""
    temperatures = np.linspace(10.0, 40.0, 30)
    difference = np.abs(LFP.usable_fraction(temperatures)
                        - LEAD_ACID.usable_fraction(temperatures))
    assert difference.max() > 0.05


def test_lithium_self_discharges_more_slowly_than_lead():
    assert LFP.self_discharge_monthly < LEAD_ACID.self_discharge_monthly
    at_25 = float(LFP.self_discharge_fraction(25.0))
    at_35 = float(LFP.self_discharge_fraction(35.0))
    assert at_35 == pytest.approx(2.0 * at_25, rel=1e-9)     # doubles every ten degrees
    assert 0.0 < at_25 < 1.0


def test_only_lithium_forbids_charging_below_freezing():
    assert LFP.charge_cutoff_c == 0.0
    assert not bool(LFP.can_charge(-5.0))
    assert bool(LFP.can_charge(20.0))
    assert LEAD_ACID.charge_cutoff_c is None
    assert bool(LEAD_ACID.can_charge(-5.0))


def test_an_unknown_chemistry_is_rejected_everywhere():
    with pytest.raises(KeyError, match="unknown battery chemistry"):
        get_chemistry("nickel-cadmium")
    with pytest.raises(ValueError, match="battery_chemistry"):
        config.ModelConfig(battery_chemistry="nickel-cadmium").validate()


def test_a_chemistry_object_passes_through_unchanged():
    assert get_chemistry(LEAD_ACID) is LEAD_ACID
    assert get_chemistry("LEAD_ACID") is LEAD_ACID          # name matching is insensitive


@pytest.mark.parametrize("chemistry", sorted(CHEMISTRIES))
def test_resource_and_controller_resolve_the_same_curve(chemistry):
    """The failure this guards against broke Assumption 1 on 1.5 % of hours."""
    from microgrid_expansion.exact.simulator import BatteryModel
    from microgrid_expansion.resource import battery_usable_fraction

    temperatures = np.linspace(5.0, 45.0, 50)
    reference = usable_fraction(temperatures, chemistry)
    assert np.allclose(battery_usable_fraction(temperatures, chemistry), reference)
    assert np.allclose(BatteryModel(chemistry=chemistry).usable_fraction(temperatures),
                       reference)


@pytest.mark.parametrize("chemistry", sorted(CHEMISTRIES))
def test_self_discharge_is_consistent_across_layers(chemistry):
    from microgrid_expansion.exact.simulator import BatteryModel
    from microgrid_expansion.resource import battery_self_discharge

    temperatures = np.linspace(5.0, 45.0, 50)
    reference = self_discharge_fraction(temperatures, chemistry)
    assert np.allclose(battery_self_discharge(temperatures, chemistry), reference)
    # the simulator works in energy; dividing by capacity must recover the fraction
    per_kwh = BatteryModel(chemistry=chemistry).self_discharge(1.0, temperatures)
    assert np.allclose(per_kwh, reference)


def test_the_instance_cache_distinguishes_chemistries():
    """A cached instance from another chemistry would describe a different battery."""
    from microgrid_expansion.instances import _cache_key

    lfp = _cache_key("Samionta", 2025, "centrale", 12, 0, "lfp")
    lead = _cache_key("Samionta", 2025, "centrale", 12, 0, "lead_acid")
    assert lfp != lead
