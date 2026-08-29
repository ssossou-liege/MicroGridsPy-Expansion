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
class GridLink:
    """A connection to the national grid, as the controller sees it hour by hour.

    ``available`` carries the outage pattern rather than an availability figure: what a plant
    must carry alone is the length of the stretches, not their average, and averaging them
    away would size the storage against a grid that dims instead of one that goes out.
    """

    available: np.ndarray | None = None
    capacity_kw: float = 0.0
    import_usd_kwh: float = 0.0
    export_usd_kwh: float = 0.0
    exports: bool = False

    @property
    def present(self) -> bool:
        return self.available is not None


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
    """One point of the design lattice, in physical units.

    ``architecture`` records where the array joins the plant, ``"dc"`` through charge
    controllers onto the battery's bus or ``"ac"`` through string inverters onto the load's.
    It belongs here because it is a decision, not a convention: the two differ in what they
    cost and in what the hybrid inverter has to carry, and the certificate proves the choice
    rather than assuming it.

    ``pv_conversion_kw`` is the rating of that photovoltaic-side conversion. Left unset it
    matches the array, which is how controllers and string inverters are ordinarily sized.
    """

    #: Array on the hybrid inverter's own trackers, feeding the battery's bus.
    pv_kw: float
    battery_kwh: float
    inverter_kw: float
    generator_kw: float
    #: Array on string inverters, feeding the load's bus. Zero recovers a plant whose whole
    #: field is on the hybrid inverter; setting ``pv_kw`` to zero recovers the converse.
    pv_ac_kw: float = 0.0
    architecture: str = "mixte"
    pv_conversion_kw: float | None = None

    @property
    def pv_total_kw(self) -> float:
        """Installed array, both buses together."""
        return self.pv_kw + self.pv_ac_kw

    @property
    def conversion_kw(self) -> float:
        """Photovoltaic-side conversion rating, defaulting to the array's own.

        Under direct-current coupling this is the hybrid inverter's integrated trackers,
        bought with the inverter; under alternating coupling it is the string inverters,
        bought separately. Either way it matches the array, which is how both are sized.
        """
        return self.pv_kw if self.pv_conversion_kw is None else self.pv_conversion_kw

    def admissible(self, ratio_dc: float, ratio_ac: float | None = None) -> bool:
        """Whether each part of the array is within what its converter admits.

        The two parts are limited separately and for different reasons: the trackers
        integrated in the hybrid inverter accept a bounded array per unit of rating, and an
        array on the load's bus must be absorbable by the battery inverter the instant the
        load falls away.
        """
        ratio_ac = ratio_dc if ratio_ac is None else ratio_ac
        return (self.pv_kw <= ratio_dc * self.inverter_kw + 1e-9
                and self.pv_ac_kw <= ratio_ac * self.inverter_kw + 1e-9)


def _night_reserve_loop(n, horizon, deficit, pv, demand, reserve):
    """Sum each hour's deficit up to the next surplus, filling ``reserve`` in place.

    Written as an explicit scan rather than with array primitives: the interpreted version
    called ``flatnonzero`` once per hour, eight thousand times per simulated year, and that
    single line outweighed the whole dispatch recursion once the latter was compiled.
    """
    for h in range(n):
        end = min(h + horizon, n)
        total = 0.0
        for k in range(h, end):
            if pv[k] > demand[k]:
                break
            total += deficit[k]
        reserve[h] = total


try:                                   # compiled when numba is present, interpreted if not
    from numba import njit as _njit_reserve

    _night_reserve_loop = _njit_reserve(cache=True)(_night_reserve_loop)
