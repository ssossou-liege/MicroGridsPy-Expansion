"""Assembly of one site-year into the arrays the oracles consume.

Both oracles need the same three hourly series — community demand, photovoltaic specific
yield and ambient temperature — for one site and one year. Producing the demand takes a
little over a minute, so a resolved instance is cached on disk: a certified sizing evaluates
the oracles thousands of times over the same instance, and regenerating it each time would
dominate the cost of the search.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .paths import DEMAND_DIR, REFERENCE_DIR, RESULTS_DIR
from .sites import SITES, Site, get_site

CACHE_DIR = RESULTS_DIR / "cache"


@dataclass(frozen=True)
class SiteYear:
    """One site, one year: everything the operating models need."""

    site: str
    year: int
    demand_kw: np.ndarray
    specific_yield: np.ndarray
    t_amb_c: np.ndarray
    usable_fraction: np.ndarray
    self_discharge: np.ndarray
    trajectory: str
    maturity_months: int
    seed: int
    chemistry: str = "lfp"
    #: The part of ``demand_kw`` nobody is billed for: the street lighting, and whatever
    #: else the community declared as unbilled. Already inside ``demand_kw`` -- the plant
    #: serves it and is sized for it -- and carried apart so the appraisal can tell the
    #: energy sold from the energy delivered. ``None`` where the site declares none.
    unbilled_kw: np.ndarray | None = None

    @property
    def hours(self) -> int:
        return self.demand_kw.size

    @property
    def demand_kwh(self) -> float:
        return float(self.demand_kw.sum())

    @property
    def peak_kw(self) -> float:
        return float(self.demand_kw.max())

    @property
    def unbilled_kwh(self) -> float:
        return 0.0 if self.unbilled_kw is None else float(self.unbilled_kw.sum())

    @property
    def billable_kwh(self) -> float:
        """The demand a customer is invoiced for, which is what a tariff is collected on."""
        return max(0.0, self.demand_kwh - self.unbilled_kwh)

    @property
    def billable_fraction(self) -> float:
        """Share of the demand a customer is invoiced for.

        A share and not a parameter: it falls out of what the community declared. Fixing it
        instead would say the unbilled load grows with the energy sold, when the street
        lighting burns the same hours whatever the village consumes.
        """
        total = self.demand_kwh
        return self.billable_kwh / total if total > 0 else 1.0


#: The demand modules whose code decides what a simulated year contains. Every module in
#: the package is either here or in ``_OFFLINE_SOURCES``; a test refuses a third category,
#: so a module added to the package forces someone to say which it is rather than being
#: silently left out of the key.
#:
#: It is the *transitive* reach of the generator, which a test computes rather than trusts.
#: Four of these were on the offline side, and they are not offline at all: every simulated
#: month asks ``growth.trajectory_law`` for the mixture, which asks ``maturity`` for the
#: maturity of each observation, which asks ``partition`` to segment the whole meter
#: archive, which reads it and clusters it through two of the build modules. The
#: segmentation is run at generation, not merely recorded by it, so changing the prior
#: strength, the maturity bands or the winsorising quantiles changed what a year contains
#: and invalidated nothing.
_GENERATION_SOURCES = ("generator.py", "growth.py", "productive.py", "archetypes.py",
                       "uses.py", "maturity.py", "partition.py", "connection.py",
                       "build_mixture_probabilities.py",
                       "build_monthly_household_clusters.py")

#: Modules that build the calibration tables rather than read them. Their output is the
#: CSVs, which the digest already covers, so hashing them too would rebuild every cached
#: year for a change that cannot reach one.
_OFFLINE_SOURCES = ("__init__.py", "build_archetype_shapes.py",
                    "build_community_profiles.py", "build_connection_curves.py",
                    "build_meter_archive.py",
                    "build_productive_profiles.py",
                    "calibration.py", "validate.py")

#: Calibration tables the generation does not read. Hashed, they invalidated every cached
#: year whenever they were rebuilt, for a change that cannot reach one. The type-by-month
#: mixture was superseded by the maturity-conditioned law and is read only by ``validate.py``
#: and the tests; six others are the record of the segmentation, written so that a
#: calibration can be checked against the meters rather than taken on trust, and read by
#: nothing, and the last is the state of every meter, written for the field team. Rebuilding the segmentation to look at it rebuilt three hours and a half of
#: cached demand. The directory's own README states the same division table by table, and a
#: test holds the two statements together.
_NOT_READ_AT_GENERATION = ("mixture_probabilities_type_month.csv",
                           "archetype_hourly_shapes.csv",
                           "global_cluster_profiles.csv",
                           "monthly_household_features.csv",
                           "monthly_household_cluster_assignments.csv",
                           "gbowele_monthly_cluster_summary.csv",
                           "samionta_monthly_cluster_summary.csv",
                           "meter_status.csv")

#: Measured inputs the segmentation reads at generation: the household register and each
#: reference site's meter archive. They were missing from the key altogether, so five more
#: months of readings -- which move the segmentation, the mixture law and therefore every
#: simulated year -- left the cache serving years built on the shorter record.
_MEASURED_CENSUS = "household_customers.csv"


def _code_digest(path: Path) -> bytes:
    """A module's code, as the parser sees it: comments and formatting excluded.

    Hashing the raw text would rebuild an hour of cached demand because someone rewrapped a
    comment. Hashing the syntax tree invalidates on a change that can alter what the module
    computes, and on nothing else. Docstrings are dropped for the same reason -- they are
    prose that happens to be stored as a node.
    """
    import ast

    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            continue
        body = node.body
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
                and isinstance(body[0].value.value, str):
            node.body = body[1:] or [ast.Pass()]
    return ast.dump(tree).encode()


def _measured_inputs() -> list[Path]:
    """The measured files the generation reads, in a fixed order.

    The household register, and one meter archive per reference site as the site registry
    declares it. Taken from the registry rather than listed here, so that the key covers
    whatever the segmentation will actually open.
    """
    names = [_MEASURED_CENSUS]
    names += sorted({site.meter_file for site in SITES.values()
                     if site.meter_file is not None})
    return [DEMAND_DIR / name for name in names]


def _demand_fingerprint() -> str:
    """Digest of everything that decides the demand a cached year carries.

    Four things decide it, and the key has to carry all four. The calibration tables,
    because a recalibration makes a cached year describe a model that no longer exists --
    which is not hypothetical: the appliance windows were corrected under a cache that would
    have gone on serving the uncorrected year. The code that reads those tables, for exactly
    the same reason, and this half was missing: the seeding fix that made the generator
    reproducible never invalidated anything, so the cache went on serving pools drawn before
    it, unseeded, and a rename of a table column was what finally dislodged them. The
    appliance library, because it is what actually draws the usage windows. And the measured
    record itself, which was missing too and is the plainest of the four: every simulated
    month is composed from a mixture law estimated on the meter archive, at generation and
    not in advance, so extending that archive by five months changes every year the model
    produces. The pools drawn before the extension stayed valid-looking.

    What it does not cover is worth stating: the versions of numpy and pandas, whose random
    streams and numerics are stable across the range this project pins, and the resource
    series, which the site fingerprint carries instead. Nor the tables listed in
    ``_NOT_READ_AT_GENERATION``, which the generation does not open.
    """
    digest = hashlib.sha1()
    for path in sorted(REFERENCE_DIR.glob("*.csv")):
        if path.name in _NOT_READ_AT_GENERATION:
            continue
        digest.update(path.name.encode())
        digest.update(path.read_bytes())

    for path in _measured_inputs():
        digest.update(path.name.encode())
        if path.exists():
            digest.update(path.read_bytes())

    demand_dir = Path(__file__).parent / "demand"
    for name in sorted(_GENERATION_SOURCES):
        digest.update(name.encode())
        digest.update(_code_digest(demand_dir / name))

    try:
        import ramp

        digest.update(str(getattr(ramp, "__version__", "unknown")).encode())
    except ImportError:                     # the library is optional at import time
        digest.update(b"no-ramp")
    return digest.hexdigest()[:12]


def _site_fingerprint(site: Site) -> str:
    """Everything about a site's description that decides the year it produces.

    The name alone is not the site. When sites were written into the source a name could
    only mean one description, and keying on it was safe; now that a site is something the
    user edits, the same name means whatever they last saved. Keyed on the name alone, the
    cache answered a community of three hundred households with the year computed for one
    hundred and fifty -- no error, no warning, a plausible number for the wrong village.
    """
    census = ";".join(f"{k}={v}" for k, v in sorted(site.census.items()))
    parts = [census, site.latitude, site.longitude, site.irradiance_file,
             site.productive_units, site.utc_offset_hours]
    # A surveyed roster of enterprises decides the demand as plainly as the census does, so
    # it belongs in the key. It is appended rather than folded in, and only when there is
    # one: a community that never declared a roster fingerprints exactly as it did before
    # the field existed, and years computed for it stay valid. Written into every key, an
    # empty roster would have invalidated every cached year on this machine and every other
    # -- some thirty pools at ten minutes apiece -- to record the absence of something.
    roster = getattr(site, "productive_mix", None)
    if roster:
        parts.append(";".join(f"{k}={v}" for k, v in sorted(roster.items())))
    # The community uses and the uses the developer described, on the same terms: appended
    # only when there are any, so a village that declared none keys as it always did.
    community = getattr(site, "community_mix", None)
    if community:
        parts.append("c:" + ";".join(f"{k}={v}" for k, v in sorted(community.items())))
    own = getattr(site, "self_mix", None)
    if own:
        parts.append("s:" + ";".join(f"{k}={v}" for k, v in sorted(own.items())))
    declared = getattr(site, "declared_uses", None)
    if declared:
        parts.append("u:" + ";".join(
            f"{u.key}=" + ",".join(f"{d.name}:{d.power_w}:{d.number}:{d.func_time_min}:"
                                   f"{d.func_cycle_min}:{d.window_start_min}:"
                                   f"{d.window_end_min}:{d.occasional_use}"
                                   for d in u.devices)
            for u in sorted(declared, key=lambda x: x.key)))
    return "|".join(str(x) for x in parts)


def _module_fingerprint(module) -> str:
    """What a module adds to a key, and nothing when it is the standard one.

    Appended only when the project describes a module other than the package's, for the
    reason the roster and the community uses are: written into every key, the five figures
    would have invalidated every cached year on every machine to record that nobody had
    changed them.
    """
    from .resource.yield_model import ModuleSpec

    if module is None or module == ModuleSpec():
        return ""
    return (f"m:{module.noct_c}|{module.gamma_per_k}|{module.derate}"
            f"|{module.u0_w_m2_k}|{module.u1_w_s_m3_k}")


def _connection_fingerprint(connection, maturity_months: int) -> str:
    """What a connection schedule adds to a key, and nothing under the whole census.

    The digest of the stock over the twelve months of the year, which is all of the
    schedule a year can see. Appended only when the schedule is not the whole census, for
    the reason the module is: every year cached before schedules existed was a year of the
    whole census, and keys exactly as it did.
    """
    if connection is None or connection.is_whole_census:
        return ""
    return f"|k:{connection.digest(until=int(maturity_months) + 11)}"


def _cache_key(site: str, year: int, trajectory: str, maturity_months: int,
               seed: int, chemistry: str, archetypes: str = "std",
               description: str = "", network_loss: float = 0.0,
               module: str = "", connection: str = "") -> str:
    # The chemistry belongs in the key: it changes the storage ceiling and the
    # self-discharge the instance carries, so a cached instance from another chemistry
    # would silently describe a different battery. So does the demand fingerprint, for the
    # same reason: it decides the demand the instance carries, tables and generating code
    # alike. So does the site's own description, for the plainest reason of all: it *is*
    # the community.
    # The network loss belongs in the key for the plainest of the reasons above: it decides
    # the demand the instance carries. A year built for a lossless network describes a
    # smaller plant, and serving it under a fifteen per cent loss is a different study.
    # The connection schedule, through ``_connection_fingerprint``.
    raw = (f"{site}|{year}|{trajectory}|{maturity_months}|{seed}|{chemistry}"
           f"|{_demand_fingerprint()}|{archetypes}|{description}"
           f"|{network_loss:.6f}{module}{connection}")
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def check_network_loss(fraction: float) -> float:
    """The loss fraction as the arithmetic below can use it.

    A share of the injection at or above one would ask the plant for infinite energy, so it
    is refused rather than clamped: a figure like that is a decimal point in the wrong place
    and silently serving the nearest admissible study would hide it.
    """
    value = float(fraction or 0.0)
    if value < 0.0:
        raise ValueError("a network loss cannot be negative")
    if value >= 1.0:
        raise ValueError(
            f"a network loss of {value:.2f} of the injection leaves nothing for the "
            "customers; it is a share of what the plant sends out, not a multiplier")
    return value


def with_network_loss(total_kw: np.ndarray, at_plant_kw: np.ndarray | None,
                      loss: float) -> tuple[np.ndarray, np.ndarray]:
    """The load the plant must produce, and what the network consumed on the way.

    The loss is taken as a share of the energy *injected* into the network, which is the
    convention a distribution meter reading is divided into and the one a utility reports.
    So the injection is the load downstream divided by one minus the share, not the load
    multiplied by one plus it -- at fifteen per cent the two differ by nearly three points.

    It applies to what travels the conductor and to nothing else. The plant's own supply is
    drawn from the busbar beside it, so ``at_plant_kw`` is taken out before the share is
    applied and carries no loss of its own.

    A fixed share is an approximation and worth naming as one. Real resistive loss follows
    the square of the current, so a share fitted at one load is wrong at another. It is the
    standard planning convention, and at the two reference villages it is not the term that
    mattered: once the street lighting and the plant's own supply were counted as the loads
    they are, what remained varying with the load could not be told from zero. The constant
    everyone had been calling a loss was those two.

    Shared by the single certified year and by the scenario tree, because a plan and a
    sizing of the same village must be asked for the same energy. Written twice they would
    drift, which is the fault this project has already repaired once in the pricing.
    """
    if loss <= 0.0:
        return total_kw, np.zeros_like(total_kw)
    at_plant = np.zeros_like(total_kw) if at_plant_kw is None else at_plant_kw
    lost = (total_kw - at_plant) * (loss / (1.0 - loss))
    return total_kw + lost, lost


def build_site_year(
    site: Site | str,
    year: int = 2025,
    trajectory: str = "central",
    maturity_months: int = 12,
    seed: int = 0,
    chemistry: str | None = None,
    use_cache: bool = True,
    network_loss_fraction: float = 0.0,
    module=None,
    connection=None,
) -> SiteYear:
    """Resolve a site and year into aligned hourly series.

    The demand and the resource are produced independently and must agree in length; a
    leap year has 8 784 hours and both sides are built for the same calendar year, so a
    mismatch signals that one of them was built for another year.

    ``network_loss_fraction`` is the share of the energy injected into the distribution
    network that the network itself consumes. It is applied here rather than in the
    generator because it is a property of the conductor and not of anybody's behaviour: the
    generator says what the village asks for, and this says what the plant must produce for
    the village to get it.

    ``connection`` is the ``ConnectionSchedule`` the households follow, and ``None`` the
    whole census at village month 0. ``maturity_months`` is then the village age at the
    first month of the year.
    """
    from .demand import archetypes as _archetypes
    from .demand.generator import simulate_demand_year
    from .resource import simulate_resource_year

    from . import config as _config

    site = get_site(site) if isinstance(site, str) else site
    chemistry = _config.BATTERY_CHEMISTRY if chemistry is None else chemistry
    if module is None:
        from .resource.yield_model import module_from
        from .settings import default_settings

        module = module_from(default_settings().photovoltaic)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    # The archetypes a site runs on are part of what a cached year is: adjusted locally and
    # not counted here, a stale file would answer with the behaviour of another community.
    loss = check_network_loss(network_loss_fraction)
    key = _cache_key(site.name, year, trajectory, maturity_months, seed, chemistry,
                     _archetypes.fingerprint(site.name), _site_fingerprint(site),
                     network_loss=loss, module=_module_fingerprint(module),
                     connection=_connection_fingerprint(connection, maturity_months))
    path = CACHE_DIR / f"siteyear_{site.name.lower()}_{key}.npz"

    if use_cache and path.exists():
        stored = np.load(path)
        return SiteYear(site=site.name, year=year,
                        demand_kw=stored["demand_kw"],
                        specific_yield=stored["specific_yield"],
                        t_amb_c=stored["t_amb_c"],
                        usable_fraction=stored["usable_fraction"],
                        self_discharge=stored["self_discharge"],
                        # Written only where there is one, and read as absent otherwise:
                        # the key covers the generating code, so a file saved before the
                        # split cannot be served to this reader -- but a village with no
                        # unbilled use writes no array either.
                        unbilled_kw=(stored["unbilled_kw"]
                                     if "unbilled_kw" in stored.files else None),
                        trajectory=trajectory, maturity_months=maturity_months,
                        seed=seed, chemistry=chemistry)

    demand = simulate_demand_year(site, year=year, seed=seed,
                                  maturity_months=maturity_months,
                                  trajectory=trajectory,
                                  scaling=_archetypes.scaling_for(site.name),
                                  connection=connection)
    resource = simulate_resource_year(site, year, module=module, chemistry=chemistry)
    if demand.hourly_kw.size != resource.specific_yield.size:
        raise ValueError(
            f"demand has {demand.hourly_kw.size} hours and the resource "
            f"{resource.specific_yield.size}; both must cover {year}"
        )

    # The loss is served energy that reaches no meter, so it joins what nobody is billed
    # for rather than sitting outside the accounts.
    demand_kw, lost_kw = with_network_loss(demand.hourly_kw, demand.at_plant_kw, loss)
    unbilled_kw = demand.unbilled_kw
    if loss > 0.0:
        unbilled_kw = lost_kw if unbilled_kw is None else unbilled_kw + lost_kw
    instance = SiteYear(
        site=site.name, year=year,
        demand_kw=demand_kw,
        specific_yield=resource.specific_yield,
        t_amb_c=resource.t_amb_c,
        usable_fraction=resource.usable_fraction,
        self_discharge=resource.self_discharge,
        unbilled_kw=unbilled_kw,
        trajectory=trajectory, maturity_months=maturity_months, seed=seed,
        chemistry=chemistry,
    )
    if use_cache:
        extra = ({} if instance.unbilled_kw is None
                 else {"unbilled_kw": instance.unbilled_kw})
        np.savez_compressed(
            path, demand_kw=instance.demand_kw, specific_yield=instance.specific_yield,
            t_amb_c=instance.t_amb_c, usable_fraction=instance.usable_fraction,
            self_discharge=instance.self_discharge, **extra,
        )
    return instance
