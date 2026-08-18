"""Stochastic generator of community load profiles.

Turns the calibrated demand model into the 8760-hour series the sizing model consumes.
One draw proceeds in three steps:

1. **Composition.** For each calendar month and each socio-economic category, the
   households of the community are allocated across behavioural states by a multinomial
   draw from the posterior mixture law :math:`P(C \\mid T=t, m)`. Using the twelve
   monthly laws rather than a single annual one keeps the seasonal variation of
   behaviour, which is what drives the seasonal variation of the storage requirement.
2. **Usage.** Each behavioural archetype is instantiated as a RAMP user carrying the
   appliance parameters calibrated for that archetype, and its households' appliance
   usage is simulated at minute resolution over the days of the month.
3. **Aggregation.** The minute-resolution community load is averaged to hourly power and
   the twelve months are concatenated into a calendar year.

The states ``inactive`` and ``outlier`` need interpretation. ``inactive`` is a genuine
behavioural state -- a connected household with no measured consumption -- and
contributes a zero profile. ``outlier`` is not a behavioural class but the residue of
observations excluded from the segmentation; its (small) mass is redistributed over the
four archetypes in proportion to their probabilities, since leaving it out would
silently shrink the community.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..paths import REFERENCE_DIR
from ..sites import Site

#: Behavioural archetypes carrying calibrated appliance parameters.
ARCHETYPES = ("0", "1", "2", "3")
#: States present in the mixture law that are not behavioural archetypes.
INACTIVE = "inactive"
OUTLIER = "outlier"

MINUTES_PER_DAY = 1440
HOURS_PER_DAY = 24

#: Random spread applied by RAMP to each appliance's total daily usage time.
TIME_VARIABILITY = 0.2
#: Random spread applied to each end of an appliance's window of use. RAMP shifts both
#: bounds independently by up to ``WINDOW_VARIABILITY x width``, so in the worst case the
#: usable window shrinks to ``(1 - 2 x WINDOW_VARIABILITY)`` of its nominal width, and it
#: then refuses any duty cycle longer than 99 % of what remains.
WINDOW_VARIABILITY = 0.15


# ---------------------------------------------------------------------------
# Calibrated inputs
# ---------------------------------------------------------------------------
def load_monthly_mixture(site: Site) -> pd.DataFrame:
    """Posterior mixture law by calendar month and household category.

    The calibration is estimated per observed year-month; several years may cover the
    same calendar month. They are pooled by averaging the posterior probabilities, which
    keeps each observed year equally informative about the season it documents rather
    than letting the longest-observed year dominate.

    Returns a frame indexed by ``(month, customer_type)`` with one column per state,
    each row summing to one.
    """
    table = pd.read_csv(REFERENCE_DIR / "mixture_probabilities_type_month.csv")
    table = table[table["site_name"] == site.name].copy()
    if table.empty:
        raise ValueError(f"no calibrated mixture for site {site.name!r}")

    table["cluster"] = table["cluster"].astype(str)
    table["calendar_month"] = pd.PeriodIndex(table["month"], freq="M").month

    pooled = (table.groupby(["calendar_month", "customer_type", "cluster"])["p_shrunk"]
              .mean()
              .unstack("cluster")
              .fillna(0.0))
    pooled = pooled.div(pooled.sum(axis=1), axis=0)
    pooled.index.names = ["month", "customer_type"]
    return pooled


def load_archetype_appliances() -> dict[str, pd.DataFrame]:
    """Calibrated appliance parameters, one frame of parameters per archetype."""
    table = pd.read_csv(REFERENCE_DIR / "cluster_params.csv")
    table["cluster"] = table["cluster"].astype(str)
    out: dict[str, pd.DataFrame] = {}
    for archetype, group in table.groupby("cluster"):
        out[archetype] = group.pivot(index="appliance", columns="parameter",
                                     values="value")
    missing = set(ARCHETYPES) - set(out)
    if missing:
        raise ValueError(f"no appliance calibration for archetype(s) {sorted(missing)}")
    return out


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------
def _redistribute_outliers(weights: pd.Series) -> pd.Series:
    """Fold the ``outlier`` mass into the archetypes, keeping ``inactive`` intact."""
    weights = weights.copy()
    residue = float(weights.get(OUTLIER, 0.0))
    weights = weights.drop(labels=[OUTLIER], errors="ignore")
    archetype_mass = float(weights.reindex(ARCHETYPES).fillna(0.0).sum())
    if residue > 0 and archetype_mass > 0:
        for archetype in ARCHETYPES:
            share = float(weights.get(archetype, 0.0)) / archetype_mass
            weights[archetype] = weights.get(archetype, 0.0) + residue * share
    elif residue > 0:
        # No archetype carries any mass: the residue can only join the inactive state.
        weights[INACTIVE] = weights.get(INACTIVE, 0.0) + residue
    total = weights.sum()
    return weights / total if total > 0 else weights


def sample_composition(
    mixture: pd.DataFrame,
    census: dict[str, int],
    month: int,
    rng: np.random.Generator,
    by_maturity: bool = False,
) -> dict[str, int]:
    """Draw how many households of the community sit in each behavioural state.

    Households of every socio-economic category are allocated by a multinomial draw from
    that category's monthly mixture law, and the categories are then pooled: what the
    micro-grid sees is the community's aggregate composition, not its social structure.
    """
    counts: dict[str, int] = {state: 0 for state in (*ARCHETYPES, INACTIVE)}
    for customer_type, n_households in census.items():
        if n_households <= 0:
            continue
        try:
            weights = mixture.loc[customer_type] if by_maturity \
                else mixture.loc[(month, customer_type)]
        except KeyError:
            # No calibration for this category: fall back to the law averaged over the
            # categories rather than dropping the households.
            weights = (mixture.mean(axis=0) if by_maturity
                       else mixture.xs(month, level="month").mean(axis=0))
        weights = _redistribute_outliers(weights)
        states = list(weights.index)
        draw = rng.multinomial(n_households, weights.to_numpy())
        for state, n in zip(states, draw):
            counts[state] = counts.get(state, 0) + int(n)
    return counts


# ---------------------------------------------------------------------------
# Usage simulation
# ---------------------------------------------------------------------------
def _appliance_spec(row: pd.Series,
                    power_scale: float = 1.0,
                    time_scale: float = 1.0) -> dict | None:
    """Turn one calibrated appliance row into RAMP arguments, or ``None`` if unusable.

    Two calibrated quantities need care. The mean appliance count is fractional -- it is
    an average over the households of an archetype -- and rounding it would bias the
    community's equipment; it is therefore returned as a mean and realised per household.
    The window randomisation is capped so that it never shrinks the window below the
    calibrated usage time: for appliances whose duty nearly fills their window, RAMP would
    otherwise refuse the appliance or silently truncate its energy.
    """
    power = float(row.get("power", 0.0)) * float(power_scale)
    func_time = float(row.get("func_time", 0.0)) * float(time_scale)
    if not (np.isfinite(power) and power > 0 and np.isfinite(func_time) and func_time > 0):
        return None

    start = row.get("w1_start", 0.0)
    end = row.get("w1_end", MINUTES_PER_DAY)
    start = 0 if not np.isfinite(start) else int(np.clip(round(float(start)), 0, MINUTES_PER_DAY))
    end = MINUTES_PER_DAY if not np.isfinite(end) else int(np.clip(round(float(end)), 0, MINUTES_PER_DAY))
    if end <= start:                                   # degenerate window -> whole day
        start, end = 0, MINUTES_PER_DAY
    width = end - start

    func_time = int(min(round(func_time), int(0.99 * width)))
    if func_time <= 0:
        return None

    # Largest window randomisation that still leaves room for the calibrated usage.
    slack = 1.0 - func_time / (0.99 * width)
    window_var = float(np.clip(slack / 2.0, 0.0, WINDOW_VARIABILITY))

    func_cycle = row.get("func_cycle", 1.0)
    func_cycle = 1 if not np.isfinite(func_cycle) else max(1, int(round(float(func_cycle))))
    func_cycle = max(1, min(func_cycle, func_time))

    mean_number = row.get("number", 1.0)
    mean_number = 1.0 if not np.isfinite(mean_number) else max(0.0, float(mean_number))

    occasional = row.get("occasional_use", 1.0)
    occasional = 1.0 if not np.isfinite(occasional) else float(np.clip(occasional, 0.0, 1.0))

    return {
        "name": str(row.name),
        "power": power,
        "mean_number": mean_number,
        "func_time": func_time,
        "func_cycle": func_cycle,
        "occasional_use": occasional,
        "window": [start, end],
        "window_var": window_var,
    }


def _realise_count(mean_number: float, rng: np.random.Generator) -> int:
    """Draw a household's appliance count with the calibrated mean as its expectation."""
    base = int(np.floor(mean_number))
    return base + int(rng.random() < (mean_number - base))


