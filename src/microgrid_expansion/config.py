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

from .settings import best_available_solver, default_settings

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

PV_LIFETIME_Y = _S.photovoltaic.lifetime_years
INV_LIFETIME_Y = _S.inverter.lifetime_years
GEN_LIFETIME_Y = max(_S.generators, key=lambda g: g.rating_kw).lifetime_years

# --- photovoltaic-side conversion (charge controllers or string inverters) --
COUPLING_ARCHITECTURE = _S.coupling.architecture
CONV_STRING_USD_KW = _S.coupling.string_inverter_cost_usd_kw
CONV_OM_RATE = _S.coupling.om_rate
CONV_LIFETIME_Y = _S.coupling.lifetime_years
DC_AC_RATIO_MAX = _S.coupling.dc_ac_ratio_max      # array per kW of hybrid inverter
AC_RATIO_MAX = _S.coupling.ac_ratio_max
AC_DOUBLE_CONVERSION_EFF = _S.coupling.ac_double_conversion_efficiency

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

# --- distribution network (see settings.InfrastructureSpec) -----------------
NETWORK_LOSS_FRACTION = _S.infrastructure.network_loss_fraction



@dataclass
class ModelConfig:
    """Top-level configuration for one model run."""

    # --- What is being sized ---
    site: str = "Samionta"

    # --- Stage calendar (milestone years, relative to commissioning) ---
    stage_years: tuple[int, ...] = (0, 5, 10, 15, 20)

    # --- Scenario-tree shape ---
    n_mc_paths: int = 1000               # Monte-Carlo paths drawn before reduction
    branching: tuple[int, ...] = (1, 3, 2, 2, 2)  # children per stage (root first)
    seed: int = 0
    # How the reduced outcomes are nested. ``fan`` reduces each stage over the whole
    # ensemble and gives every node of a stage the same children, which is the tree every
    # stored result was drawn on; along one of its paths the growth trajectory and the cost
    # future can change from one milestone to the next. ``persistent`` branches over regimes
    # -- the connection trajectory, the growth trajectory and the cost future of a path --
    # at the first milestone after the root and holds each regime below its branch.
    # ``branching`` shapes the fan; ``regime_branches``, ``regime_fan`` and ``root_period``
    # shape the persistent tree.
    tree_mode: str = "fan"
    # Regime branches below the root. When the ensemble holds more regimes, they are reduced
    # to this many medoid regimes, each carrying the mass of its cluster.
    regime_branches: int = 9
    # Children per stage within a regime, root first. Ones throughout: climate and the
    # year-to-year variability then enter through each regime's medoid outcome, and the
    # programme keeps the forty-six nodes of the fan.
    regime_fan: tuple[int, ...] = (1, 1, 1, 1, 1)
    # Who operates the root's span in a persistent tree. ``regimes``: one node per regime
    # branch, holding the root's plant and investing nothing, so the year-0 plant is
    # operated under every regime it may meet; the root then invests and does not operate.
    # ``root``: the root operates it on the medoid of the whole ensemble, as in the fan.
    root_period: str = "regimes"
    # Centre the stage features before scaling them, and set a channel that does not vary to
    # zero (``tree.reduce._scaled``). Without it a constant channel -- the prices at year 0,
    # where every cost future starts from the same ones -- is divided by a spread of pure
    # rounding, and the distances the medoids are chosen by all come out zero: the fan's
    # root is then the first path drawn, not the medoid of year 0. Off for the fan, which
    # every stored result was drawn with, until session 4 recomputes them; the persistent
    # tree always centres, since within one cost future the prices are constant at every
    # stage and none of its medoids would otherwise be one.
    centre_features: bool = False
    # The year of its span whose demand a node carries. ``first`` is the milestone's own
    # year, which every stored result used; ``last`` is the span's last year, the most
    # demanding one of a village still connecting. Only the demand moves: the yield, the
    # temperature and the prices remain the milestone's.
    node_year: str = "first"

    # --- Time-domain reduction ---
    # Sixty-four days, which is what produced every stored tree result: 777 538 columns
    # over forty-six nodes and eleven flow variables is 1 536 steps a node, and 1 536 hours
    # is sixty-four days. The default read eight and the command line read 365, neither of
    # them the figure the results came from, and at 365 the programme grows sevenfold --
    # 5.6 million columns and sixteen gigabytes -- for a bound whose compression error is
    # measured and reported anyway.
    n_rep_days: int = 64                 # 365 or more is the whole year

    # --- Horizon and discounting, shared with the project settings ---
    # Copies, not second sources: the tree is drawn before a settings object exists, so the
    # calendar and the rate have to be here too. The project's figures govern, and
    # ``model.economics.check_one_discount_rate`` refuses a copy that disagrees rather than
    # letting a twelve-per-cent future be met with an eight-per-cent plant.
    horizon_years: int = PROJECT_YEARS
    discount_rate: float = DISCOUNT_RATE

    # The operating layer once offered a second, "rule-faithful", encoding which added the
    # night-reserve floor to the cost objective and claimed to reproduce the field
    # controller. It is gone: the rule trajectory sits below that floor in four to sixty
    # per cent of the hours, so the constraint excludes the behaviour it claims to encode,
    # and a programme minimising over a whole horizon is anticipative where the controller
    # is causal. The controller is simulated instead, which is the premise of the method.

    # --- Solver ---
    # The name only. The time limit, the tolerance and the thread count live in
    # ``settings.solver``, which the interface edits and ``solve.driver`` reads; they were
    # here as well, read by nobody, which is how a limit comes to be declared twice and
    # applied never.
    solver: str = field(default_factory=best_available_solver)

    # --- Modular unit sizes (PV, battery, inverter) ---
    pv_unit_kw: float = PV_UNIT_KW
    batt_unit_kwh: float = BATT_UNIT_KWH
    inv_unit_kw: float = INV_UNIT_KW

    # --- Generator (single unit, catalogue, upgrades only) ---
    gen_catalog_kw: tuple[float, ...] = GEN_CATALOG_KW
    gen_salvage_frac: float = GEN_SALVAGE_FRAC

    # The plant already standing is declared with the village, in
    # ``settings.InstalledPlant``, not here. It was declared here as well -- four figures no
    # module read -- and the generator's default was the smallest set in the catalogue, so
    # the day anything read it every greenfield plan would have started with a generating
    # set nobody had bought.

    # --- Age of the village the tree starts from ---
    # The village age at year 0: whole months since the site's first customer connection.
    # The plan ages the community from this, milestone by milestone. Under the whole census
    # every household is that old, which is what the figure meant before households joined
    # in cohorts; under progressive connection each cohort is younger by the month it
    # joined in. Held here for the same reason as the horizon: the tree is drawn before a
    # settings object exists, and a plan built from a one-year-old village is the wrong
    # plan for a village being connected next month. A brownfield site with its own record
    # derives its age from the roster instead, and this is then not read.
    maturity_months: int = 12

    # --- The network between the plant and the customer ---
    # Share of the energy injected that the distribution network consumes. Held here as
    # well as in the project settings, for the same reason the horizon and the discount
    # rate are: the tree is drawn before a settings object exists, and the demand it draws
    # is the demand the plant must produce. The default is read from the project's, so the
    # two cannot disagree: a plan and the certificate of its first year would otherwise be
    # sized for different demands.
    network_loss_fraction: float = NETWORK_LOSS_FRACTION

    def spans(self) -> tuple[int, ...]:
        """Operating years each milestone stands for: to the next one, or to the horizon."""
        years = list(self.stage_years)
        return tuple(max(int((years[k + 1] if k + 1 < len(years)
                              else int(self.horizon_years)) - year), 1)
                     for k, year in enumerate(years))

    def demand_year(self, stage: int) -> int:
        """The year of a milestone's span whose demand its node carries (``node_year``)."""
        year = int(self.stage_years[stage])
        return year if self.node_year == "first" else year + self.spans()[stage] - 1

    def validate(self) -> None:
        """Check internal consistency (stage count vs branching, etc.)."""
        if len(self.branching) != len(self.stage_years):
            raise ValueError(
                "branching must have one entry per stage in stage_years"
            )
        if self.branching and self.branching[0] != 1:
            raise ValueError("the first stage is the here-and-now decision and holds one "
                             "node; branching starts after it")
        if self.n_rep_days < 1:
            raise ValueError("a node needs at least one representative day")
        if self.tree_mode not in ("fan", "persistent"):
            raise ValueError(f"tree_mode is 'fan' or 'persistent', not {self.tree_mode!r}")
        if self.node_year == "both":
            # Two operating years per node would change how the programme is indexed, for a
            # bias that ``first`` and ``last`` already bracket.
            raise ValueError(
                "node_year 'both' is not built: it would give every node two operating "
                "years, which changes how the programme is indexed, and 'first' and "
                "'last' already bracket the bias it would measure; run both of those")
        if self.node_year not in ("first", "last"):
            raise ValueError(f"node_year is 'first' or 'last', not {self.node_year!r}")
        if self.tree_mode == "persistent":
            if len(self.regime_fan) != len(self.stage_years):
                raise ValueError("regime_fan must have one entry per stage in stage_years")
            if self.regime_fan[0] != 1:
                raise ValueError("the first stage is the here-and-now decision and holds "
                                 "one node; a regime's fan starts after it")
            if min(self.regime_fan) < 1 or self.regime_branches < 1:
                raise ValueError("a regime needs at least one branch and one child a stage")
            if self.root_period not in ("regimes", "root"):
                raise ValueError(
                    f"root_period is 'regimes' or 'root', not {self.root_period!r}")


def crf(r: float = DISCOUNT_RATE, n: int = PROJECT_YEARS) -> float:
    """Capital recovery factor r(1+r)^n / ((1+r)^n - 1)."""
    return r * (1 + r) ** n / ((1 + r) ** n - 1)


def battery_degradation_cost() -> float:
    """Battery throughput-degradation cost c^deg [$/kWh discharged]."""
    throughput = BATT_CYCLES * (SOC_MAX_FRAC - SOC_MIN_FRAC)  # per kWh of capacity
    return BATT_COST_USD_KWH / throughput
