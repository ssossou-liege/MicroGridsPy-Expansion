"""Two operating-cost oracles for the capacity lattice and one representative day.

``cost_optimal_relaxation`` is the LOWER-bound oracle: a linear program minimising
annualised total cost Z_opt over the feasible dispatch set F(x) (power balance, storage
dynamics and limits, generator and inverter limits, curtailment and unmet-load slacks),
with the capacities themselves treated as continuous variables ranging over a box. This
is exactly the box relaxation of Proposition 1 (docs/formulation/model.tex). Pinning the
box to a single point (lo == hi) yields the exact cost-optimal value at that point.

``rule_dispatch`` is the UPPER-bound oracle: a forward simulation of the uGrid
generation-balance controller (PV -> battery -> generator priority, with a night-reserve
floor). Its trajectory is feasible for F(x), so

    cost_optimal (operating)  <=  rule_dispatch (operating)        (Proposition 1)

which licenses the branch-and-simulate bound.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import linprog

from .. import config


def _toy_fuel_coefficients() -> tuple[float, float]:
    """Fuel cost per generator-on hour and per kWh, from the catalogue's own curve."""
    from ..settings import default_settings
    from .lower_bound import fuel_minorant
    from .simulator import GeneratorModel

    settings = default_settings()
    spec = min(settings.generators, key=lambda g: abs(g.rating_kw - 16.0))
    a, b, c = spec.efficiency_coefficients()
    model = GeneratorModel(eta_0=a, eta_1=b, eta_2=c,
                           min_load_fraction=spec.min_load_fraction,
                           fuel_price_usd_l=settings.economics.diesel_price_usd_l)
    intercept, slope = fuel_minorant(model, spec.rating_kw)
    price = settings.economics.diesel_price_usd_l
    return intercept * price, slope * price


@dataclass
class ToyInstance:
    """A single representative day: demand, PV unit-yield and economics.

    Capacities are integer unit counts: ``cap_pv = n_pv * u_pv`` [kW] and
    ``cap_batt = n_batt * u_batt`` [kWh]. Generator and inverter are fixed.
    """

    demand: np.ndarray
    pv_unit: np.ndarray
    # active generator / inverter capacity for one evaluation (set per design point)
    cap_ge: float = 6.0
    cap_inv: float = 10.0
    # modular unit sizes and lattice bounds
    u_pv: float = config.PV_UNIT_KW
    u_batt: float = config.BATT_UNIT_KWH
    u_inv: float = config.INV_UNIT_KW
    n_pv_max: int = 40
    n_batt_max: int = 16
    n_inv_max: int = 8
    # generator catalogue (single unit, upgrades only) and resale value
    gen_catalog: tuple = config.GEN_CATALOG_KW
    gen_salvage_frac: float = config.GEN_SALVAGE_FRAC
    # brownfield initial condition (existing fleet); zero -> greenfield
    n_pv0: int = 0
    n_batt0: int = 0
    n_inv0: int = 0
    gen_kw0: float = 0.0

    crf: float = field(default_factory=config.crf)
    c_pv: float = config.PV_COST_USD_KW
    c_batt: float = config.BATT_COST_USD_KWH
    c_inv: float = config.INV_COST_USD_KW
    c_ge: float = config.GEN_COST_USD_KVA
    # Derived from the catalogue's own fuel curve rather than from a separate linear pair,
    # so the toy and the real oracles price fuel the same way.
    fuel_per_kwh: float = field(default_factory=lambda: _toy_fuel_coefficients()[1])
    fuel_fixed: float = field(default_factory=lambda: _toy_fuel_coefficients()[0])
    c_deg: float = field(default_factory=config.battery_degradation_cost)
    voll: float = config.VOLL_USD_KWH
    eta_c: float = config.ETA_CHARGE
    eta_d: float = config.ETA_DISCHARGE
    e_lo: float = config.SOC_MIN_FRAC
    e_hi: float = config.SOC_MAX_FRAC

    @property
    def H(self) -> int:
        return len(self.demand)

    def night_reserve(self) -> np.ndarray:
        """Baseline look-ahead reserve R[h] [kWh] (half the remaining-night demand)."""
        return 0.5 * _remaining_night(self)

    def capex_annualised(self, n_pv: int, n_batt: int) -> float:
        """Annualised PV + battery capex on the modules ADDED above the existing fleet.

        Pre-existing modules (n_pv0, n_batt0) are sunk and carry no charge (brownfield).
        """
        add_pv = max(n_pv - self.n_pv0, 0)
        add_batt = max(n_batt - self.n_batt0, 0)
        return self.crf * (self.c_pv * add_pv * self.u_pv
                           + self.c_batt * add_batt * self.u_batt)

    def inverter_capex_annualised(self, n_inv: int) -> float:
        """Annualised inverter capex on modules added above the existing fleet."""
        return self.crf * self.c_inv * max(n_inv - self.n_inv0, 0) * self.u_inv

    def generator_capex_annualised(self, gen_kw: float) -> float:
        """Annualised generator cost: install new size minus resale of the incumbent.

        Zero if the incumbent is kept (gen_kw == gen_kw0). On an upgrade, pay for the new
        unit and recover ``gen_salvage_frac`` of the old unit's capex (sold/redeployed).
        A greenfield project (gen_kw0 == 0) pays the full cost of the chosen unit.
        """
        if abs(gen_kw - self.gen_kw0) < 1e-9:
            return 0.0
        return self.crf * self.c_ge * (gen_kw - self.gen_salvage_frac * self.gen_kw0)