def _build_households(
    archetype: str,
    n_households: int,
    appliances: pd.DataFrame,
    rng: np.random.Generator,
    scaling: "ArchetypeScaling | None" = None,
) -> list:
    """One RAMP user per household, with appliance counts drawn per household.

    Instantiating households individually rather than as a single user class of
    ``n_households`` members is what allows the fractional calibrated appliance counts to
    be honoured in expectation: a mean of 1.33 lamps becomes a third of the households
    owning two and two thirds owning one, instead of every household owning one.
    """
    from ramp import User

    power_scale, time_scale = (1.0, 1.0) if scaling is None else scaling.factors(archetype)
    specs = [spec for _, row in appliances.iterrows()
             if (spec := _appliance_spec(row, power_scale, time_scale)) is not None]
    users = []
    for household in range(int(n_households)):
        user = User(user_name=f"C{archetype}_{household}", num_users=1)
        has_appliance = False
        for spec in specs:
            number = _realise_count(spec["mean_number"], rng)
            if number <= 0:
                continue
            appliance = user.add_appliance(
                number=number,
                power=spec["power"],
                func_time=spec["func_time"],
                func_cycle=spec["func_cycle"],
                occasional_use=spec["occasional_use"],
                time_fraction_random_variability=TIME_VARIABILITY,
                name=spec["name"],
            )
            appliance.windows(window_1=spec["window"], random_var_w=spec["window_var"])
            has_appliance = True
        if has_appliance:
            users.append(user)
    return users


