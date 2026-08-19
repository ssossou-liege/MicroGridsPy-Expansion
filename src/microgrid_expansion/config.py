"""Named constants, derived from the project settings.

Every technical and economic quantity here is read from
:mod:`microgrid_expansion.settings`, which is the single place a project declares them.
This module exists only so that the symbols of the formulation keep short, stable names in
the code; it holds no values of its own.

Declaring these twice is not a style question. A second linear fuel model once lived here
and disagreed with the fitted efficiency curve by 59 % on its intercept; an inverter price
and a value of lost load once lived here and silently overrode the ones a user had supplied.
Both were found by comparing the two copies, which is not a discipline worth relying on.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .settings import default_settings

_S = default_settings()

# --- economics (see settings.EconomicSettings) ------------------------------
DISCOUNT_RATE = _S.economics.discount_rate            # r
PROJECT_YEARS = _S.economics.horizon_years            # planning horizon [yr]
DIESEL_PRICE_USD_L = _S.economics.diesel_price_usd_l  # c^fuel
VOLL_USD_KWH = _S.economics.value_of_lost_load_usd_kwh
TARIFF_USD_KWH = _S.economics.tariff_usd_kwh

# --- capital and maintenance (see the equipment specifications) -------------
PV_COST_USD_KW = _S.photovoltaic.cost_usd_kw          # C^inv_pv
BATT_COST_USD_KWH = _S.battery.cost_usd_kwh           # C^inv_batt
INV_COST_USD_KW = _S.inverter.cost_usd_kw             # C^inv_inv
GEN_COST_USD_KVA = max(_S.generators, key=lambda g: g.rating_kw).cost_usd_kw

PV_OM_RATE = _S.photovoltaic.om_rate                  # O_pv
BATT_OM_RATE = _S.battery.om_rate                     # O_batt
INV_OM_RATE = _S.inverter.om_rate                     # O_inv
GEN_OM_RATE = max(_S.generators, key=lambda g: g.rating_kw).om_rate

# --- storage ----------------------------------------------------------------
BATTERY_CHEMISTRY = _S.battery.chemistry
BATT_CYCLES = _S.battery.cycles
BATT_LIFETIME_Y = _S.battery.lifetime_years
ETA_CHARGE = _S.battery.charge_efficiency             # eta^c
ETA_DISCHARGE = _S.battery.discharge_efficiency       # eta^d
SOC_MIN_FRAC = _S.battery.soc_min                     # underline{e}
SOC_MAX_FRAC = _S.battery.soc_max                     # overline{e}

# --- generator --------------------------------------------------------------
GEN_MIN_LOAD_FRAC = min(g.min_load_fraction for g in _S.generators)   # phi^ge
GEN_CATALOG_KW = tuple(g.rating_kw for g in _S.generators)            # kappa^ge_s
GEN_SALVAGE_FRAC = max(_S.generators, key=lambda g: g.rating_kw).salvage_fraction

# --- modular unit sizes -----------------------------------------------------
PV_UNIT_KW = _S.photovoltaic.unit_kw                  # u^pv
BATT_UNIT_KWH = _S.battery.unit_kwh                   # u^batt
INV_UNIT_KW = _S.inverter.unit_kw                     # u^inv

# --- brownfield initial condition (existing installed capacity) -------------
INITIAL_PV_KW = 0.0
INITIAL_BATT_KWH = 0.0
INITIAL_INV_KW = 0.0
GEN_INITIAL_KW = GEN_CATALOG_KW[0]


@dataclass
class ModelConfig:
    """Top-level configuration for one model run."""

    # --- Stage calendar (milestone years, relative to commissioning) ---
    stage_years: tuple[int, ...] = (0, 5, 10, 15, 20)

    # --- Scenario-tree shape ---
    n_mc_paths: int = 1000               # Monte-Carlo paths drawn before reduction
    branching: tuple[int, ...] = (1, 3, 2, 2, 2)  # children per stage (root first)
    seed: int = 0

    # --- Time-domain reduction ---
    n_rep_days: int = 8                  # representative days per node

    # --- Operating layer encoding ---
    # "rule_faithful" adds the night-reserve floor (eq. night-reserve);
    # "baseline" uses cost-optimal dispatch within the operating envelope.
    dispatch_variant: str = "rule_faithful"

    # --- Solver ---
    solver: str = "highs"
    time_limit_s: int = 3600
    mip_gap: float = 0.01
    threads: int = 0                     # 0 = solver default

    # --- Modular unit sizes (PV, battery, inverter) ---
    pv_unit_kw: float = PV_UNIT_KW
    batt_unit_kwh: float = BATT_UNIT_KWH
    inv_unit_kw: float = INV_UNIT_KW

    # --- Generator (single unit, catalogue, upgrades only) ---
    gen_catalog_kw: tuple[float, ...] = GEN_CATALOG_KW
    gen_salvage_frac: float = GEN_SALVAGE_FRAC

    # --- Brownfield initial condition (existing installed capacity) ---
    initial_pv_kw: float = INITIAL_PV_KW
    initial_batt_kwh: float = INITIAL_BATT_KWH
    initial_inv_kw: float = INITIAL_INV_KW
    gen_initial_kw: float = GEN_INITIAL_KW

    # --- Storage chemistry ---
    battery_chemistry: str = BATTERY_CHEMISTRY

    # --- Economics ---
    discount_rate: float = DISCOUNT_RATE

    def validate(self) -> None:
        """Check internal consistency (stage count vs branching, etc.)."""
        if len(self.branching) != len(self.stage_years):
            raise ValueError(
                "branching must have one entry per stage in stage_years"
            )
        if self.dispatch_variant not in {"rule_faithful", "baseline"}:
            raise ValueError("dispatch_variant must be 'rule_faithful' or 'baseline'")
        if self.gen_initial_kw not in (0.0, *self.gen_catalog_kw):
            raise ValueError("gen_initial_kw must be 0 or a catalogue size")
        from .battery import CHEMISTRIES
        if self.battery_chemistry not in CHEMISTRIES:
            raise ValueError(
                f"battery_chemistry must be one of {sorted(CHEMISTRIES)}, "
                f"not {self.battery_chemistry!r}")


def crf(r: float = DISCOUNT_RATE, n: int = PROJECT_YEARS) -> float:
    """Capital recovery factor r(1+r)^n / ((1+r)^n - 1)."""
    return r * (1 + r) ** n / ((1 + r) ** n - 1)


def battery_degradation_cost() -> float:
    """Battery throughput-degradation cost c^deg [$/kWh discharged]."""
    throughput = BATT_CYCLES * (SOC_MAX_FRAC - SOC_MIN_FRAC)  # per kWh of capacity
    return BATT_COST_USD_KWH / throughput
