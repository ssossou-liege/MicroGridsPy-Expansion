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
from dataclasses import dataclass, field, replace

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
    start = 0 if not np.isfinite(start) else int(np.clip(round(float(start)), 0,
                                                        MINUTES_PER_DAY))
    # A window may run past midnight, and the commonest appliance in this calibration does:
    # a dusk-to-dawn security lamp starting at 18:48 and burning for twelve hours. Its end
    # is not recorded, and reading a missing end as "midnight" truncated the window to five
    # hours and the duty with it — which is why the simulated households drew nothing at all
    # between midnight and dawn while the meters show that to be their steadiest load.
    raw_end = row.get("w1_end", np.nan)
    if not np.isfinite(raw_end):
        # No end recorded: the calibrated duty defines it, with a little room to randomise.
        end = start + int(min(round(func_time / 0.9), MINUTES_PER_DAY))
    else:
        end = int(round(float(raw_end)))
        if end <= start:
            end += MINUTES_PER_DAY                     # an explicitly wrapping window

    wrapped: list[int] | None = None
    if end > MINUTES_PER_DAY:
        wrapped = [0, min(end - MINUTES_PER_DAY, start)]
        end = MINUTES_PER_DAY
        if wrapped[1] <= wrapped[0]:
            wrapped = None
    if end <= start:                                   # degenerate window -> whole day
        start, end, wrapped = 0, MINUTES_PER_DAY, None

    width = (end - start) + (wrapped[1] - wrapped[0] if wrapped else 0)

    func_time = int(min(round(func_time), int(0.99 * width)))
    if func_time <= 0:
        return None

    # Largest window randomisation that still leaves room for the calibrated usage.
    slack = 1.0 - func_time / (0.99 * width)
    window_var = float(np.clip(slack / 2.0, 0.0, WINDOW_VARIABILITY))

    func_cycle = row.get("func_cycle", 1.0)
    func_cycle = 1 if not np.isfinite(func_cycle) else max(1, int(round(float(func_cycle))))
    # The shortest stretch a device runs for cannot exceed the duty, nor the window it is
    # confined to. For a window that crosses midnight the bound is the *shorter* of the two
    # segments, not the longer: the simulator places cycles in both, and one too long for
    # the smaller leaves it empty. A dusk-to-dawn street lamp splits into 330 minutes before
    # midnight and 360 after; bounded by 360 only the small hours lit, and bounded by
    # nothing at all the lamp never lit and the use drew zero all month, in silence.
    segments = [end - start] + ([wrapped[1] - wrapped[0]] if wrapped else [])
    func_cycle = max(1, min(func_cycle, func_time, min(s for s in segments if s > 0)))

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
        "window_2": wrapped,
        "window_var": window_var,
    }


def _measured_groups(site, anchored: frozenset[str] = frozenset()):
    """The calibrated classes this village has, grouped by who pays and where they sit.

    Returns a list of ``(counts, calibration, billable, on_network)``, empty when the
    village declares none or the calibration has not been built. The grouping is what lets
    a measured class reach the right series: a place of worship is a customer out on the
    network, the plant's own supply is neither, and one of the three is not an opinion the
    generator holds -- it is read off the calibration table, which says of every class it
    carries who is billed for it and whether a distribution loss reaches it.

    A measured class is present from the first month rather than scaled by how far the line
    has reached: a place of worship predates the grid and is among the first things put on
    it, and the inverter room is air conditioned before a single household is connected.

    A class the developer has described device by device is left out. The two are both
    offered on purpose -- a measured shape for the village that has none of its own, and the
    developer's own figures for the village that knows better -- but they are alternatives,
    and adding both counted one building twice. So is a class in ``anchored``, whose
    buildings a village's record holds one by one at their own levels.
    """
    from .uses import CommunityCalibration

    counted = {**(getattr(site, "community_mix", None) or {}),
               **(getattr(site, "self_mix", None) or {})}
    if not counted:
        return []
    calibration = CommunityCalibration.load()
    if calibration is None:
        return []
    described = {u.key for u in (getattr(site, "declared_uses", None) or ())}
    groups: dict[tuple[bool, bool], dict[str, int]] = {}
    for klass, number in counted.items():
        if int(number) <= 0 or klass in described or klass in anchored:
            continue
        if klass not in calibration.profiles.index:
            continue
        key = (calibration.is_billable(klass), calibration.is_on_network(klass))
        groups.setdefault(key, {})[klass] = int(number)
    # Sorted so that the draws fall in a fixed order whatever a dictionary happens to hold.
    return [(counts, calibration, billable, on_network)
            for (billable, on_network), counts in sorted(groups.items(), reverse=True)]