except Exception:                      # pragma: no cover - depends on the installation
    pass


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
    _night_reserve_loop(n, horizon, deficit, pv, demand, reserve)
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
    #: Power crossing the hybrid inverter each hour. What crosses it depends on the
    #: architecture — under direct-current coupling the array reaches the load through it,
    #: under alternating-current coupling the array reaches the battery through it — so the
    #: total is accumulated as the trajectory is built rather than reconstructed afterwards.
    inverter_flow_kw: np.ndarray | None = None
    #: Array output refused by the photovoltaic-side conversion, already counted in
    #: ``curtailed_kw``. Reported apart because it is an equipment-sizing loss, not a
    #: surplus the plant had no use for.
    clipped_kwh: float = 0.0

    @property
    def fuel_cost_usd(self) -> float:
        return float(self.fuel_litres.sum())

    def operating_cost(self, generator: GeneratorModel = GeneratorModel(),
                       degradation_usd_kwh: float | None = None,
                       voll_usd_kwh: float = config.VOLL_USD_KWH) -> float:
        """Annual operating cost: fuel, storage degradation and unserved energy."""
        degradation = (config.battery_degradation_cost()
                       if degradation_usd_kwh is None else degradation_usd_kwh)
        imported = (0.0 if self.grid_import_kw is None
                    else float(self.grid_import_kw.sum()) * self.grid_import_usd_kwh)
        exported = (0.0 if self.grid_export_kw is None
                    else float(self.grid_export_kw.sum()) * self.grid_export_usd_kwh)
        return float(self.fuel_litres.sum() * generator.fuel_price_usd_l
                     + self.discharge_kw.sum() * degradation
                     + self.unserved_kw.sum() * voll_usd_kwh
                     + imported - exported)

    @property
    def served_kwh(self) -> float:
        return float(self.demand_kwh - self.unserved_kw.sum())

    demand_kwh: float = 0.0
    #: Energy drawn from and injected into the national grid [kW per step], and their prices.
    grid_import_kw: np.ndarray | None = None
    grid_export_kw: np.ndarray | None = None
    grid_import_usd_kwh: float = 0.0
    grid_export_usd_kwh: float = 0.0
    #: Array power reaching the load directly, before any storage.
    pv_to_load_kw: np.ndarray | None = None

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
                bool((self.inverter_flow_kw <= cap.inverter_kw + tolerance).all())
                if self.inverter_flow_kw is not None else
                bool((self.charge_kw <= cap.inverter_kw + tolerance).all()
                     and (self.discharge_kw <= cap.inverter_kw + tolerance).all()),
            "pv_conversion_within_rating":
                bool((self.pv_to_load_kw + self.charge_kw
                      <= cap.conversion_kw + cap.generator_kw + tolerance).all())
                if self.pv_to_load_kw is not None else True,
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




