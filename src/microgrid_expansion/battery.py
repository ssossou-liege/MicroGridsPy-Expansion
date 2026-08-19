"""Temperature behaviour of the storage, by chemistry, defined once for the whole model.

Two quantities of the formulation depend on ambient temperature: the usable-capacity
factor, which derates the upper energy bound, and the self-discharge rate. They appear on
both sides of the certificate — the resource layer supplies them as parameters of the
cost-optimal problem, and the controller reacts to them when it decides — so a single
definition is a correctness requirement, not a convenience. Two definitions of the same
ceiling put the simulated trajectory outside the feasible set the bound is computed over,
and the certificate silently stops meaning anything.

The curves differ by chemistry, and materially: a lead-acid pack loses roughly a tenth of
its capacity by 15 degrees and gains a little in the heat, whereas a lithium-iron-phosphate
pack is nearly flat across the whole temperate band and is limited in heat by its
management system rather than by available capacity. Their self-discharge differs by more
than a factor of two. The chemistry is therefore selected explicitly rather than inherited
from whichever implementation a routine happened to be ported from.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

#: Reference temperature of the manufacturers' ratings [degC].
T_REFERENCE_C = 25.0


@dataclass(frozen=True)
class Chemistry:
    """Temperature response of one storage chemistry.

    ``capacity_coefficients`` are those of a quadratic in the ambient temperature giving
    the fraction of nameplate energy the pack can hold; ``self_discharge_monthly`` is the
    fraction of the stored energy lost per month at the reference temperature, and
    ``self_discharge_doubling_k`` the temperature rise that doubles it.
    """

    name: str
    capacity_coefficients: tuple[float, float, float]
    capacity_cap: float
    self_discharge_monthly: float
    self_discharge_doubling_k: float = 10.0
    #: Temperature below which the pack must not be charged, if any [degC].
    charge_cutoff_c: float | None = None
    description: str = ""

    def usable_fraction(self, t_amb_c: np.ndarray | float) -> np.ndarray:
        """Fraction of nameplate energy available at a given temperature [-]."""
        t = np.asarray(t_amb_c, dtype=float)
        a, b, c = self.capacity_coefficients
        return np.clip(a + b * t + c * t ** 2, 0.1, self.capacity_cap)

    def self_discharge_fraction(self, t_amb_c: np.ndarray | float,
                                timestep_h: float = 1.0) -> np.ndarray:
        """Fraction of the stored energy lost over one step [-]."""
        t = np.asarray(t_amb_c, dtype=float)
        monthly = self.self_discharge_monthly * 2.0 ** (
            (t - T_REFERENCE_C) / self.self_discharge_doubling_k)
        return np.clip(monthly * timestep_h / (30.0 * 24.0), 0.0, 1.0)

    def self_discharge_kwh(self, capacity_kwh: float, t_amb_c: np.ndarray | float,
                           timestep_h: float = 1.0) -> np.ndarray:
        """Energy lost to self-discharge over one step [kWh]."""
        return capacity_kwh * self.self_discharge_fraction(t_amb_c, timestep_h)

    def can_charge(self, t_amb_c: np.ndarray | float) -> np.ndarray:
        """Whether charging is permitted at a given temperature."""
        t = np.asarray(t_amb_c, dtype=float)
        if self.charge_cutoff_c is None:
            return np.ones_like(t, dtype=bool)
        return t >= self.charge_cutoff_c


#: Lithium iron phosphate — the chemistry of the packs this study sizes.
#: Capacity is essentially flat from about 15 degC upwards and falls away in the cold;
#: the quadratic reproduces roughly 0.85 at 0 degC, 0.95 at 10, and the nameplate from 20.
#: Charging below freezing is prohibited by the management system, which never binds at the
#: study sites but must not be silently assumed away elsewhere.
LFP = Chemistry(
    name="lfp",
    capacity_coefficients=(0.848, 0.01206, -0.000226),
    capacity_cap=1.0,
    self_discharge_monthly=0.025,
    charge_cutoff_c=0.0,
    description="lithium iron phosphate",
)

#: Lead-acid, after IEEE 485 Table 1. Retained because the reference controller assumes it,
#: so reproducing that controller's behaviour requires it; it is not the study's chemistry.
LEAD_ACID = Chemistry(
    name="lead_acid",
    capacity_coefficients=(0.711009126, 0.0138667895, -0.0000933332591),
    capacity_cap=1.0,
    self_discharge_monthly=0.05,
    charge_cutoff_c=None,
    description="lead-acid, IEEE 485 Table 1",
)

CHEMISTRIES: dict[str, Chemistry] = {c.name: c for c in (LFP, LEAD_ACID)}

#: The chemistry used when none is named. It matches the pack described in the
#: configuration; changing it changes the storage ceiling everywhere at once.
DEFAULT_CHEMISTRY = LFP


def get_chemistry(chemistry: str | Chemistry | None = None) -> Chemistry:
    """Resolve a chemistry by name, passing a :class:`Chemistry` through unchanged."""
    if chemistry is None:
        return DEFAULT_CHEMISTRY
    if isinstance(chemistry, Chemistry):
        return chemistry
    try:
        return CHEMISTRIES[str(chemistry).lower()]
    except KeyError:
        raise KeyError(
            f"unknown battery chemistry {chemistry!r}; "
            f"available: {sorted(CHEMISTRIES)}"
        ) from None


# --- convenience wrappers on the default chemistry ---------------------------
def usable_fraction(t_amb_c, chemistry: str | Chemistry | None = None):
    """Fraction of nameplate energy available [-]."""
    return get_chemistry(chemistry).usable_fraction(t_amb_c)


def self_discharge_fraction(t_amb_c, chemistry: str | Chemistry | None = None,
                            timestep_h: float = 1.0):
    """Fraction of the stored energy lost over one step [-]."""
    return get_chemistry(chemistry).self_discharge_fraction(t_amb_c, timestep_h)


def self_discharge_kwh(capacity_kwh: float, t_amb_c,
                       chemistry: str | Chemistry | None = None,
                       timestep_h: float = 1.0):
    """Energy lost to self-discharge over one step [kWh]."""
    return get_chemistry(chemistry).self_discharge_kwh(capacity_kwh, t_amb_c, timestep_h)