def _intensity(calibration, band: str, trajectory: str) -> float:
    """Productive users per connected household at a maturity band, as ``sample_units``
    reads it."""
    band = band if band in calibration.intensity.index else calibration.intensity.index[-1]
    column = trajectory if trajectory in calibration.intensity.columns else "central"
    return float(calibration.intensity.loc[band, column])


def _observed_units(calibration, site_name: str, count: int) -> dict[str, int]:
    """A reference village's observed productive users, split by its own measured mix.

    The mix of each reference village is the share of its own metered enterprises in each
    class, so the split of its whole count is that village's state, in whole numbers;
    largest remainders keep the total exact for any other count.
    """
    from .growth import TRAJECTORIES

    column = next((t for t, name in TRAJECTORIES.items() if name == site_name), "central")
    exact = calibration.mix[column] * int(count)
    units = np.floor(exact + 1e-9).astype(int)
    short = int(count) - int(units.sum())
    if short > 0:
        units[(exact - units).sort_values(ascending=False, kind="stable").index[:short]] += 1
    return {klass: int(n) for klass, n in units.items()}


def _declared_counts(site, counts: dict[str, int], connected: int | None = None) -> dict:
    """The declared uses in force this month, with how many of each.

    A community use is there from the start, and so is anything the plant serves for itself:
    the street lighting is lit the night the line is energised, and the inverter room is air
    conditioned before a single household is connected. A productive use waits for the line
    as the calibrated trades do, so its count is scaled by the share of households connected
    and may round to none in the early months. ``connected`` is the households that share
    is taken over; ``None`` counts those outside the inactive state.
    """
    declared = getattr(site, "declared_uses", None)
    if not declared:
        return {}
    from .generator import INACTIVE                      # the key for an unconnected home

    if connected is None:
        connected = sum(v for k, v in counts.items() if k != INACTIVE)
    share = connected / max(getattr(site, "n_households", 0) or 1, 1)
    productive = getattr(site, "productive_mix", None) or {}
    community = getattr(site, "community_mix", None) or {}
    # Street lighting was counted among the community uses before it had a category of its
    # own, so a site saved then is read there as well. One place or the other, never both.
    own = getattr(site, "self_mix", None) or {}

    out = {}
    for use in declared:
        if use.category == "self_consumption":
            count = int(own.get(use.key, community.get(use.key, 0)))
        elif use.category == "community":
            count = int(community.get(use.key, 0))
        else:
            count = int(round(int(productive.get(use.key, 0)) * share))
        if count > 0:
            out[use] = count
    return out


def _declared_use_minutes(uses: dict, year: int, month: int, n_days: int,
                          seed: int) -> np.ndarray | None:
    """Minute-by-minute draw for the uses a developer declared, or ``None`` if there are none.

    These reach RAMP through ``_appliance_spec`` exactly as a calibrated appliance does, so
    a declared device inherits its handling of windows that cross midnight, of duties that
    fill their window, and of the randomisation caps. A use declared with no device, or
    with devices the specification rejects, contributes nothing rather than raising: the
    year must still be buildable while a developer is halfway through describing a village.
    """
    import pandas as pd
    from ramp.core.core import User

    total = np.zeros(n_days * MINUTES_PER_DAY)
    users = []
    for use, count in uses.items():
        if count <= 0 or not use.devices:
            continue
        user = User(user_name=f"use_{use.key}", num_users=int(count))
        attached = False
        for device in use.devices:
            # A device that runs its whole window every day has no behaviour to draw, and
            # drawing one loses energy rather than adding realism: a street lamp put through
            # the appliance library came back with barely half the kilowatt-hours it burns,
            # because the library scatters a duty it was told was stochastic. Such a device
            # is placed exactly instead, minute by minute.
            if device.is_constant:
                total += count * _constant_minutes(device, n_days)
                attached = True            # it contributed, even without reaching RAMP
                continue
            row = pd.Series(device.as_row(), name=device.name)
            spec = _appliance_spec(row)
            if spec is None:
                continue
            appliance = user.add_appliance(
                number=max(1, int(round(spec["mean_number"]))),
                power=spec["power"], func_time=spec["func_time"],
                func_cycle=spec["func_cycle"], occasional_use=spec["occasional_use"],
                time_fraction_random_variability=TIME_VARIABILITY,
                name=spec["name"],
                num_windows=2 if spec.get("window_2") else 1,
            )
            appliance.windows(window_1=spec["window"], window_2=spec.get("window_2"),
                              random_var_w=spec["window_var"])
            attached = True
        if attached and user.App_list:
            users.append(user)
    if users:
        total += _run_ramp(users, year, month, n_days, seed)
    return total if total.any() else None