# ------------------------------------------------------------------- noyau de l'automate
def _controller_loop(n, demand, pv, soc, losses, ceilings, next_ceiling, reserve,
                     gen, charge, discharge, curtailed, unserved, pv_to_load,
                     inverter_flow, floor, share_dc, eta_ac, power_limit, timestep_h,
                     cap_pv_kw, cap_pv_ac_kw, cap_inverter_kw, cap_generator_kw,
                     eta_charge, eta_discharge, gen_setpoint, gen_min_load,
                     grid_available, grid_import, grid_export, grid_capacity_kw,
                     grid_exports):
    """The controller's hour-by-hour recursion, over scalars and arrays alone.

    Lifted out of :func:`simulate` so that it can be compiled. The body is a scalar
    recursion over the hours of a year and holds the interpreter lock throughout, which made
    it the floor under every search built on this oracle: a certification spends most of its
    time here, and interpreted it runs at about a hundred and thirty thousand hours a
    second. Compiled, the same arithmetic runs untouched.

    The arrays are filled in place; the two running totals come back as the return value.
    """
    spill = 0.0
    clipped_total = 0.0
    for h in range(n):
        energy = max(soc[h] - losses[h], floor)
        ceiling = ceilings[h]

        # Neither part of the array delivers more than its own converter is rated for; the
        # excess is clipped and reaches no bus at all.
        offered = pv[h] * share_dc
        offered_ac = pv[h] - offered
        available_dc = min(offered, cap_pv_kw)
        available_ac = min(offered_ac, cap_pv_ac_kw)
        clipped = (offered - available_dc) + (offered_ac - available_ac)
        clipped_total += clipped

        inverter_left = cap_inverter_kw
        # The field on the load's bus serves it without conversion, and is therefore drawn
        # on first; what the field on the battery's bus sends the load is converted.
        served_ac = min(available_ac, demand[h])
        remaining_demand = demand[h] - served_ac
        served_dc = min(available_dc, remaining_demand, inverter_left)
        inverter_left -= served_dc
        inverter_flow[h] += served_dc

        served = served_ac + served_dc
        surplus_dc = available_dc - served_dc
        surplus_ac = available_ac - served_ac
        deficit = demand[h] - served
        pv_to_load[h] = served

        # 1. the surplus charges the battery. From the battery's own bus it arrives without
        #    conversion; from the load's bus it must be rectified, and the hybrid inverter
        #    limits it.
        headroom = max(ceiling - energy, 0.0)
        charge_dc = min(surplus_dc, power_limit,
                        headroom / eta_charge / timestep_h)
        charge_dc = max(charge_dc, 0.0)
        energy += eta_charge * charge_dc * timestep_h

        headroom = max(ceiling - energy, 0.0)
        charge_ac = min(surplus_ac, inverter_left, power_limit - charge_dc,
                        headroom / eta_ac / timestep_h)
        charge_ac = max(charge_ac, 0.0)
        energy += eta_ac * charge_ac * timestep_h
        inverter_left -= charge_ac
        inverter_flow[h] += charge_ac

        charge_kw = charge_dc + charge_ac
        reste = (surplus_dc - charge_dc) + (surplus_ac - charge_ac)
        # What the battery could not take goes to the grid before it is thrown away, up to
        # what the connection can inject and what the converter can still carry. Only the
        # part on the battery's bus needs the inverter to get there; the part already on the
        # load's bus is on the right side of it.
        if grid_available[h] and grid_exports and reste > 1e-9:
            room = grid_capacity_kw if grid_capacity_kw > 0.0 else reste
            grid_export[h] = min(reste, room)
            reste -= grid_export[h]
        curtailed[h] = reste + clipped
        charge[h] = charge_kw

        if deficit > 0:
            # 2. the battery may serve the load only above the look-ahead reserve
            #
            # The grid comes *after* storage and *before* the generating set. Stored energy
            # was bought with sunlight and costs only the wear of the cycle; imported energy
            # costs the utility's tariff, which is nonetheless a third of what a litre of
            # diesel costs to deliver at the same kilowatt-hour. So a connection displaces
            # the generator, not the battery -- which is what operators report when a feeder
            # reaches a village, and why the plant it justifies has less diesel and no less
            # storage.
            reserve_floor = min(max(floor, reserve[h]), ceiling)
            available = max(energy - reserve_floor, 0.0) * eta_discharge
            from_battery = min(deficit, inverter_left, power_limit, available / timestep_h)
            from_battery = max(from_battery, 0.0)

            if from_battery >= deficit - 1e-9:
                discharge[h] = from_battery
                energy -= from_battery / eta_discharge * timestep_h
                inverter_left -= from_battery
                inverter_flow[h] += from_battery
            else:
                # 3. the grid carries what storage could not, while it is energised
                remaining = deficit - from_battery
                if from_battery > 0.0:
                    discharge[h] = from_battery
                    energy -= from_battery / eta_discharge * timestep_h
                    inverter_left -= from_battery
                    inverter_flow[h] += from_battery
                if grid_available[h] and remaining > 1e-9:
                    room = grid_capacity_kw if grid_capacity_kw > 0.0 else remaining
                    taken = min(remaining, room)
                    grid_import[h] = taken
                    remaining -= taken
                if remaining <= 1e-9:
                    unserved[h] = 0.0
                    closing = min(max(energy, floor), ceiling)
                    derated = min(closing, next_ceiling[h])
                    spill += closing - derated
                    soc[h + 1] = derated
                    continue

                # 4. the generating set starts, at least at its minimum stable loading
                target = max(remaining,
                             gen_setpoint * cap_generator_kw,
                             gen_min_load * cap_generator_kw)
                output = min(cap_generator_kw, target)
                gen[h] = output

                to_load = min(output, remaining)
                remaining -= to_load
                spare = output - to_load
                if spare > 0:
                    headroom = max(ceiling - energy, 0.0)
                    extra = min(spare, inverter_left, power_limit - charge[h],
                                headroom / eta_charge / timestep_h)
                    extra = max(extra, 0.0)
                    energy += eta_charge * extra * timestep_h
                    charge[h] += extra
                    inverter_left -= extra
                    inverter_flow[h] += extra
                    curtailed[h] += spare - extra      # generator power with nowhere to go
                if remaining > 1e-9:
                    # the battery covers what the generator could not, down to its floor
                    available = max(energy - floor, 0.0) * eta_discharge
                    from_battery = min(remaining, inverter_left, power_limit,
                                       available / timestep_h)
                    from_battery = max(from_battery, 0.0)
                    discharge[h] = from_battery
                    energy -= from_battery / eta_discharge * timestep_h
                    inverter_flow[h] += from_battery
                    remaining -= from_battery
                unserved[h] = max(remaining, 0.0)

        closing = min(max(energy, floor), ceiling)
        derated = min(closing, next_ceiling[h])
        spill += closing - derated
        soc[h + 1] = derated
    return spill, clipped_total