def _remaining_night(inst: "ToyInstance") -> np.ndarray:
    """Remaining-night demand [kWh] from early evening (h>=16) to next dawn (h<6)."""
    H, D = inst.H, inst.demand
    R = np.zeros(H)
    for h in range(H):
        if h >= 16 or h < 6:
            end = 24 + 6 if h >= 16 else 6
            R[h] = sum(D[k % 24] for k in range(h, end))
    return R


def cost_optimal_relaxation(inst: ToyInstance,
                            cap_pv_bounds: tuple[float, float],
                            cap_batt_bounds: tuple[float, float],
                            days: int = 365,
                            include_capex: bool = True) -> float:
    """LOWER-bound oracle: min annualised cost over F(x) for capacities in a box.

    With ``cap_*_bounds = (v, v)`` the capacities are pinned and the result is the exact
    cost-optimal value at that point. Returns annualised total cost [$/yr] (or, with
    ``include_capex=False, days=1``, the daily operating cost).
    """
    H = inst.H
    ge, ch, dis, q, ell, e = 0, H, 2 * H, 3 * H, 4 * H, 5 * H
    cpv, cbatt = 6 * H + 1, 6 * H + 2
    nvars = 6 * H + 3

    c = np.zeros(nvars)
    c[ge:ge + H] = days * inst.fuel_per_kwh
    c[dis:dis + H] = days * inst.c_deg
    c[ell:ell + H] = days * inst.voll
    if include_capex:
        c[cpv] = inst.crf * inst.c_pv
        c[cbatt] = inst.crf * inst.c_batt

    bounds = [(0.0, None)] * nvars
    for h in range(H):
        bounds[ge + h] = (0.0, inst.cap_ge)
        bounds[ch + h] = (0.0, inst.cap_inv)
        bounds[dis + h] = (0.0, inst.cap_inv)
        bounds[ell + h] = (0.0, inst.demand[h])
    bounds[cpv] = cap_pv_bounds
    bounds[cbatt] = cap_batt_bounds

    A_eq, b_eq = [], []
    # power balance: P_ge - P_ch + P_dis - q + ell + rho*cap_pv = D
    for h in range(H):
        row = np.zeros(nvars)
        row[ge + h] = 1.0; row[dis + h] = 1.0; row[ch + h] = -1.0
        row[q + h] = -1.0; row[ell + h] = 1.0; row[cpv] = inst.pv_unit[h]
        A_eq.append(row); b_eq.append(inst.demand[h])
    # storage dynamics
    for h in range(H):
        row = np.zeros(nvars)
        row[e + h + 1] = 1.0; row[e + h] = -1.0
        row[ch + h] = -inst.eta_c; row[dis + h] = 1.0 / inst.eta_d
        A_eq.append(row); b_eq.append(0.0)
    # initial SOC = 0.5 * usable capacity
    row = np.zeros(nvars)
    row[e + 0] = 1.0; row[cbatt] = -0.5 * inst.e_hi
    A_eq.append(row); b_eq.append(0.0)

    A_ub, b_ub = [], []
    for h in range(H):                               # q <= rho*cap_pv
        row = np.zeros(nvars); row[q + h] = 1.0; row[cpv] = -inst.pv_unit[h]
        A_ub.append(row); b_ub.append(0.0)
    for h in range(H + 1):                           # e <= e_hi*cap_batt
        row = np.zeros(nvars); row[e + h] = 1.0; row[cbatt] = -inst.e_hi
        A_ub.append(row); b_ub.append(0.0)
    for h in range(H + 1):                           # e >= e_lo*cap_batt
        row = np.zeros(nvars); row[e + h] = -1.0; row[cbatt] = inst.e_lo
        A_ub.append(row); b_ub.append(0.0)

    res = linprog(c, A_ub=np.array(A_ub), b_ub=np.array(b_ub),
                  A_eq=np.array(A_eq), b_eq=np.array(b_eq),
                  bounds=bounds, method="highs")
    if not res.success:
        raise RuntimeError(f"LP failed: {res.message}")
    value = float(res.fun)
    if include_capex:
        # brownfield: existing PV/battery is sunk -> charge only the added modules,
        # consistent with ToyInstance.capex_annualised used by the rule oracle.
        value -= inst.crf * (inst.c_pv * inst.n_pv0 * inst.u_pv
                             + inst.c_batt * inst.n_batt0 * inst.u_batt)
    return value