def _constant_minutes(device, n_days: int) -> np.ndarray:
    """One device's watts, minute by minute, over a month it runs unfailingly.

    The window is written as it was declared, wrapping past midnight where it does, so a
    lamp lit at half past six in the evening is still lit at dawn without the day boundary
    interrupting it.
    """
    day = np.zeros(MINUTES_PER_DAY)
    start, end = int(device.window_start_min), int(device.window_end_min)
    if end > start:
        day[start:end] = 1.0
    else:                                   # the window crosses midnight
        day[start:] = 1.0
        day[:end] = 1.0
    return np.tile(day, n_days) * device.power_w * device.number


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
                # The count is declared here, not at assignment: RAMP validates the total
                # window time against the duty using the number of windows it was told to
                # expect, and silently ignores a second window it does not know about.
                num_windows=2 if spec.get("window_2") else 1,
            )
            appliance.windows(window_1=spec["window"], window_2=spec.get("window_2"),
                              random_var_w=spec["window_var"])
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
    import random as _stdlib_random

    # The appliance library draws its usage windows and its power variation from Python's
    # global random module, and seeds it only inside ``UseCase`` -- after the users have been
    # built, and only when the seed is truthy, which a seed of zero is not. Both together
    # left the load unseeded: three runs of one sizing differed by a tenth of a per cent,
    # which is larger than several of the differences this work reports. Seeding here covers
    # everything the month draws, before anything is drawn.
    _stdlib_random.seed(int(seed) + 1)

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

    return _run_ramp(users, year, month, n_days, seed)


def _run_ramp(users: list, year: int, month: int, n_days: int, seed: int) -> np.ndarray:
    """Draw one month of minutes for a set of RAMP users.

    Shared by the households and by the uses a developer declares, so that both reach the
    appliance library by one path and inherit the same seeding.
    """
    from ramp import UseCase

    start = f"{year}-{month:02d}-01"
    end = f"{year}-{month:02d}-{n_days:02d}"
    # RAMP seeds Python's global random module, and only ``if self.random_seed:`` -- so a
    # seed of zero, which is this project's default, leaves it unseeded and drawing from
    # whatever state the process happens to be in. Three runs of one sizing then differed by
    # a tenth of a per cent, which is more than the differences this work reports. Offset so
    # the value is never falsy, and never zero for any month.
    use_case = UseCase(users=users, date_start=start, date_end=end,
                       random_seed=int(seed) + 1)
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


@dataclass(frozen=True)
class ArchetypeShapes:
    """The measured hourly shape of each archetype, as ``productive.own_level_parts`` reads a
    class's: one row per archetype, one column per hour.

    A household of a village's record draws its own level on its archetype's shape
    (``build_archetype_shapes``), the one its meter's months are most often assigned to.
    """

    profiles: pd.DataFrame

    @classmethod
    def load(cls, path=None) -> "ArchetypeShapes":
        path = REFERENCE_DIR / "archetype_hourly_shapes.csv" if path is None else path
        table = pd.read_csv(path, dtype={"cluster": str}).set_index("cluster")
        table.columns = [int(c) for c in table.columns]
        return cls(profiles=table)


