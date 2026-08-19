"""Forward simulation of the deployed rule-based controller — the upper-bound oracle.

This is the operating model that will actually run the plant, and the quantity it returns
is the upper bound of the certificate. It reproduces the generation-balance controller of
off-grid practice: photovoltaic power serves the load first, its surplus charges the
battery and is curtailed only once the battery is full, the remaining deficit is drawn from
the battery, and the generator starts only when the battery cannot carry the load — refined
by a look-ahead that reserves enough stored energy to reach the next photovoltaic surplus.

**What is ported and what is not.** The *decision rule* is taken faithfully: the priority
order, the night-reserve look-ahead, the temperature dependence of usable capacity and
self-discharge, and the quadratic dependence of generator efficiency on part load. The
*physics* is that of the feasible set :math:`\\mathcal{F}(x)` rather than the reference
implementation's, which differs on three points: it updates the state of charge without
round-trip losses, it has no minimum stable loading for the generator, and it lets a
deficit the generator cannot cover disappear instead of counting it as unserved energy.
Those three would put the trajectory outside :math:`\\mathcal{F}(x)` and invalidate the
bound, so the rule is applied under the model's own physics. This is precisely the
"policy class whose trajectories lie in the feasible set" the formulation requires, and
:meth:`Dispatch.feasibility` verifies the result rather than assuming it.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .. import config

#: Mass density of diesel [kg/L], to convert the fuel mass the efficiency curve yields
#: into the volume the fuel price is quoted against.
DIESEL_DENSITY_KG_L = 0.832
#: Higher heating value of diesel [kJ/kg].
DIESEL_HHV_KJ_KG = 45800.0


@dataclass(frozen=True)
class BatteryModel:
    """Storage behaviour, including the temperature effects the controller reacts to."""

    charge_efficiency: float = config.ETA_CHARGE
    discharge_efficiency: float = config.ETA_DISCHARGE
    soc_min: float = config.SOC_MIN_FRAC
    soc_max: float = config.SOC_MAX_FRAC
    #: Maximum charge or discharge power as a fraction of nameplate energy, per hour.
    c_rate: float = 0.25
    #: Storage chemistry, by name or as a Chemistry; drives the temperature response.
    chemistry: str = config.BATTERY_CHEMISTRY
    #: State of charge the plant starts from, as a fraction of the usable ceiling. Declared
    #: once here and read by the bound, so the two cannot start from different states.
    initial_soc_fraction: float = 0.5

    @classmethod
    def from_spec(cls, spec) -> "BatteryModel":
        """Build the operating model of the pack described in the project settings."""
        return cls(charge_efficiency=spec.charge_efficiency,
                   discharge_efficiency=spec.discharge_efficiency,
                   soc_min=spec.soc_min, soc_max=spec.soc_max, c_rate=spec.c_rate,
                   chemistry=spec.chemistry,
                   initial_soc_fraction=spec.initial_soc_fraction)

    def usable_fraction(self, t_amb_c: np.ndarray) -> np.ndarray:
        """Temperature derating of the nameplate energy (single definition)."""
        from ..battery import usable_fraction
        return usable_fraction(t_amb_c, self.chemistry)

    def self_discharge(self, capacity_kwh: float, t_amb_c: np.ndarray,
                       timestep_h: float = 1.0) -> np.ndarray:
        """Energy lost to self-discharge over one step [kWh] (single definition)."""
        from ..battery import self_discharge_kwh
        return self_discharge_kwh(capacity_kwh, t_amb_c, self.chemistry, timestep_h)


@dataclass(frozen=True)
class GeneratorModel:
    """Diesel generator, with efficiency varying over the part-load range."""

    min_load_fraction: float = config.GEN_MIN_LOAD_FRAC
    fuel_price_usd_l: float = config.DIESEL_PRICE_USD_L
    #: Quadratic efficiency in the part load, fitted on the manufacturer's fuel curve.
    eta_0: float = 0.0995
    eta_1: float = 0.4215
    eta_2: float = -0.2368
    eta_floor: float = 0.02

    @classmethod
    def from_spec(cls, spec, fuel_price_usd_l: float) -> "GeneratorModel":
        """Build the operating model of one catalogue entry from its datasheet.

        Each rating carries its own consumption figures, so each gets its own efficiency
        curve. Applying one unit's curve to a whole catalogue would make the sizes
        indistinguishable in exactly the dimension the certificate arbitrates over.
        """
        a, b, c = spec.efficiency_coefficients()
        return cls(min_load_fraction=spec.min_load_fraction,
                   fuel_price_usd_l=fuel_price_usd_l,
                   eta_0=a, eta_1=b, eta_2=c)

    def efficiency(self, part_load: np.ndarray | float) -> np.ndarray:
        """Conversion efficiency at a given fraction of the nameplate rating."""
        p = np.asarray(part_load, dtype=float)
        eta = self.eta_0 + self.eta_1 * p + self.eta_2 * p ** 2
        return np.maximum(eta, self.eta_floor)

    def fuel_litres(self, output_kw: np.ndarray, rating_kw: float,
                    timestep_h: float = 1.0) -> np.ndarray:
        """Fuel burnt over one step [L]."""
        output = np.asarray(output_kw, dtype=float)
        if rating_kw <= 0:
            return np.zeros_like(output)
        eta = self.efficiency(np.divide(output, rating_kw))
        fuel_kj = np.where(output > 0, output / eta * timestep_h * 3600.0, 0.0)
        return fuel_kj / DIESEL_HHV_KJ_KG / DIESEL_DENSITY_KG_L


@dataclass(frozen=True)
class Controller:
    """Parameters of the generation-balance rule.

    ``reserve_multiplier`` scales the look-ahead reserve and ``lookahead_hours`` sets how
    far it looks; ``generator_setpoint`` is the loading the generator targets once running,
    the power beyond the served deficit going to the battery. The reference strategy is
    recovered at a setpoint equal to the minimum stable loading.
    """

    reserve_multiplier: float = 1.0
    lookahead_hours: int = 14
    generator_setpoint: float = config.GEN_MIN_LOAD_FRAC


@dataclass(frozen=True)
class Capacities:
    """One point of the design lattice, in physical units."""

    pv_kw: float
    battery_kwh: float
    inverter_kw: float
    generator_kw: float


def night_reserve(demand_kw: np.ndarray, pv_kw: np.ndarray,
                  controller: Controller) -> np.ndarray:
    """Energy needed to reach the next photovoltaic surplus [kWh].

    The look-ahead the field controller applies: at each hour, the net demand that the
    battery would have to carry until generation next exceeds consumption, capped at the
    horizon. It is what stops the battery being emptied in the evening and the generator
    having to run all night.
    """
    demand = np.asarray(demand_kw, dtype=float)
    pv = np.asarray(pv_kw, dtype=float)
    deficit = np.clip(demand - pv, 0.0, None)
    horizon = int(controller.lookahead_hours)
    n = demand.size

    reserve = np.zeros(n)
    for h in range(n):
        end = min(h + horizon, n)
        window = deficit[h:end]
        surplus = np.flatnonzero(pv[h:end] > demand[h:end])
        if surplus.size:
            window = window[:surplus[0]]
        reserve[h] = window.sum()
    return controller.reserve_multiplier * reserve


@dataclass
class Dispatch:
    """The trajectory produced by the controller and what it costs."""

    generator_kw: np.ndarray
    charge_kw: np.ndarray
    discharge_kw: np.ndarray
    soc_kwh: np.ndarray
    curtailed_kw: np.ndarray
    unserved_kw: np.ndarray
    fuel_litres: np.ndarray
    capacities: Capacities
    derating_spill_kwh: float = 0.0

    @property
    def fuel_cost_usd(self) -> float:
        return float(self.fuel_litres.sum())

    def operating_cost(self, generator: GeneratorModel = GeneratorModel(),
                       degradation_usd_kwh: float | None = None,
                       voll_usd_kwh: float = config.VOLL_USD_KWH) -> float:
        """Annual operating cost: fuel, storage degradation and unserved energy."""
        degradation = (config.battery_degradation_cost()
                       if degradation_usd_kwh is None else degradation_usd_kwh)
        return float(self.fuel_litres.sum() * generator.fuel_price_usd_l
                     + self.discharge_kw.sum() * degradation
                     + self.unserved_kw.sum() * voll_usd_kwh)

    @property
    def served_kwh(self) -> float:
        return float(self.demand_kwh - self.unserved_kw.sum())

    demand_kwh: float = 0.0

    def feasibility(self, battery: BatteryModel, generator: GeneratorModel,
                    usable_fraction: np.ndarray, tolerance: float = 1e-6) -> dict:
        """Check the trajectory against the operating feasible set.

        The certificate rests on the trajectory being admissible for the cost-optimal
        problem; this reports each condition rather than trusting it.
        """
        cap = self.capacities
        simultaneous = float(np.minimum(self.charge_kw, self.discharge_kw).max(initial=0.0))
        running = self.generator_kw > tolerance
        min_load = generator.min_load_fraction * cap.generator_kw
        return {
            "no_simultaneous_charge_discharge": simultaneous <= tolerance,
            "generator_within_rating":
                bool((self.generator_kw <= cap.generator_kw + tolerance).all()),
            "generator_above_minimum_load":
                bool((self.generator_kw[running] >= min_load - 1e-6).all())
                if running.any() else True,
            "inverter_within_rating":
                bool((self.charge_kw <= cap.inverter_kw + tolerance).all()
                     and (self.discharge_kw <= cap.inverter_kw + tolerance).all()),
            "soc_within_trips": bool(
                (self.soc_kwh >= battery.soc_min * cap.battery_kwh - 1e-6).all()
                and (self.soc_kwh[:-1] <= battery.soc_max * usable_fraction
                     * cap.battery_kwh + 1e-6).all()),
            "no_negative_flows": bool(
                (self.generator_kw >= -tolerance).all()
                and (self.charge_kw >= -tolerance).all()
                and (self.discharge_kw >= -tolerance).all()
                and (self.unserved_kw >= -tolerance).all()
                and (self.curtailed_kw >= -tolerance).all()),
        }


def simulate(
    demand_kw: np.ndarray,
    specific_yield: np.ndarray,
    t_amb_c: np.ndarray,
    capacities: Capacities,
    battery: BatteryModel = BatteryModel(),
    generator: GeneratorModel = GeneratorModel(),
    controller: Controller = Controller(),
    timestep_h: float = 1.0,
) -> Dispatch:
    """Run the controller over a series and return its trajectory."""
    demand = np.asarray(demand_kw, dtype=float)
    pv = np.asarray(specific_yield, dtype=float) * capacities.pv_kw
    temperature = np.asarray(t_amb_c, dtype=float)
    n = demand.size
    if pv.size != n or temperature.size != n:
        raise ValueError("demand, yield and temperature must have the same length")

    usable = battery.usable_fraction(temperature)
    # Ceiling of the next step as well as the current one: the usable capacity follows the
    # temperature and can tighten from one hour to the next below the energy already
    # stored. A real management system derates and that excess becomes unavailable; not
    # modelling it would leave the trajectory outside the feasible set and invalidate the
    # bound, for a loss of about one per cent of capacity in one hour in sixty.
    ceilings = battery.soc_max * usable * capacities.battery_kwh
    next_ceiling = np.append(ceilings[1:], ceilings[-1])
    losses = battery.self_discharge(capacities.battery_kwh, temperature, timestep_h)
    reserve = night_reserve(demand, pv, controller)
    power_limit = battery.c_rate * capacities.battery_kwh

    gen = np.zeros(n)
    charge = np.zeros(n)
    discharge = np.zeros(n)
    curtailed = np.zeros(n)
    unserved = np.zeros(n)
    soc = np.zeros(n + 1)
    soc[0] = min(battery.initial_soc_fraction * battery.soc_max * capacities.battery_kwh,
                 ceilings[0] if n else 0.0)
    spill = 0.0

    floor = battery.soc_min * capacities.battery_kwh
    for h in range(n):
        energy = max(soc[h] - losses[h], floor)
        ceiling = ceilings[h]

        served = min(pv[h], demand[h])
        surplus = pv[h] - served
        deficit = demand[h] - served
        inverter_left = capacities.inverter_kw

        # 1. photovoltaic surplus charges the battery, the rest is curtailed
        headroom = max(ceiling - energy, 0.0)
        charge_kw = min(surplus, inverter_left, power_limit,
                        headroom / battery.charge_efficiency / timestep_h)
        charge_kw = max(charge_kw, 0.0)
        energy += battery.charge_efficiency * charge_kw * timestep_h
        inverter_left -= charge_kw
        curtailed[h] = surplus - charge_kw
        charge[h] = charge_kw

        if deficit > 0:
            # 2. the battery may serve the load only above the look-ahead reserve
            reserve_floor = min(max(floor, reserve[h]), ceiling)
            available = max(energy - reserve_floor, 0.0) * battery.discharge_efficiency
            from_battery = min(deficit, inverter_left, power_limit, available / timestep_h)
            from_battery = max(from_battery, 0.0)

            if from_battery >= deficit - 1e-9:
                discharge[h] = from_battery
                energy -= from_battery / battery.discharge_efficiency * timestep_h
                inverter_left -= from_battery
            else:
                # 3. the generator starts, at least at its minimum stable loading
                remaining = deficit
                target = max(remaining,
                             controller.generator_setpoint * capacities.generator_kw,
                             generator.min_load_fraction * capacities.generator_kw)
                output = min(capacities.generator_kw, target)
                gen[h] = output

                to_load = min(output, remaining)
                remaining -= to_load
                spare = output - to_load
                if spare > 0:
                    headroom = max(ceiling - energy, 0.0)
                    extra = min(spare, inverter_left, power_limit - charge[h],
                                headroom / battery.charge_efficiency / timestep_h)
                    extra = max(extra, 0.0)
                    energy += battery.charge_efficiency * extra * timestep_h
                    charge[h] += extra
                    inverter_left -= extra
                    curtailed[h] += spare - extra      # generator power with nowhere to go
                if remaining > 1e-9:
                    # the battery covers what the generator could not, down to its floor
                    available = max(energy - floor, 0.0) * battery.discharge_efficiency
                    from_battery = min(remaining, inverter_left, power_limit,
                                       available / timestep_h)
                    from_battery = max(from_battery, 0.0)
                    discharge[h] = from_battery
                    energy -= from_battery / battery.discharge_efficiency * timestep_h
                    remaining -= from_battery
                unserved[h] = max(remaining, 0.0)

        closing = min(max(energy, floor), ceiling)
        derated = min(closing, next_ceiling[h])
        spill += closing - derated
        soc[h + 1] = derated

    return Dispatch(
        generator_kw=gen, charge_kw=charge, discharge_kw=discharge, soc_kwh=soc,
        curtailed_kw=curtailed, unserved_kw=unserved,
        fuel_litres=generator.fuel_litres(gen, capacities.generator_kw, timestep_h),
        capacities=capacities, demand_kwh=float(demand.sum()),
        derating_spill_kwh=float(spill),
    )