def rule_dispatch(inst: ToyInstance, cap_pv: float, cap_batt: float) -> float:
    """UPPER-bound oracle: daily operating cost of the rule-based controller [$/day]."""
    H = inst.H
    Rf = inst.night_reserve()
    e = 0.5 * inst.e_hi * cap_batt
    floor_abs, cap_abs = inst.e_lo * cap_batt, inst.e_hi * cap_batt
    cost = 0.0
    for h in range(H):
        pv = inst.pv_unit[h] * cap_pv
        served = min(pv, inst.demand[h])
        surplus, deficit = pv - served, inst.demand[h] - served

        room = cap_abs - e
        chg = min(surplus, inst.cap_inv, room / inst.eta_c if inst.eta_c else 0.0)
        e += inst.eta_c * chg

        reserve = min(max(floor_abs, Rf[h]), cap_abs)
        avail = max(e - reserve, 0.0)
        dch = min(deficit, inst.cap_inv, avail * inst.eta_d)
        e -= dch / inst.eta_d
        deficit -= dch

        gen = min(deficit, inst.cap_ge)
        unmet = deficit - gen
        cost += inst.fuel_per_kwh * gen + inst.c_deg * dch + inst.voll * unmet
    return cost


def total_cost_optimal(inst: ToyInstance, n_pv: int, n_batt: int,
                       days: int = 365) -> float:
    """Exact annualised Z_opt(x) = capex + days * cost-optimal day (caps pinned)."""
    cp, cb = n_pv * inst.u_pv, n_batt * inst.u_batt
    return cost_optimal_relaxation(inst, (cp, cp), (cb, cb), days)


def total_cost_rule(inst: ToyInstance, n_pv: int, n_batt: int,
                    days: int = 365) -> float:
    """Annualised Z_rule(x) = capex + days * rule-based day."""
    op = rule_dispatch(inst, n_pv * inst.u_pv, n_batt * inst.u_batt)
    return inst.capex_annualised(n_pv, n_batt) + days * op