def _household_growth(users, energy, age: int, last: int) -> list[float] | None:
    """Each anchored household's level beyond the record, relative to the one it measured.

    A household of the record keeps its own level up to the record's last month ``last``.
    Beyond it, its level grows along the growth trajectory from its age at ``last``: the
    ratio of what the trajectory's law expects of a household of its category at its age
    now to what it expects at its age then, both ages held at
    ``growth.ANCHORED_GROWTH_MONTHS`` (``growth.anchored_growth``). ``None`` on the record.
    """
    from .growth import anchored_growth

    if age <= last:
        return None
    return [anchored_growth(energy, u.kind, last - u.joined, age - u.joined) for u in users]


@dataclass
class DemandYear:
    """One stochastic realisation of a community's demand over a calendar year."""

    site: str
    year: int
    seed: int
    hourly_kw: np.ndarray                       # 8760 (or 8784) hourly mean power [kW]
    composition: dict[int, dict[str, int]] = field(default_factory=dict)
    #: Enterprises connected each month, by activity class. Empty when the community is
    #: simulated without productive uses.
    enterprises: dict[int, dict[str, int]] = field(default_factory=dict)
    #: The part of ``hourly_kw`` that no customer is billed for -- the street lighting and
    #: anything else declared as unbilled -- hour by hour, so that the revenue can be
    #: computed on the energy actually sold. It is included in ``hourly_kw``: the plant
    #: serves it and must be sized for it. ``None`` when the community declares nothing of
    #: the kind, which is not the same as zero only in that it costs nothing to carry.
    unbilled_kw: np.ndarray | None = None
    #: The part of ``hourly_kw`` that sits at the plant rather than out on the network: the
    #: air conditioning of the inverter room and whatever else the plant draws to run
    #: itself. Carried apart because no distribution loss applies to it -- it never travels
    #: the conductor the losses occur in. A subset of ``unbilled_kw``.
    at_plant_kw: np.ndarray | None = None
    #: Households connected each month, by category, whether or not they consumed. Under
    #: the whole census it is the census in every month.
    connected: dict[int, dict[str, int]] = field(default_factory=dict)
    #: Households drawn at their own measured level each month, by category: the record's
    #: households in a year that starts from a village's record, none otherwise.
    #: ``composition`` covers the others.
    anchored: dict[int, dict[str, int]] = field(default_factory=dict)
    #: The billed load hour by hour, by who draws it: ``households``, ``productive:<class>``
    #: for the productive users of each class, ``community:<class>`` for the measured
    #: community buildings, and ``declared`` for the billed uses a developer declared. Their
    #: sum is ``hourly_kw`` less ``unbilled_kw``, to rounding. Kept so that a simulated year
    #: can be set against the meters category by category; nothing the sizing reads.
    parts: dict[str, np.ndarray] = field(default_factory=dict)

    @property
    def annual_energy_kwh(self) -> float:
        return float(self.hourly_kw.sum())

    @property
    def unbilled_kwh(self) -> float:
        """Energy delivered over the year that nobody is invoiced for [kWh]."""
        return 0.0 if self.unbilled_kw is None else float(self.unbilled_kw.sum())

    @property
    def at_plant_kwh(self) -> float:
        """Energy the plant drew to run itself, which crossed no network [kWh]."""
        return 0.0 if self.at_plant_kw is None else float(self.at_plant_kw.sum())

    @property
    def billable_kwh(self) -> float:
        """Energy delivered to a metered customer, and so the base a tariff applies to.

        The distinction is not a refinement of the collection rate. A fraction applied to
        everything delivered assumes the unbilled load grows with the energy sold, and it
        does not: the street lighting burns the same hours whatever the village consumes,
        so the share it represents moves with the sales rather than staying put.
        """
        return max(0.0, self.annual_energy_kwh - self.unbilled_kwh)

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
    trajectory: str = "central",
    scaling: ArchetypeScaling | None = None,
    apply_seasonality: bool = True,
    include_productive: bool = True,
    connection: "ConnectionSchedule | None" = None,
    productive_scale: float = 1.0,
) -> DemandYear:
    """Draw one community load profile for ``site`` over the calendar year ``year``.

    The behavioural composition is resolved from the *maturity* of the connection rather
    than from the site's identity, so a locality with no meter record of its own can be
    simulated from its census alone -- which is the situation of every site the model is
    meant to size. ``maturity_months`` is the village age at the start of the simulated
    year, whole months since the site's first connection, and the village ages month by
    month through it.

    ``connection`` says which households are on the grid and since when; ``None`` is the
    whole census at village month 0, every household then as old as the village. Each
    cohort is composed under the law of its own maturity band, and an unconnected household
    is in no state at all: it draws nothing and counts for nothing. A schedule that carries a
    village's record draws each household, productive user and place of worship of the
    record at the level its own meter measured, and the laws decide only what changes after
    the record: the households and users who connect after it, and how an anchored
    household's level grows from its age then.

    ``trajectory`` selects which of the observed growth behaviours to apply; the two
    reference villages bracket a factor of two after two years, so a sizing should be
    computed under both bounds rather than under the central case alone. Genuine calendar
    seasonality is restored afterwards through the residual seasonal index, the part of the
    monthly variation that survives conditioning on maturity.

    ``productive_scale`` multiplies the productive-use intensity the rule reads, a
    sensitivity of the rule and not of the record: the productive users a village's record
    holds stay as recorded, and only what the rule draws is scaled. One leaves the year as
    it was.
    """
    from .connection import ConnectionSchedule
    from .growth import household_energy, maturity_band, seasonal_index, trajectory_law
    from .productive import (ProductiveCalibration, monthly_profile_parts, own_level_parts,
                             sample_units)

    schedule = ConnectionSchedule.whole_census(site) if connection is None else connection
    law = trajectory_law(trajectory)
    # The record's households at their own levels: their shapes, and what the trajectory's
    # law expects of a household by band, which their growth beyond the record follows.
    shapes = energy = None
    if schedule.household_users:
        shapes = ArchetypeShapes.load()
        energy = household_energy(law)
    anchored_classes = frozenset(u.klass for u in schedule.community_users)
    productive = ProductiveCalibration.load() if include_productive else None
    if productive is not None and float(productive_scale) != 1.0:
        productive = replace(productive,
                             intensity=productive.intensity * float(productive_scale))
    appliances = load_archetype_appliances()
    scaling = ArchetypeScaling.load() if scaling is None else scaling
    season = seasonal_index() if apply_seasonality else None
    rng = np.random.default_rng(seed)

    hourly: list[np.ndarray] = []
    unbilled: list[np.ndarray] = []
    at_plant: list[np.ndarray] = []
    composition: dict[int, dict[str, int]] = {}
    enterprises: dict[int, dict[str, int]] = {}
    connected_by_month: dict[int, dict[str, int]] = {}
    anchored_by_month: dict[int, dict[str, int]] = {}
    months_parts: list[dict[str, np.ndarray]] = []
    for month in range(1, 13):
        age = maturity_months + month - 1
        # The band of the village, which is the clock the productive-use intensity was
        # estimated on. Each cohort's own band decides its composition below.
        band = maturity_band(age)
        # Independent multinomial draws under one law add up to one multinomial draw, so
        # grouping the cohorts by band is exact and costs one draw per band and category.
        # Under the whole census there is one band, and the call is the one made before
        # cohorts existed, with the same arguments in the same order: the random stream is
        # unchanged.
        counts = {state: 0 for state in (*ARCHETYPES, INACTIVE)}
        for cohort_band, census in schedule.drawn_by_band(age).items():
            part = sample_composition(law.xs(cohort_band, level="maturity"), census, month,
                                      rng, by_maturity=True)
            for state, n in part.items():
                counts[state] = counts.get(state, 0) + n
        composition[month] = counts
        connected_by_month[month] = schedule.connected(age)
        minutes = _simulate_month(counts, appliances, year, month,
                                  seed=int(rng.integers(0, 2**31 - 1)), rng=rng,
                                  scaling=scaling)
        profile = _to_hourly_kw(minutes)
        if season is not None:
            profile = profile * float(season.get(month, 1.0))
        days = profile.size // 24
        # The record's households at their own levels, each with its own months, which hold
        # its season: the residual seasonality is the law's, and applies to the law's
        # households alone.
        anchored = schedule.anchored_households(age)
        if anchored:
            anchored_by_month[month] = {k: sum(u.kind == k for u in anchored)
                                        for k in schedule.categories}
            scales = _household_growth(anchored, energy, age, schedule.record_end)
            for part in own_level_parts(anchored, shapes, month, days, rng,
                                        scales=scales).values():
                profile = profile + part
        billed_parts: dict[str, np.ndarray] = {"households": profile.copy()}
        # The households the productive users are referred to. The intensity was estimated
        # per household of the connected stock, so that is the base under a progressive
        # schedule. The whole census keeps the reading the model had before, households
        # outside the inactive state, so that no year drawn under it moves: the legacy
        # reading, kept for that alone.
        connected = (sum(v for k, v in counts.items() if k != INACTIVE)
                     if schedule.is_whole_census else sum(schedule.connected(age).values()))
        if productive is not None:
            # Enterprises are counted, not composed: how many have started trading is what
            # varies with the age of the connection, and it is drawn rather than fixed.
            # A site that states how many enterprises it expects is believed over a ratio
            # carried across from the reference villages, scaled by how far its connection
            # has actually advanced.
            # ``None`` means the site has not been surveyed and the reference ratio stands;
            # zero means it was surveyed and there are none. Reading zero as "unknown" would
            # answer a village that stated it has no enterprises with a village that has
            # thirty, which is the whole difference between a daytime and an evening plant.
            declared = getattr(site, "productive_units", None)
            expected_units = None
            if declared is not None:
                share = connected / max(site.n_households, 1)
                expected_units = float(declared) * share
            # A stated roster is taken as it stands; it is scaled by how far the connection
            # has advanced, as the total is, because an enterprise waits for the line like
            # a household does.
            roster = getattr(site, "productive_mix", None)
            if roster:
                share = connected / max(site.n_households, 1)
                roster = {k: int(round(v * share)) for k, v in roster.items()}
            observed = schedule.observed_productive(age)
            users = ()
            if observed is not None and expected_units is None and not roster:
                # A village with its own record starts from the productive users it has,
                # as it does from its households, and the rule decides only what changes
                # after the record's last month: the users it expects of the stock then,
                # less those it expects of the stock at the record's end, never fewer than
                # none. On the record, nothing is drawn.
                held, last = observed
                expected_units = 0.0 if age <= last else max(
                    0.0, _intensity(productive, band, trajectory) * connected
                    - _intensity(productive, maturity_band(last), trajectory)
                    * sum(schedule.connected(last).values()))
                units = sample_units(productive, connected, band, trajectory, rng,
                                     expected_units=expected_units)
                # The users the record holds draw what their own meters measured, each one,
                # where the record has their levels; the users the rule adds draw their
                # class's profile. Without the levels, the record's count is split among
                # the classes by the village's mix and every user draws its class's profile.
                users = schedule.held_users(age)
                if not users:
                    for klass, n in _observed_units(productive, site.name, held).items():
                        units[klass] = units.get(klass, 0) + n
            else:
                units = sample_units(productive, connected, band, trajectory, rng,
                                     expected_units=expected_units, declared_mix=roster)
            drawn = monthly_profile_parts(units, productive, days, rng)
            enterprises[month] = dict(units)
            own = own_level_parts(users, productive, month, days, rng) if users else {}
            for user in users:
                enterprises[month][user.klass] = enterprises[month].get(user.klass, 0) + 1
            # Added in the order the parts come, which for a year without the record's
            # levels is the sum the profile always received.
            total = np.zeros(profile.size)
            for part in (*drawn.values(), *own.values()):
                total += part
            profile = profile + total
            for klass in dict.fromkeys((*drawn, *own)):
                billed_parts[f"productive:{klass}"] = (drawn.get(klass, 0.0)
                                                       + own.get(klass, 0.0))

        # The classes the meters could speak to contribute their measured day exactly as a
        # productive class does, spread and all. Each group goes where its own kind of load
        # belongs: a place of worship into the load alone, the plant's own supply into the
        # load, the unbilled energy and the part that carries no distribution loss.
        measured_unbilled = np.zeros(profile.size)
        measured_at_plant = np.zeros(profile.size)
        for counts, calibration, billable, on_network in _measured_groups(site,
                                                                           anchored_classes):
            by_class = monthly_profile_parts(counts, calibration, days, rng)
            part = np.zeros(profile.size)
            for one in by_class.values():
                part += one
            profile = profile + part
            if billable:
                for klass, one in by_class.items():
                    billed_parts[f"community:{klass}"] = one
            if not billable:
                measured_unbilled = measured_unbilled + part
            if not on_network:
                measured_at_plant = measured_at_plant + part
        # The places of worship a village's record holds, each at its own level, in place
        # of its class's count; where they sit and who pays for them is their class's.
        buildings = schedule.community_present(age)
        if buildings:
            from .uses import CommunityCalibration

            calibration = CommunityCalibration.load()
            if calibration is None:
                raise ValueError("a village's record holds places of worship and the "
                                 "community calibration is not built")
            for klass, one in own_level_parts(buildings, calibration, month, days,
                                              rng).items():
                profile = profile + one
                if calibration.is_billable(klass):
                    billed_parts[f"community:{klass}"] = one
                else:
                    measured_unbilled = measured_unbilled + one
                if not calibration.is_on_network(klass):
                    measured_at_plant = measured_at_plant + one

        # The uses the developer declared, simulated device by device. Community uses are
        # connected from the first month rather than scaled by how far the line has reached:
        # a school or a dispensary is usually what the line was run for, not something that
        # waits its turn behind the households. Declared productive uses wait like the
        # calibrated ones do.
        #
        # Three groups, drawn apart, because two questions divide them and each decides
        # something different. Whether a customer is billed decides the revenue; whether the
        # load sits on the network decides whether a distribution loss applies to it. The
        # street lighting answers no and yes, the plant's own supply no and no. All three
        # are added to the load: the plant serves every one of them.
        declared = _declared_counts(site, counts, connected)
        unbilled_month = measured_unbilled
        at_plant_month = measured_at_plant
        if declared:
            month_seed = int(rng.integers(0, 2**31 - 1))
            n_days = calendar.monthrange(year, month)[1]
            groups = (
                ("billed", 0, {u: n for u, n in declared.items() if u.billable}),
                ("network", 0x5EED, {u: n for u, n in declared.items()
                                     if not u.billable and u.on_network}),
                ("plant", 0x0AC1, {u: n for u, n in declared.items()
                                   if not u.billable and not u.on_network}),
            )
            for kind, salt, uses in groups:
                if not uses:
                    continue
                # Salted from the month's seed rather than drawn from the stream, so that
                # declaring a street lamp does not move the households of every later month.
                minutes = _declared_use_minutes(uses, year, month, n_days,
                                                seed=month_seed ^ salt)
                if minutes is None:
                    continue
                part = _to_hourly_kw(minutes)
                profile = profile + part
                if kind == "billed":
                    billed_parts["declared"] = part
                if kind != "billed":
                    unbilled_month = unbilled_month + part
                if kind == "plant":
                    at_plant_month = at_plant_month + part
        hourly.append(profile)
        unbilled.append(unbilled_month)
        at_plant.append(at_plant_month)
        months_parts.append(billed_parts)

    unbilled_series = np.concatenate(unbilled)
    at_plant_series = np.concatenate(at_plant)
    names = list(dict.fromkeys(k for p in months_parts for k in p))
    parts = {name: np.concatenate([p.get(name, np.zeros(h.size))
                                   for p, h in zip(months_parts, hourly)])
             for name in names}
    return DemandYear(
        site=site.name,
        year=year,
        seed=seed,
        hourly_kw=np.concatenate(hourly),
        composition=composition,
        enterprises=enterprises,
        unbilled_kw=unbilled_series if unbilled_series.any() else None,
        at_plant_kw=at_plant_series if at_plant_series.any() else None,
        connected=connected_by_month,
        anchored=anchored_by_month,
        parts=parts,
    )
