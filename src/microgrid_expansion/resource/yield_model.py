"""From measured irradiance to specific yield and battery temperature effects.

The photovoltaic specific yield :math:`Y` [kW per kW installed] is obtained from the
global horizontal irradiance through a cell-temperature model and the module's temperature
coefficient, then derated for the losses that no cell model represents -- soiling, wiring,
mismatch and conversion. The same ambient temperature drives the two battery quantities
the storage constraints need: the usable-capacity factor, which derates the upper energy
bound in the cold and in the heat, and the self-discharge rate, which grows with
temperature.

Ambient temperature is a required input of the physics. The irradiance series currently
committed for the reference site carries irradiance alone, although the download it comes
from also requests two-metre temperature and wind: until that series is regenerated with
those variables, an isothermal approximation may be requested explicitly, and the result
is flagged as provisional rather than silently passed off as measured.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..sites import Site

#: Irradiance at standard test conditions [W/m2].
G_STC = 1000.0
#: Cell temperature at standard test conditions [degC].
T_STC = 25.0


@dataclass(frozen=True)
class ModuleSpec:
    """Photovoltaic module characteristics entering the yield model.

    Defaults describe a crystalline-silicon module in an open-rack installation, which is
    what the reference sites use. ``u0`` and ``u1`` are the Faiman heat-transfer
    coefficients: the constant term and the wind-driven term of the convective cooling.
    """

    noct_c: float = 45.0             # nominal operating cell temperature [degC]
    gamma_per_k: float = -0.0035     # power temperature coefficient [1/K]
    derate: float = 0.85             # soiling, wiring, mismatch and conversion losses
    u0_w_m2_k: float = 25.0          # Faiman constant heat-transfer coefficient
    u1_w_s_m3_k: float = 6.84        # Faiman wind-driven heat-transfer coefficient


def cell_temperature(
    ghi_w_m2: np.ndarray,
    t_amb_c: np.ndarray,
    module: ModuleSpec = ModuleSpec(),
) -> np.ndarray:
    """Cell temperature [degC] from irradiance and ambient temperature.

    Uses the nominal-operating-cell-temperature model, in which the cell sits above
    ambient in proportion to the incident irradiance. It needs no wind measurement, which
    matters here: wind is not available in the committed series.
    """
    ghi = np.asarray(ghi_w_m2, dtype=float)
    t_amb = np.asarray(t_amb_c, dtype=float)
    return t_amb + (module.noct_c - 20.0) / 800.0 * ghi


def cell_temperature_faiman(
    ghi_w_m2: np.ndarray,
    t_amb_c: np.ndarray,
    wind_m_s: np.ndarray,
    module: ModuleSpec = ModuleSpec(),
) -> np.ndarray:
    """Cell temperature [degC] accounting for convective cooling by the wind.

    The Faiman model resolves the cooling that the nominal-operating-cell-temperature
    model folds into a single constant. It matters here: the sites sit in a hot climate
    where the module runs well above its rated point for much of the day, and the
    temperature coefficient turns that excess directly into lost yield.
    """
    ghi = np.asarray(ghi_w_m2, dtype=float)
    t_amb = np.asarray(t_amb_c, dtype=float)
    wind = np.clip(np.asarray(wind_m_s, dtype=float), 0.0, None)
    return t_amb + ghi / (module.u0_w_m2_k + module.u1_w_s_m3_k * wind)


def specific_yield(
    ghi_w_m2: np.ndarray,
    t_amb_c: np.ndarray,
    module: ModuleSpec = ModuleSpec(),
    wind_m_s: np.ndarray | None = None,
) -> np.ndarray:
    """Specific yield [kW per kW installed] from irradiance and ambient temperature.

    The array is clipped at zero: a module never consumes power, and the temperature
    correction alone could otherwise turn a very hot, very weakly lit hour negative.
    """
    ghi = np.asarray(ghi_w_m2, dtype=float)
    if wind_m_s is None:
        t_cell = cell_temperature(ghi, t_amb_c, module)
    else:
        t_cell = cell_temperature_faiman(ghi, t_amb_c, wind_m_s, module)
    correction = 1.0 + module.gamma_per_k * (t_cell - T_STC)
    return np.clip(ghi / G_STC * module.derate * correction, 0.0, None)


def battery_usable_fraction(t_amb_c: np.ndarray) -> np.ndarray:
    """Fraction of nameplate energy a lithium-iron-phosphate pack can hold [-].

    Full capacity is available across the temperate band and falls off at both ends: below
    about 15 degC the pack loses capacity to internal resistance, above about 35 degC the
    management system derates it to protect the cells. Both slopes are linear
    approximations of the manufacturer's derating curves.
    """
    t = np.asarray(t_amb_c, dtype=float)
    cold = np.clip(1.0 - 0.010 * (15.0 - t), 0.6, 1.0)
    hot = np.clip(1.0 - 0.005 * (t - 35.0), 0.8, 1.0)
    return np.minimum(cold, hot)


def battery_self_discharge(t_amb_c: np.ndarray) -> np.ndarray:
    """Fractional self-discharge over one hour [-].

    Roughly 2 % of the stored energy per month at 25 degC, doubling for every 10 K above
    it, which is the usual rule of thumb for the electrochemistry of these cells.
    """
    t = np.asarray(t_amb_c, dtype=float)
    monthly = 0.02 * 2.0 ** ((t - T_STC) / 10.0)
    return np.clip(monthly / (30.0 * 24.0), 0.0, 1.0)


def load_irradiance(site: Site) -> pd.DataFrame:
    """Read the site's hourly irradiance series, indexed by timestamp."""
    frame = pd.read_csv(site.irradiance_path(), parse_dates=["timestamp"])
    frame = frame.set_index("timestamp").sort_index()
    if "irradiance_w_m2" not in frame.columns:
        raise ValueError(
            f"{site.irradiance_path().name} has no 'irradiance_w_m2' column "
            f"(columns: {list(frame.columns)})"
        )
    return frame