def default_instance() -> ToyInstance:
    """A small but realistic single-day instance (evening-peak village load)."""
    h = np.arange(24)
    demand = np.array([3, 2.6, 2.4, 2.3, 2.4, 2.8, 3.6, 4.2, 4.0, 3.6, 3.4, 3.5,
                       3.6, 3.4, 3.2, 3.3, 3.8, 5.2, 6.4, 6.8, 6.0, 5.0, 4.0, 3.4])
    pv_unit = np.clip(np.exp(-((h - 12.5) / 3.1) ** 2) - 0.03, 0, None)
    return ToyInstance(demand=demand, pv_unit=pv_unit)


# ===========================================================================
# Parameterised causal controller class (formulation Section "Refining the
# controller: a parameterised rule class").
# ===========================================================================
from dataclasses import dataclass as _dataclass  # noqa: E402


@_dataclass
class ParametricRule:
    """A causal controller theta = (e_on, e_off, sigma_ge, gamma).

    * ``e_on, e_off``  -- generator commitment hysteresis band (SOC fractions of usable
      capacity); start below ``e_on``/when the battery cannot cover the deficit, run until
      ``e_off``.
    * ``sigma_ge``     -- generator setpoint (fraction of rating); the power beyond the
      served deficit charges the battery (cycle-charging when large).
    * ``gamma``        -- night-reserve multiplier; ``R = gamma * remaining-night demand``.
    """

    e_on: float = 0.05
    e_off: float = 0.06
    sigma_ge: float = config.GEN_MIN_LOAD_FRAC
    gamma: float = 0.5
    name: str = "custom"


def rule_dispatch_param(inst: ToyInstance, cap_pv: float, cap_batt: float,
                        rule: ParametricRule) -> float:
    """Daily operating cost [$/day] of the parameterised controller (with F0).

    Feasible by construction (no simultaneous charge/discharge, respects the minimum
    loading and SOC trips), so Proposition 1 applies: the value is >= the MILP
    cost-optimal value at the same capacity.
    """
    H = inst.H
    rem = _remaining_night(inst)                     # remaining-night demand [kWh]
    phi = config.GEN_MIN_LOAD_FRAC
    e = 0.5 * inst.e_hi * cap_batt
    floor_abs, cap_abs = inst.e_lo * cap_batt, inst.e_hi * cap_batt
    gen_on, cost = False, 0.0
    for h in range(H):
        pv = inst.pv_unit[h] * cap_pv
        served = min(pv, inst.demand[h])
        surplus, deficit = pv - served, inst.demand[h] - served
        inv_avail = inst.cap_inv

        # 1) PV surplus charges the battery
        room = cap_abs - e
        chg = min(surplus, inv_avail, room / inst.eta_c if inst.eta_c else 0.0)
        e += inst.eta_c * chg
        inv_avail -= chg

        reserve = min(max(floor_abs, rule.gamma * rem[h]), cap_abs)
        avail_dis = max(e - reserve, 0.0) * inst.eta_d
        batt_cover = min(deficit, inv_avail, avail_dis)

        # 2) commitment (hysteresis + need / preemptive start)
        if gen_on:
            if e >= rule.e_off * cap_abs:
                gen_on = False
        if not gen_on and (batt_cover < deficit - 1e-9 or e < rule.e_on * cap_abs):
            gen_on = True

        # 3) act
        if gen_on:
            rated = inst.cap_ge
            P_ge = min(rated, max(deficit, rule.sigma_ge * rated))
            dis = 0.0
            if P_ge >= deficit:                       # serve load + charge surplus
                gen_surplus = P_ge - deficit
                target_room = max(0.0, rule.e_off * cap_abs - e)
                ch_ge = min(gen_surplus, inv_avail,
                            (cap_abs - e) / inst.eta_c, target_room / inst.eta_c)
                e += inst.eta_c * ch_ge
                output, unmet = deficit + ch_ge, 0.0
            else:                                     # rated < deficit: battery helps
                rem_def = deficit - P_ge
                dis = min(rem_def, inv_avail, max(e - reserve, 0.0) * inst.eta_d)
                e -= dis / inst.eta_d
                output, unmet = P_ge, rem_def - dis
            billed = max(output, phi * rated)         # minimum-loading fuel
            cost += (inst.fuel_fixed + inst.fuel_per_kwh * billed
                     + inst.c_deg * dis + inst.voll * unmet)
        else:
            dis = min(deficit, inv_avail, avail_dis)
            e -= dis / inst.eta_d
            cost += inst.c_deg * dis + inst.voll * (deficit - dis)
    return cost


