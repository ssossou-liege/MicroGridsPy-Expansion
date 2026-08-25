"""Project parameters, declared once and supplied by the user.

Everything the model needs that is not measured data lives here: the site, the equipment,
the economics, the operating policy and the calibration settings. They are held in one
typed tree that round-trips through a YAML file, so that sizing a new project is a matter
of editing a document rather than of editing the source, and so that the parameters behind
a published result can be archived with it.

Three principles govern what belongs here.

*One definition.* A quantity that appears in two places will eventually disagree in two
places. Every parameter has exactly one home, and the modules read it from here rather than
keeping a copy — a discipline this project adopted after three separate defects were traced
to duplicated definitions.

*Equipment describes itself.* Fuel curves belong to a generator, not to the model; a
catalogue of four ratings carries four fuel curves. Manufacturers publish consumption at
half, three-quarter and full load, so that is what the user is asked for and the efficiency
curve is fitted from it.

*Unverified values announce themselves.* A parameter nobody has sourced is marked as such
and reported, rather than passing silently as though it were measured.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any

import numpy as np

#: Physical constants: properties of matter, not choices, and so not user parameters.
DIESEL_HHV_KJ_KG = 45800.0
DIESEL_DENSITY_KG_L = 0.832
SOLAR_CONSTANT_W_M2 = 1361.0
T_STC_C = 25.0
G_STC_W_M2 = 1000.0


@dataclass
class Provenance:
    """Where a group of parameters comes from, and whether anyone has checked it."""

    source: str = "unsourced"
    verified: bool = False
    note: str = ""


@dataclass
class CurrencySettings:
    """Conversion between the currency of the field and the currency of the model.

    Equipment is quoted and tariffs are set in CFA francs, while the model computes in
    dollars. The CFA franc is pegged to the euro at a fixed parity, so only the euro-dollar
    rate moves; recording both makes a cost traceable back to the quotation it came from
    and lets a result be restated at another rate without re-sourcing anything.
    """

    local_code: str = "XOF"
    xof_per_eur: float = 655.957          # fixed parity, not a market rate
    usd_per_eur: float = 1.08
    rate_note: str = "euro-dollar rate of August 2026; update when restating costs"

    @property
    def local_per_usd(self) -> float:
        return self.xof_per_eur / self.usd_per_eur

    def to_usd(self, amount_local: float) -> float:
        """Convert an amount in the local currency into dollars."""
        return amount_local / self.local_per_usd

    def to_local(self, amount_usd: float) -> float:
        """Convert an amount in dollars into the local currency."""
        return amount_usd * self.local_per_usd


# --------------------------------------------------------------------- equipment
@dataclass
class PhotovoltaicSpec:
    """A photovoltaic module and the array losses around it."""

    unit_kw: float = 0.5                       # rated power of one panel
    #: 100 000 FCFA/kW quoted on the Beninese market.
    cost_usd_kw: float = 164.6
    lifetime_years: int = 25
    om_rate: float = 0.018                     # annual, as a fraction of capital
    noct_c: float = 45.0
    temperature_coefficient_per_k: float = -0.0035
    derate: float = 0.85                       # soiling, wiring, mismatch, conversion
    faiman_u0_w_m2_k: float = 25.0
    faiman_u1_w_s_m3_k: float = 6.84
    provenance: Provenance = field(default_factory=lambda: Provenance(
        source="100 000 FCFA/kW quoted on the Beninese market (2026); crystalline "
               "silicon, open rack, generic technical characteristics",
        verified=True,
        note="the price is sourced; the thermal characteristics remain generic"))


@dataclass
class BatterySpec:
    """A storage pack: chemistry, limits and economics."""

    chemistry: str = "lfp"
    unit_kwh: float = 5.0                      # usable energy of one module
    #: 200 000 FCFA/kWh quoted on the Beninese market.
    cost_usd_kwh: float = 329.3
    lifetime_years: int = 16
    cycles: int = 6000
    om_rate: float = 0.060
    charge_efficiency: float = 0.975
    discharge_efficiency: float = 0.975
    soc_min: float = 0.05
    soc_max: float = 0.95
    #: Maximum charge or discharge power as a fraction of nameplate energy, per hour.
    c_rate: float = 0.25
    #: State of charge the plant starts from, as a fraction of the usable ceiling.
    initial_soc_fraction: float = 0.5
    provenance: Provenance = field(default_factory=lambda: Provenance(
        source="200 000 FCFA/kWh quoted on the Beninese market (2026); BYD LV Flex, "
               "lithium iron phosphate",
        verified=True,
        note="the price is sourced; cycle life and efficiencies remain manufacturer "
             "figures"))

    def degradation_usd_kwh(self) -> float:
        """Throughput cost of storage [$ per kWh discharged]."""
        throughput = self.cycles * (self.soc_max - self.soc_min)
        return self.cost_usd_kwh / throughput


@dataclass
class GeneratorSpec:
    """One generator of the catalogue, carrying its own fuel curve.

    ``fuel_l_per_h`` is what a manufacturer publishes: consumption at half, three-quarter
    and full load. The quadratic efficiency the model uses is fitted from those three
    points, so a catalogue of several ratings carries several curves rather than borrowing
    one unit's behaviour for every size.
    """

    rating_kw: float
    fuel_l_per_h: dict[float, float]
    #: Generators are quoted per kVA of apparent power while the model sizes active
    #: power, so the quotation and the power factor are held separately rather than
    #: silently conflated: at a factor of 0.8 a kVA buys only 0.8 kW.
    cost_usd_kva: float = 411.6
    power_factor: float = 0.8
    lifetime_years: int = 15
    om_rate: float = 0.080
    min_load_fraction: float = 0.30
    salvage_fraction: float = 0.40
    provenance: Provenance = field(default_factory=Provenance)

    @property
    def cost_usd_kw(self) -> float:
        """Capital cost per kilowatt of active power."""
        return self.cost_usd_kva / self.power_factor

    def efficiency_coefficients(self) -> tuple[float, float, float]:
        """Fit ``eta = a + b x + c x^2`` to the published consumption figures.

        Efficiency at part load ``x`` is the electrical output divided by the fuel power,
        so each published point gives one equation; three points determine the quadratic
        exactly, and more are fitted by least squares.
        """
        loads = np.array(sorted(self.fuel_l_per_h), dtype=float)
        if loads.size < 3:
            raise ValueError(
                f"generator {self.rating_kw} kW needs at least three fuel points, "
                f"got {sorted(self.fuel_l_per_h)}")
        litres = np.array([self.fuel_l_per_h[float(x)] for x in loads], dtype=float)

        fuel_kw = litres * DIESEL_DENSITY_KG_L * DIESEL_HHV_KJ_KG / 3600.0
        efficiency = loads * self.rating_kw / fuel_kw
        design = np.vstack([np.ones_like(loads), loads, loads ** 2]).T
        a, b, c = np.linalg.lstsq(design, efficiency, rcond=None)[0]
        return float(a), float(b), float(c)


def default_generator_catalogue() -> list[GeneratorSpec]:
    """The Perkins 400-series units available in the size range this study needs.

    Each entry carries the consumption its manufacturer publishes at half, three-quarter
    and full load, so the four ratings are genuinely distinguishable rather than one
    curve stretched over a catalogue — which matters, the certificate arbitrating between
    exactly these sizes.

    Ratings are quoted in kVA of apparent power and converted to the active power the model
    sizes. Their specific consumption is not monotone in size: the 15 kVA unit is a
    naturally aspirated three-cylinder and burns less per kilowatt-hour at full load than
    the larger four-cylinder, which is precisely the kind of detail a single scaled curve
    erases.
    """
    perkins = Provenance(
        source="Perkins 400 series, manufacturers' published consumption at 50/75/100 % "
               "load; ratings converted from kVA at the catalogue power factor",
        verified=True)
    return [
        GeneratorSpec(rating_kw=8.0, fuel_l_per_h={0.5: 1.7, 0.75: 2.3, 1.0: 3.0},
                      provenance=Provenance(source="Perkins 403A-11G1, 10 kVA — " +
                                            perkins.source, verified=True)),
        GeneratorSpec(rating_kw=12.0, fuel_l_per_h={0.5: 2.0, 0.75: 2.8, 1.0: 3.7},
                      provenance=Provenance(source="Perkins 403A-15G1, 15 kVA — " +
                                            perkins.source, verified=True)),
        GeneratorSpec(rating_kw=16.0, fuel_l_per_h={0.5: 2.9, 0.75: 4.0, 1.0: 5.3},
                      provenance=Provenance(source="Perkins 404A-22G1, 20 kVA — " +
                                            perkins.source, verified=True)),
    ]


@dataclass
class InverterSpec:
    """The hybrid inverter coupling the assets to the load."""

    unit_kw: float = 2.5
    #: 250 000 FCFA/kW quoted on the Beninese market, at 655.957 XOF/EUR and 1.08 USD/EUR.
    cost_usd_kw: float = 412.0
    lifetime_years: int = 10
    om_rate: float = 0.020
    provenance: Provenance = field(default_factory=lambda: Provenance(
        source="hybrid inverter, 250 000 FCFA/kW quoted on the Beninese market (2026)",
        verified=True,
        note="restate through the currency block if the euro-dollar rate is updated"))


@dataclass
class CouplingSpec:
    """Where the array joins the plant, and what that junction permits.

    A hybrid inverter is not a bare converter: it ships with its own maximum-power-point
    trackers, two to four of them on current three-phase units, and it expects to be the
    single authority over the battery. Bolting separate charge controllers onto the same
    lithium bank puts two regulators on one pack, and unless both answer to the same
    battery-management conversation the result is conflicting set-points and a real risk of
    overcharge. It is done — Victron coordinates its controllers and its inverters from one
    device that holds the conversation with the pack — but only inside a single
    manufacturer's ecosystem, and never by mixing brands. The model therefore does not size
    external controllers at all. Conversion on the direct-current side is *inside* the
    hybrid inverter and is bought with it.

    What that costs the design is not money but a ceiling. Integrated trackers accept only
    so much array per kilowatt of inverter — a thirty-kilowatt three-phase unit takes
    thirty-nine kilowatts of array, a ratio of about 1.3 — so enlarging the array past that
    means buying another inverter. Enlarging the *array* and enlarging the *converter* are
    thus one decision, not two.

    The alternative is to put the surplus array on the alternating-current side through its
    own string inverters, where it serves the load without passing the hybrid inverter at
    all. That has its own ceiling: off grid, whatever the load does not take must be
    absorbable by the battery inverter, which is why such an array is not sized beyond the
    hybrid inverter's own rating. It is also curtailed by frequency shift rather than by
    command, and it pays a second conversion on everything that reaches storage.

    Which of the two is cheaper is not assumed: at ``"auto"`` both are certified and the
    result reports which prevailed and by how much.
    """

    #: ``"dc"``, ``"ac"``, or ``"auto"`` to let the search prove the choice.
    architecture: str = "auto"
    #: Array admitted per kilowatt of hybrid inverter by its integrated trackers. 1.3 is
    #: what current three-phase units publish (30 kW of inverter, 39 kW of array).
    dc_ac_ratio_max: float = 1.3
    #: Array admitted per kilowatt of hybrid inverter when coupled on the alternating side.
    #: Held at parity: off grid the battery inverter must be able to absorb the whole array
    #: the instant the load drops.
    ac_ratio_max: float = 1.0
    #: String inverters for an alternating-coupled array, 50 000 FCFA/kW. Nothing
    #: corresponds to this under direct-current coupling, the conversion being integrated.
    string_inverter_cost_usd_kw: float = 82.3
    lifetime_years: int = 12
    om_rate: float = 0.020
    #: Round-trip penalty on array energy that reaches storage through the alternating bus,
    #: converted up by the string inverter and down again by the hybrid inverter.
    ac_double_conversion_efficiency: float = 0.94
    provenance: Provenance = field(default_factory=lambda: Provenance(
        source="integrated-tracker ratio from current three-phase hybrid inverter data "
               "sheets (30 kW AC / 39 kW PV); string inverters at 50 000 FCFA/kW quoted on "
               "the Beninese market (2026); parity rule for off-grid alternating coupling",
        verified=True))

    def cost_usd_kw(self, architecture: str) -> float:
        """Conversion bought per kilowatt of array, beyond the hybrid inverter itself."""
        if architecture == "dc":
            return 0.0                     # the trackers come inside the inverter
        if architecture == "ac":
            return self.string_inverter_cost_usd_kw
        raise ValueError(f"architecture must be 'dc' or 'ac', not {architecture!r}")

    def array_ratio_max(self, architecture: str) -> float:
        """Array admitted per kilowatt of hybrid inverter under the given architecture."""
        if architecture == "dc":
            return self.dc_ac_ratio_max
        if architecture == "ac":
            return self.ac_ratio_max
        raise ValueError(f"architecture must be 'dc' or 'ac', not {architecture!r}")

    def architectures(self) -> tuple[str, ...]:
        """The architectures the search must consider."""
        return ("dc", "ac") if self.architecture == "auto" else (self.architecture,)


# ---------------------------------------------------------------------- economics
@dataclass
class EconomicSettings:
    """Discounting, fuel and the price put on unserved energy."""

    discount_rate: float = 0.08
    horizon_years: int = 25
    diesel_price_usd_l: float = 1.29
    #: Tariff the operator intends to charge; 160 FCFA/kWh. It is also the revealed lower
    #: bound of what a connected household is prepared to pay for a kilowatt-hour.
    tariff_usd_kwh: float = 0.263
    #: Whether that tariff is a *target* to be reached with a capital subsidy. When it is,
    #: the model reports the share of the investment a grant must cover for the levelised
    #: cost to fall to the target. When it is not, the project is assumed to recover its
    #: full cost and the tariff simply is the levelised cost.
    tariff_is_target: bool = True
    #: Value of lost load. See ``voll_provenance``: it fixes the reliability the design
    #: aims at, so it is reported across a range rather than asserted as one number.
    value_of_lost_load_usd_kwh: float = 1.00
    value_of_lost_load_range_usd_kwh: tuple[float, float] = (0.50, 3.00)
    discount_provenance: Provenance = field(default_factory=lambda: Provenance(
        source="World Bank, Discounting Costs and Benefits in Economic Analysis of World "
               "Bank Projects, OPSPQ, May 2016",
        verified=True,
        note="the guidance derives the rate from per-capita growth through the Ramsey "
             "formula: client-country growth of about 3 % gives 6 %, and the 25-75 "
             "percentile band spans 2-10 %, while the descriptive approach suggests "
             "8-12 % for developing countries. 8 % is the lower end of the descriptive "
             "band and sits inside the Ramsey interval; the guidance asks for a "
             "sensitivity analysis over a range rather than a single value"))
    diesel_provenance: Provenance = field(default_factory=lambda: Provenance(
        source="central benchmark for the study region", verified=False,
        note="the formulation treats the fuel price as an uncertainty axis; this is its "
             "central value, not a fixed datum"))
    def __post_init__(self) -> None:
        # YAML has no tuple; normalising keeps a reloaded project equal to itself.
        self.value_of_lost_load_range_usd_kwh = tuple(
            self.value_of_lost_load_range_usd_kwh)

    tariff_provenance: Provenance = field(default_factory=lambda: Provenance(
        source="160 FCFA/kWh charged on the micro-grid (2026)", verified=True))
    voll_provenance: Provenance = field(default_factory=lambda: Provenance(
        source="bounded below by the tariff households demonstrably pay (0.26 $/kWh) and "
               "by the marginal cost of diesel generation in this model (0.36 $/kWh), "
               "below which the optimiser would shed load rather than generate; anchored "
               "on the cost of the substitute households actually use during an outage, "
               "self-generation in Africa costing about 0.47 $/kWh and lighting and phone "
               "charging by kiosk far more per useful kilowatt-hour",
        verified=False,
        note="this parameter sets the reliability the design aims at, not merely a price; "
             "report the sizing across value_of_lost_load_range_usd_kwh rather than at the "
             "central value alone"))


# ------------------------------------------------------------------------- policy
@dataclass
class ControllerSettings:
    """Parameters of the deployed operating rule — the policy class theta."""

    reserve_multiplier: float = 1.0
    lookahead_hours: int = 14
    generator_setpoint: float = 0.30


# -------------------------------------------------------------------- calibration
@dataclass
class CalibrationSettings:
    """Choices made when turning measurements into archetypes and mixture laws.

    They are method parameters rather than physical ones, but they determine the partition
    everything downstream rests on, so they are recorded with the project rather than left
    in the source.
    """

    n_archetypes: int = 4
    winsor_lower_quantile: float = 0.01
    winsor_upper_quantile: float = 0.99
    outlier_mad_threshold: float = 4.5
    min_support: int = 30
    mixture_prior_strength: float = 20.0
    maturity_edges_months: tuple[int, ...] = (-1, 3, 6, 12, 24, 1200)
    ramp_time_variability: float = 0.2
    ramp_window_variability: float = 0.15
    meter_interval_minutes: int = 15

    def __post_init__(self) -> None:
        # YAML has no tuple, so a reloaded document brings the edges back as a list;
        # normalising here keeps a saved and reloaded project exactly equal to itself.
        self.maturity_edges_months = tuple(self.maturity_edges_months)


@dataclass
class SolverSettings:
    """How the mathematical programmes are solved."""

    name: str = "highs"
    mip_gap: float = 0.01
    time_limit_s: int = 3600
    threads: int = 0


# ------------------------------------------------------------------------- project
@dataclass
class ProjectSettings:
    """Everything a project needs beyond its measured data."""

    site: str = "Samionta"
    year: int = 2025
    demand_trajectory: str = "centrale"
    maturity_months: int = 12
    seed: int = 0

    currency: CurrencySettings = field(default_factory=CurrencySettings)
    photovoltaic: PhotovoltaicSpec = field(default_factory=PhotovoltaicSpec)
    battery: BatterySpec = field(default_factory=BatterySpec)
    inverter: InverterSpec = field(default_factory=InverterSpec)
    coupling: CouplingSpec = field(default_factory=CouplingSpec)
    generators: list[GeneratorSpec] = field(default_factory=default_generator_catalogue)
    economics: EconomicSettings = field(default_factory=EconomicSettings)
    controller: ControllerSettings = field(default_factory=ControllerSettings)
    calibration: CalibrationSettings = field(default_factory=CalibrationSettings)
    solver: SolverSettings = field(default_factory=SolverSettings)

    # ---------------------------------------------------------------- validation
    def validate(self) -> None:
        """Reject a configuration that cannot describe a real plant."""
        from .battery import CHEMISTRIES

        if self.battery.chemistry not in CHEMISTRIES:
            raise ValueError(f"unknown battery chemistry {self.battery.chemistry!r}; "
                             f"available: {sorted(CHEMISTRIES)}")
        if not 0.0 <= self.battery.soc_min < self.battery.soc_max <= 1.0:
            raise ValueError("battery state-of-charge limits must satisfy 0 <= min < max <= 1")
        if not 0.0 < self.economics.discount_rate < 1.0:
            raise ValueError("the discount rate must lie strictly between 0 and 1")
        if self.coupling.architecture not in ("dc", "ac", "auto"):
            raise ValueError("coupling.architecture must be 'dc', 'ac' or 'auto', "
                             f"not {self.coupling.architecture!r}")
        if min(self.coupling.dc_ac_ratio_max, self.coupling.ac_ratio_max) <= 0.0:
            raise ValueError("the array-to-inverter ratios must be strictly positive")
        if self.economics.horizon_years <= 0:
            raise ValueError("the horizon must be a positive number of years")
        if not self.generators:
            raise ValueError("the generator catalogue must not be empty")
        ratings = [g.rating_kw for g in self.generators]
        if len(set(ratings)) != len(ratings):
            raise ValueError(f"duplicate generator ratings in the catalogue: {ratings}")
        for generator in self.generators:
            generator.efficiency_coefficients()          # raises if under-specified
            if not 0.0 <= generator.min_load_fraction < 1.0:
                raise ValueError(f"minimum loading of the {generator.rating_kw} kW unit "
                                 "must lie in [0, 1)")
        if self.demand_trajectory not in ("lente", "centrale", "rapide"):
            raise ValueError(f"unknown demand trajectory {self.demand_trajectory!r}")

        low, high = self.economics.value_of_lost_load_range_usd_kwh
        if not 0 < low <= self.economics.value_of_lost_load_usd_kwh <= high:
            raise ValueError(
                "the value of lost load must lie inside its own reported range")
        if self.economics.value_of_lost_load_usd_kwh < self.economics.tariff_usd_kwh:
            raise ValueError(
                "the value of lost load cannot fall below the tariff households pay: "
                "they demonstrably value a kilowatt-hour at least that much")

    def unverified(self) -> list[tuple[str, Provenance]]:
        """Every parameter group nobody has sourced, so the software can say so."""
        found: list[tuple[str, Provenance]] = []

        def walk(obj: Any, path: str) -> None:
            if isinstance(obj, Provenance):
                if not obj.verified:
                    found.append((path, obj))
                return
            if is_dataclass(obj):
                for f in fields(obj):
                    walk(getattr(obj, f.name), f"{path}.{f.name}" if path else f.name)
            elif isinstance(obj, (list, tuple)):
                for i, item in enumerate(obj):
                    walk(item, f"{path}[{i}]")

        walk(self, "")
        return found

    # --------------------------------------------------------------------- files
    def to_dict(self) -> dict:
        return asdict(self)

    def save(self, path: str | Path) -> Path:
        """Write the parameters to a YAML document."""
        import yaml

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(self.to_dict(), sort_keys=False,
                                       allow_unicode=True, default_flow_style=False))
        return path

    @classmethod
    def load(cls, path: str | Path) -> "ProjectSettings":
        """Read parameters from a YAML document, filling anything absent with defaults."""
        import yaml

        raw = yaml.safe_load(Path(path).read_text()) or {}
        settings = cls.from_dict(raw)
        settings.validate()
        return settings

    @classmethod
    def from_dict(cls, raw: dict) -> "ProjectSettings":
        """Build settings from a plain mapping, tolerating omitted sections."""
        def build(kind, value):
            if value is None:
                return None
            if is_dataclass(kind) and isinstance(value, dict):
                kwargs = {}
                for f in fields(kind):
                    if f.name in value:
                        kwargs[f.name] = build(f.type if is_dataclass(f.type) else None,
                                               value[f.name]) or value[f.name]
                return kind(**kwargs)
            return value

        settings = cls()
        for f in fields(cls):
            if f.name not in raw:
                continue
            value = raw[f.name]
            if f.name == "generators":
                setattr(settings, f.name, [
                    GeneratorSpec(**{**g, "provenance": Provenance(**g["provenance"])}
                                  if isinstance(g.get("provenance"), dict) else g)
                    for g in value])
            elif isinstance(value, dict):
                current = getattr(settings, f.name)
                if is_dataclass(current):
                    for key, item in value.items():
                        if not hasattr(current, key):
                            continue
                        # Rebuild a nested record from its own type rather than from its
                        # name. Keying on the name ``provenance`` left every differently
                        # named one — ``diesel_provenance``, ``voll_provenance`` — as a
                        # plain mapping, so a reloaded project reported no unsourced
                        # parameter at all and the one guarantee this file makes was void
                        # for exactly the projects that read their settings from a file.
                        existing = getattr(current, key)
                        if is_dataclass(existing) and isinstance(item, dict):
                            item = type(existing)(**item)
                        setattr(current, key, item)
                else:
                    setattr(settings, f.name, value)
            else:
                setattr(settings, f.name, value)

        # Sections are populated attribute by attribute, which bypasses the normalisation
        # a dataclass does on construction; re-run it so a reloaded project equals itself.
        for f in fields(settings):
            section = getattr(settings, f.name)
            if is_dataclass(section) and hasattr(section, "__post_init__"):
                section.__post_init__()
        return settings


def default_settings() -> ProjectSettings:
    """The parameters this study runs with, as shipped."""
    settings = ProjectSettings()
    settings.validate()
    return settings


# ---------------------------------------------------------------------------- CLI
TEMPLATE_HEADER = """\
# Paramètres du projet — microgrid-expansion
#
# Ce document rassemble tout ce que le modèle a besoin de savoir en dehors des données
# mesurées. Modifiez-le plutôt que le code : les résultats publiés doivent pouvoir être
# archivés avec le jeu de paramètres qui les a produits.
#
# Les blocs « provenance » indiquent d'où vient un paramètre et si quelqu'un l'a vérifié.
# Un paramètre marqué « verified: false » n'a pas été sourcé et ne devrait pas soutenir une
# conclusion publiée sans être remplacé.
#
# Les consommations de carburant sont celles des fiches constructeur, à 50, 75 et 100 % de
# charge ; la courbe de rendement en est déduite. Chaque taille du catalogue porte la
# sienne : c'est ce qui distingue économiquement les tailles entre lesquelles le
# certificat arbitre.
"""


def write_template(path: str | Path) -> Path:
    """Write a documented parameter file for a user to edit."""
    settings = default_settings()
    written = settings.save(path)
    written.write_text(TEMPLATE_HEADER + "\n" + written.read_text())
    return written


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Paramètres du projet.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("template", help="écrire un fichier de paramètres à remplir") \
        .add_argument("--output", default="projet.yaml")
    sub.add_parser("check", help="valider un fichier et signaler le non sourcé") \
        .add_argument("path")

    args = parser.parse_args(argv)
    if args.command == "template":
        path = write_template(args.output)
        print(f"écrit {path}")
        return 0

    settings = ProjectSettings.load(args.path)
    print(f"{args.path} : validé")
    unverified = settings.unverified()
    if not unverified:
        print("tous les paramètres sont sourcés.")
        return 0
    print(f"\n{len(unverified)} groupe(s) de paramètres non vérifiés :")
    for path, provenance in unverified:
        print(f"  {path}")
        print(f"      origine : {provenance.source}")
        if provenance.note:
            print(f"      à faire : {provenance.note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