@dataclass
class ResourceYear:
    """One calendar year of resource quantities on the model's hourly grid."""

    site: str
    year: int
    specific_yield: np.ndarray          # Y [kW/kW]
    t_amb_c: np.ndarray                 # ambient temperature [degC]
    usable_fraction: np.ndarray         # F^e [-]
    self_discharge: np.ndarray          # A [-] per hour
    isothermal: bool                    # True when temperature was assumed, not measured
    cell_model: str = "noct"            # cell-temperature model actually used

    @property
    def annual_yield_kwh_per_kw(self) -> float:
        """Energy produced per kW installed over the year [kWh/kW]."""
        return float(self.specific_yield.sum())

    @property
    def capacity_factor(self) -> float:
        return float(self.specific_yield.mean())


def simulate_resource_year(
    site: Site,
    year: int,
    module: ModuleSpec = ModuleSpec(),
    t_amb_c: float | np.ndarray | None = None,
) -> ResourceYear:
    """Build the resource year for ``site``.

    ``t_amb_c`` may be an hourly series, a single value standing for an isothermal
    approximation, or ``None``. When it is ``None`` the temperature is taken from the
    meteorological file if it carries one, and otherwise the call fails rather than
    inventing a temperature: the specific yield depends on it, and a silent default would
    be an unrecorded modelling assumption. When the file also carries wind speed, the
    Faiman cell-temperature model is used in place of the nominal-operating-cell model,
    which resolves the convective cooling instead of folding it into a constant.
    """
    frame = load_irradiance(site)
    frame = frame[frame.index.year == year]
    if frame.empty:
        years = sorted(load_irradiance(site).index.year.unique())
        raise ValueError(f"no irradiance for {site.name} in {year}; available: {years}")

    ghi = frame["irradiance_w_m2"].to_numpy(dtype=float)
    isothermal = False
    wind = (frame["wind_speed_m_s"].to_numpy(dtype=float)
            if "wind_speed_m_s" in frame.columns else None)

    if t_amb_c is None:
        for column in ("t_amb_c", "temperature_c", "t2m_c", "air_temperature_c"):
            if column in frame.columns:
                temperature = frame[column].to_numpy(dtype=float)
                break
        else:
            raise ValueError(
                f"{site.irradiance_file} carries no ambient-temperature column, "
                "and the specific yield depends on it. Regenerate the series with the "
                "two-metre temperature the download already requests, or pass an explicit "
                "t_amb_c to work under a stated isothermal assumption."
            )
    elif np.isscalar(t_amb_c):
        temperature = np.full(ghi.shape, float(t_amb_c))
        isothermal = True
    else:
        temperature = np.asarray(t_amb_c, dtype=float)
        if temperature.shape != ghi.shape:
            raise ValueError(
                f"temperature has {temperature.shape} values for {ghi.shape} hours"
            )

    return ResourceYear(
        site=site.name,
        year=year,
        specific_yield=specific_yield(ghi, temperature, module, wind_m_s=wind),
        t_amb_c=temperature,
        usable_fraction=battery_usable_fraction(temperature),
        self_discharge=battery_self_discharge(temperature),
        isothermal=isothermal,
        cell_model="faiman" if wind is not None else "noct",
    )