def cost_optimal_dispatch_milp(inst: ToyInstance, cap_pv: float,
                               cap_batt: float, days: int = 1) -> float:
    """Tight cost-optimal daily operating cost WITH the fixed fuel intercept.

    Adds a generator-commitment binary and the F0 term, so it shares the exact cost
    structure of the parameterised rule. By Proposition 1 it lower-bounds every
    :func:`rule_dispatch_param` value at the same capacity.
    """
    from scipy.optimize import milp, LinearConstraint, Bounds

    H = inst.H
    ge, ch, dis, q, ell, e, y = 0, H, 2 * H, 3 * H, 4 * H, 5 * H, 6 * H + 1
    nvars = 7 * H + 1
    phi = config.GEN_MIN_LOAD_FRAC
    e0 = 0.5 * inst.e_hi * cap_batt

    c = np.zeros(nvars)
    c[ge:ge + H] = days * inst.fuel_per_kwh
    c[dis:dis + H] = days * inst.c_deg
    c[ell:ell + H] = days * inst.voll
    c[y:y + H] = days * inst.fuel_fixed

    lb = np.zeros(nvars)
    ub = np.full(nvars, np.inf)
    for h in range(H):
        ub[ge + h] = inst.cap_ge
        ub[ch + h] = inst.cap_inv
        ub[dis + h] = inst.cap_inv
        ub[q + h] = inst.pv_unit[h] * cap_pv
        ub[ell + h] = inst.demand[h]
        ub[y + h] = 1.0
    lb[e:e + H + 1] = inst.e_lo * cap_batt
    ub[e:e + H + 1] = inst.e_hi * cap_batt

    integrality = np.zeros(nvars)
    integrality[y:y + H] = 1

    A_eq, b_eq = [], []
    for h in range(H):                                # balance
        row = np.zeros(nvars)
        row[ge + h] = 1; row[dis + h] = 1; row[ch + h] = -1
        row[q + h] = -1; row[ell + h] = 1
        A_eq.append(row); b_eq.append(inst.demand[h] - inst.pv_unit[h] * cap_pv)
    for h in range(H):                                # storage dynamics
        row = np.zeros(nvars)
        row[e + h + 1] = 1; row[e + h] = -1
        row[ch + h] = -inst.eta_c; row[dis + h] = 1.0 / inst.eta_d
        A_eq.append(row); b_eq.append(0.0)
    row = np.zeros(nvars); row[e] = 1; A_eq.append(row); b_eq.append(e0)

    A_ub, ub_ub = [], []
    for h in range(H):                                # P_ge <= cap_ge * y
        row = np.zeros(nvars); row[ge + h] = 1; row[y + h] = -inst.cap_ge
        A_ub.append(row); ub_ub.append(0.0)
    for h in range(H):                                # P_ge >= phi*cap_ge*y
        row = np.zeros(nvars); row[ge + h] = -1; row[y + h] = phi * inst.cap_ge
        A_ub.append(row); ub_ub.append(0.0)

    cons = [LinearConstraint(np.array(A_eq), b_eq, b_eq),
            LinearConstraint(np.array(A_ub), -np.inf, ub_ub)]
    res = milp(c, integrality=integrality, bounds=Bounds(lb, ub), constraints=cons)
    if not res.success:
        raise RuntimeError(f"MILP failed: {res.message}")
    return float(res.fun)