def _simulate_month(
    counts: dict[str, int],
    appliances_by_archetype: dict[str, pd.DataFrame],
    year: int,
    month: int,
    seed: int,
    rng: np.random.Generator,
    scaling: "ArchetypeScaling | None" = None,
) -> np.ndarray:
    """Minute-resolution community load [W] over one calendar month."""
    from ramp import UseCase

    n_days = calendar.monthrange(year, month)[1]
    users: list = []
    for archetype in ARCHETYPES:
        n = counts.get(archetype, 0)
        if n > 0:
            users.extend(_build_households(archetype, n,
                                           appliances_by_archetype[archetype], rng,
                                           scaling))
    if not users:                              # every household inactive this month
        return np.zeros(n_days * MINUTES_PER_DAY)

    start = f"{year}-{month:02d}-01"
    end = f"{year}-{month:02d}-{n_days:02d}"
    use_case = UseCase(users=users, date_start=start, date_end=end, random_seed=seed)
    profile = np.asarray(use_case.generate_daily_load_profiles(), dtype=float).ravel()

    expected = n_days * MINUTES_PER_DAY
    if profile.size != expected:               # guard against a silent shape change
        raise RuntimeError(
            f"RAMP returned {profile.size} minutes for {n_days} days ({expected} expected)"
        )
    return profile


