"""Configuration: stage calendar, technology catalogues, economic constants and
solver settings.

Economic and technical constants are those of the reference Benin mini-grid
dispatch assessment, restated here so this repository is self-contained. Symbols map
onto the formulation in ``docs/formulation/model.tex`` as annotated.
"""
from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Economic constants (reference Benin mini-grid dispatch assessment)
# ---------------------------------------------------------------------------
DISCOUNT_RATE = 0.12          # r   -- annual discount rate
PROJECT_YEARS = 25            # planning horizon [yr]

PV_COST_USD_KW = 500.0        # C^inv_pv   [$/kW]
BATT_COST_USD_KWH = 450.0     # C^inv_batt [$/kWh]  (BYD LV Flex LFP)
GEN_COST_USD_KVA = 800.0      # C^inv_ge   [$/kVA]
INV_COST_USD_KW = 150.0       # C^inv_inv  [$/kW]   (placeholder; refine from catalogue)

PV_OM_RATE = 0.018            # O_pv   -- annual O&M as fraction of CAPEX
BATT_OM_RATE = 0.060          # O_batt
GEN_OM_RATE = 0.080           # O_ge
INV_OM_RATE = 0.020           # O_inv

DIESEL_PRICE_USD_L = 1.29     # c^fuel -- central benchmark [$/L]
VOLL_USD_KWH = 2.00           # v      -- value of lost load [$/kWh]

# Generator fuel characteristic (linear): F = F0*y + F1*P_ge  [L/h]
FUEL_F0 = 1.10                # F_0 -- no-load intercept [L/h]
FUEL_F1 = 0.252               # F_1 -- incremental slope [L/kWh]

# Battery degradation cost [$/kWh discharged] = replacement / lifetime throughput
BATT_CYCLES = 6000
BATT_LIFETIME_Y = 16

# ---------------------------------------------------------------------------
# Battery technical parameters
# ---------------------------------------------------------------------------
ETA_CHARGE = 0.975            # eta^c
ETA_DISCHARGE = 0.975         # eta^d
SOC_MIN_FRAC = 0.05           # underline{e}  -- protective discharge trip
SOC_MAX_FRAC = 0.95           # overline{e}   -- protective charge trip

# Generator
GEN_MIN_LOAD_FRAC = 0.30      # phi^ge -- minimum stable loading fraction

# ---------------------------------------------------------------------------
# Capacity increments (modular) and the generator catalogue (single, replaceable unit)
# ---------------------------------------------------------------------------
# Modular technologies: capacity is added in identical units.
PV_UNIT_KW = 0.5              # u^pv   -- rated power of one PV panel [kW]
BATT_UNIT_KWH = 5.0           # u^batt -- usable energy of one battery module [kWh]
INV_UNIT_KW = 2.5             # u^inv  -- rated power of one inverter module [kW]

# Generator: a single unit chosen from a catalogue and replaced (upgrades only).
GEN_CATALOG_KW = (5.0, 10.0, 18.0, 30.0)   # kappa^ge_s [kW]
GEN_SALVAGE_FRAC = 0.40       # V^ge_s -- resale/transfer value as a fraction of capex

# Brownfield initial condition: existing installed capacity at commissioning
# (all zero -> greenfield; GEN_INITIAL_KW must be a catalogue size).
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


def crf(r: float = DISCOUNT_RATE, n: int = PROJECT_YEARS) -> float:
    """Capital recovery factor r(1+r)^n / ((1+r)^n - 1)."""
    return r * (1 + r) ** n / ((1 + r) ** n - 1)


def battery_degradation_cost() -> float:
    """Battery throughput-degradation cost c^deg [$/kWh discharged]."""
    throughput = BATT_CYCLES * (SOC_MAX_FRAC - SOC_MIN_FRAC)  # per kWh of capacity
    return BATT_COST_USD_KWH / throughput