try:                                   # compiled when numba is present, interpreted if not
    from numba import njit

    _controller_loop = njit(cache=True)(_controller_loop)
except Exception:                      # pragma: no cover - depends on the installation
    pass


def simulate(
    demand_kw: np.ndarray,
    specific_yield: np.ndarray,
    t_amb_c: np.ndarray,
    capacities: Capacities,
    battery: BatteryModel = BatteryModel(),
    generator: GeneratorModel = GeneratorModel(),
    controller: Controller = Controller(),
    timestep_h: float = 1.0,
    grid: "GridLink | None" = None,
) -> Dispatch:
    """Run the controller over a series and return its trajectory."""
    demand = np.asarray(demand_kw, dtype=float)
    # The whole field produces, whichever bus each part of it is on; the split governs the
    # path to the load, not the output.
    pv = np.asarray(specific_yield, dtype=float) * capacities.pv_total_kw
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
    pv_to_load = np.zeros(n)
    inverter_flow = np.zeros(n)
    soc = np.zeros(n + 1)
    soc[0] = min(battery.initial_soc_fraction * battery.soc_max * capacities.battery_kwh,
                 ceilings[0] if n else 0.0)

    floor = battery.soc_min * capacities.battery_kwh
    total_array = capacities.pv_total_kw
    share_dc = (capacities.pv_kw / total_array) if total_array > 0 else 0.0
    # Array energy reaching storage across the load's bus is converted twice, up by the
    # string inverter and down again by the hybrid inverter. That second conversion is what
    # a field placed on the load's bus pays for the one it saves on the way to the load.
    eta_ac = battery.charge_efficiency * config.AC_DOUBLE_CONVERSION_EFF
    grid = GridLink() if grid is None else grid
    if grid.available is None:
        grid_available = np.zeros(n, dtype=np.bool_)
    else:
        grid_available = np.asarray(grid.available, dtype=np.bool_)[:n]
        if grid_available.size != n:
            raise ValueError(
                f"the outage pattern covers {grid_available.size} hours and the year {n}")
    grid_import = np.zeros(n)
    grid_export = np.zeros(n)

    spill, clipped_total = _controller_loop(
        n, demand, pv, soc, losses, ceilings, next_ceiling, reserve,
        gen, charge, discharge, curtailed, unserved, pv_to_load, inverter_flow,
        floor, share_dc, eta_ac, power_limit, timestep_h,
        capacities.pv_kw, capacities.pv_ac_kw, capacities.inverter_kw,
        capacities.generator_kw, battery.charge_efficiency, battery.discharge_efficiency,
        controller.generator_setpoint, generator.min_load_fraction,
        grid_available, grid_import, grid_export, float(grid.capacity_kw),
        bool(grid.exports))

    return Dispatch(
        generator_kw=gen, charge_kw=charge, discharge_kw=discharge, soc_kwh=soc,
        curtailed_kw=curtailed, unserved_kw=unserved,
        fuel_litres=generator.fuel_litres(gen, capacities.generator_kw, timestep_h),
        capacities=capacities, demand_kwh=float(demand.sum()),
        derating_spill_kwh=float(spill),
        pv_to_load_kw=pv_to_load, inverter_flow_kw=inverter_flow,
        clipped_kwh=float(clipped_total),
        grid_import_kw=grid_import, grid_export_kw=grid_export,
        grid_import_usd_kwh=float(grid.import_usd_kwh),
        grid_export_usd_kwh=float(grid.export_usd_kwh),
    )