def _to_hourly_kw(minutes: np.ndarray) -> np.ndarray:
    """Average a minute-resolution series in W into hourly mean power in kW."""
    return minutes.reshape(-1, 60).mean(axis=1) / 1000.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ArchetypeScaling:
    """Moment-matching correction applied to each archetype's appliance set.

    The calibrated appliance parameters do not, on their own, reproduce the daily energy
    and peak power measured for the archetypes they describe (see
    :mod:`microgrid_expansion.demand.calibration`). Two factors per archetype reconcile
    them: ``power`` scales every appliance's rated power, which moves the peak and the
    energy together, and ``time`` scales every appliance's usage duration, which moves the
    energy alone. Two targets, two degrees of freedom.

    The factors are data, not a hidden fudge: they are stored alongside the calibration
    and reported, so the size of the underlying calibration gap stays visible.
    """

    power: dict[str, float] = field(default_factory=dict)
    time: dict[str, float] = field(default_factory=dict)

    def factors(self, archetype: str) -> tuple[float, float]:
        return (float(self.power.get(archetype, 1.0)),
                float(self.time.get(archetype, 1.0)))

    @classmethod
    def identity(cls) -> "ArchetypeScaling":
        """No correction: the appliance parameters are used exactly as calibrated."""
        return cls()

    @classmethod
    def load(cls, path=None) -> "ArchetypeScaling":
        """Read the fitted factors, falling back to no correction if absent."""
        path = REFERENCE_DIR / "archetype_scaling.csv" if path is None else path
        if not path.exists():
            return cls.identity()
        table = pd.read_csv(path)
        table["cluster"] = table["cluster"].astype(str)
        return cls(power=dict(zip(table["cluster"], table["power_scale"])),
                   time=dict(zip(table["cluster"], table["time_scale"])))


@dataclass
class DemandYear:
    """One stochastic realisation of a community's demand over a calendar year."""

    site: str
    year: int
    seed: int
    hourly_kw: np.ndarray                       # 8760 (or 8784) hourly mean power [kW]
    composition: dict[int, dict[str, int]] = field(default_factory=dict)

    @property
    def annual_energy_kwh(self) -> float:
        return float(self.hourly_kw.sum())

    @property
    def peak_kw(self) -> float:
        return float(self.hourly_kw.max())

    @property
    def load_factor(self) -> float:
        peak = self.peak_kw
        return float(self.hourly_kw.mean() / peak) if peak > 0 else 0.0

    def monthly_energy_kwh(self) -> pd.Series:
        """Energy delivered in each calendar month [kWh]."""
        index = pd.date_range(f"{self.year}-01-01", periods=self.hourly_kw.size,
                              freq="h")
        return pd.Series(self.hourly_kw, index=index).groupby(index.month).sum()


def simulate_demand_year(
    site: Site,
    year: int = 2025,
    seed: int = 0,
    maturity_months: int = 0,
    trajectory: str = "centrale",
    scaling: ArchetypeScaling | None = None,
    apply_seasonality: bool = True,
) -> DemandYear:
    """Draw one community load profile for ``site`` over the calendar year ``year``.

    The behavioural composition is resolved from the *maturity* of the connection rather
    than from the site's identity, so a locality with no meter record of its own can be
    simulated from its census alone -- which is the situation of every site the model is
    meant to size. ``maturity_months`` is the age of the connection at the start of the
    simulated year, and the community ages month by month through it.

    ``trajectory`` selects which of the observed growth behaviours to apply; the two
    reference villages bracket a factor of two after two years, so a sizing should be
    computed under both bounds rather than under the central case alone. Genuine calendar
    seasonality is restored afterwards through the residual seasonal index, the part of the
    monthly variation that survives conditioning on maturity.
    """
    from .growth import maturity_band, seasonal_index, trajectory_law

    law = trajectory_law(trajectory)
    appliances = load_archetype_appliances()
    scaling = ArchetypeScaling.load() if scaling is None else scaling
    season = seasonal_index() if apply_seasonality else None
    rng = np.random.default_rng(seed)

    hourly: list[np.ndarray] = []
    composition: dict[int, dict[str, int]] = {}
    for month in range(1, 13):
        band = maturity_band(maturity_months + month - 1)
        weights = law.xs(band, level="maturity")
        counts = sample_composition(weights, site.census, month, rng,
                                    by_maturity=True)
        composition[month] = counts
        minutes = _simulate_month(counts, appliances, year, month,
                                  seed=int(rng.integers(0, 2**31 - 1)), rng=rng,
                                  scaling=scaling)
        profile = _to_hourly_kw(minutes)
        if season is not None:
            profile = profile * float(season.get(month, 1.0))
        hourly.append(profile)

    return DemandYear(
        site=site.name,
        year=year,
        seed=seed,
        hourly_kw=np.concatenate(hourly),
        composition=composition,
    )
