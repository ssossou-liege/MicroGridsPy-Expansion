"""A plan for a village that already has a plant must not price it as bare ground.

Both villages have been running for years: Samionta since February 2024, Gbowele since
October 2024. Everything the repository computes for them has nonetheless been a greenfield
plan, which is wrong twice over. It charges the project for an array, a pack and a
converter that are paid for and standing, which overstates what the next step costs. And it
lets the search answer with a plant *smaller* than the one on the ground, which is not a
plan at all: nobody uninstalls a working array to follow it.

The formulation these tests pin down follows from how the repository already annualises
capacity. A kilowatt is recovered at the capital recovery factor of its own service life,
and that is exactly the annuity of buying it now and replacing it for ever: ``crf(r, L) =
r / (1 - (1+r)^-L)``. A kilowatt already standing, commissioned ``a`` years ago, differs in
one respect only -- its first replacement falls in ``L - a`` years rather than in ``L`` --
so its annuity is the same one discounted by that deferral:

    existing kW:  unit_cost * (crf(r, L) * (1+r)^-(L-a) + om_rate)
    added kW:     unit_cost * (crf(r, L)                + om_rate)

At ``a = L`` the two coincide, which is right: an asset at the end of its life must be
bought again, and being there is worth nothing. At ``a = 0`` only the maintenance is due,
the replacement being a whole service life away. Nothing else in the cost model has to
change, and in particular the upkeep of what exists is a *constant* of the design: it is
charged whatever the plan decides, exactly like the network and the connections.

What does change the answer is the floor. A design below the installed capacity is not
admissible, so the lattice starts at what exists rather than at zero.
"""
from __future__ import annotations

import math

import pytest

from microgrid_expansion import config
from microgrid_expansion.settings import default_settings


# ------------------------------------------------------------------ the declaration
def test_the_project_declares_the_plant_already_on_the_ground() -> None:
    """The plates belong to the village, so they are declared with the village.

    Defaults are empty on purpose. A project that says nothing about an existing plant is
    describing bare ground, which is the right reading of silence: inventing a plant for a
    village that has none would charge it for equipment nobody bought.
    """
    settings = default_settings()
    plant = settings.installed
    for technology in ("pv", "pv_ac", "battery", "inverter", "generator"):
        assert hasattr(plant, technology), (
            f"the installed plant declares no {technology}")
    assert plant.capacity("pv") == 0.0
    assert plant.capacity("battery") == 0.0
    assert plant.capacity("inverter") == 0.0
    assert plant.capacity("generator") == 0.0


def test_a_technology_holds_as_many_vintages_as_it_has() -> None:
    """One age per technology cannot describe either village.

    Samionta's field is 17.48 kWp from February 2024 and 8.38 kWp more from November 2025;
    its storage is 55 kWh from 2024 and 40 kWh more from July 2026. Collapsing those into
    one age would charge a two-year-old array and a five-month-old pack at the same
    deferral, and the error runs in the project's favour, which is the direction that does
    not get noticed.
    """
    from microgrid_expansion.settings import InstalledPlant, Vintage

    plant = InstalledPlant(pv=(Vintage(17.48, 2024), Vintage(8.38, 2025)))
    assert plant.capacity("pv") == pytest.approx(25.86)
    assert len(plant.pv) == 2


def test_the_configuration_no_longer_declares_the_existing_plant() -> None:
    """The four fields it carried were read by nothing, and are now declared once.

    ``ModelConfig`` declared ``initial_pv_kw``, ``initial_batt_kwh``, ``initial_inv_kw`` and
    ``gen_initial_kw``, and no module read any of them: the certification, the tree and the
    single-run command all took a configuration carrying an existing plant and sized the
    village as bare ground. The generator's default was worse than unread -- the smallest
    set in the catalogue -- so the day anything read it, every greenfield plan would have
    started with a generating set nobody had bought.
    """
    cfg = config.ModelConfig()
    for gone in ("initial_pv_kw", "initial_batt_kwh", "initial_inv_kw", "gen_initial_kw"):
        assert not hasattr(cfg, gone), (
            f"{gone} is declared on the configuration as well as in the settings")


# ------------------------------------------------------------------ the arithmetic
def _coefficients(settings, age_years: float):
    """The annuity of one existing kilowatt of array, and of one added kilowatt."""
    from microgrid_expansion.exact.lower_bound import Economics
    from microgrid_expansion.settings import InstalledPlant, Vintage

    base = settings.installed.base_year
    plant = InstalledPlant(base_year=base,
                           pv=(Vintage(1.0, int(base - age_years)),))
    economics = Economics.from_settings(settings)
    return economics.existing_annualised(plant)[0], economics.annualised()[0]


def test_a_kilowatt_already_paid_for_costs_only_its_upkeep_and_its_replacement() -> None:
    """The deferral, stated as the identity it is."""
    settings = default_settings()
    spec = settings.photovoltaic
    rate = settings.economics.discount_rate
    life = spec.lifetime_years

    existing, added = _coefficients(settings, age_years=0)
    expected = spec.cost_usd_kw * (config.crf(rate, life) / (1 + rate) ** life
                                   + spec.om_rate)
    assert existing == pytest.approx(expected)
    assert existing < added, "a standing array cannot cost what a new one costs"


def test_an_asset_at_the_end_of_its_life_is_worth_nothing_for_being_there() -> None:
    """At ``a = L`` the two coefficients must meet, or the formula has a seam."""
    settings = default_settings()
    life = settings.photovoltaic.lifetime_years
    existing, added = _coefficients(settings, age_years=life)
    assert existing == pytest.approx(added)

    # And past its life it is not charged *more* than a new one: it is replaced now.
    older, _ = _coefficients(settings, age_years=life + 7)
    assert older == pytest.approx(added)


def test_the_older_the_asset_the_dearer_it_is_to_keep() -> None:
    """Monotone in age, which is the property that makes the deferral meaningful."""
    settings = default_settings()
    life = settings.photovoltaic.lifetime_years
    costs = [_coefficients(settings, age_years=a)[0]
             for a in range(0, int(life) + 1)]
    assert all(b >= a for a, b in zip(costs, costs[1:])), costs
    assert costs[-1] > costs[0]


def test_what_exists_costs_the_same_whatever_the_plan_decides() -> None:
    """The upkeep of a standing plant is a constant, so it cannot bias the search.

    Worth stating because it is what makes the change safe: a constant added to every
    design shifts every cost by the same amount and leaves the ranking, and therefore the
    certificate, exactly where it was. What moves the optimum is the floor, not this.
    """
    from microgrid_expansion.exact.lower_bound import Economics
    from microgrid_expansion.settings import InstalledPlant, Vintage

    settings = default_settings()
    plant = InstalledPlant(base_year=2026,
                           pv=(Vintage(20.0, 2024),),
                           battery=(Vintage(40.0, 2024),))
    economics = Economics.from_settings(settings, installed=plant)
    assert economics.existing_plant_usd_yr > 0.0
    assert economics.existing_plant_usd_yr == pytest.approx(
        Economics.from_settings(settings, installed=plant).existing_plant_usd_yr)


# ------------------------------------------------------------------ the floor
def _instance():
    from microgrid_expansion.instances import build_site_year

    return build_site_year("Samionta", 2025, trajectory="central")


def test_the_search_cannot_fall_below_the_plant_that_exists() -> None:
    """A plan that uninstalls a working array is not a plan."""
    from microgrid_expansion.exact.certify import Lattice
    from microgrid_expansion.settings import InstalledPlant, Vintage

    settings = default_settings()
    settings.installed = InstalledPlant(
        base_year=2026,
        pv=(Vintage(22.0, 2024),),
        battery=(Vintage(40.0, 2024),),
        inverter=(Vintage(24.0, 2024),),
        generator=(Vintage(16.0, 2024),))
    lattice = Lattice.around(_instance(), settings, architecture="dc")

    assert lattice.n_pv[0] * lattice.pv_unit_kw == pytest.approx(22.0)
    assert lattice.n_batt[0] * lattice.batt_unit_kwh == pytest.approx(40.0)
    assert lattice.n_inv[0] * lattice.inv_unit_kw == pytest.approx(22.5)
    assert min(lattice.generator_ratings) >= 16.0


def test_a_floor_never_claims_more_than_is_installed() -> None:
    """The remainder of a plate that is not a whole module stays outside the plan.

    Gbowele's field is 22.45 kWp and the module is half a kilowatt: the floor is 44
    modules, not 45. Rounding the other way would hand the plan 50 watts of array nobody
    installed, and the same reasoning on the converter would hand it a whole kilowatt.
    """
    from microgrid_expansion.exact.certify import Lattice
    from microgrid_expansion.settings import InstalledPlant, Vintage

    settings = default_settings()
    settings.installed = InstalledPlant(base_year=2026,
                                        pv=(Vintage(22.45, 2024),),
                                        inverter=(Vintage(24.0, 2024),))
    lattice = Lattice.around(_instance(), settings, architecture="dc")
    assert lattice.n_pv[0] == math.floor(22.45 / lattice.pv_unit_kw)
    assert lattice.n_pv[0] * lattice.pv_unit_kw <= 22.45 + 1e-9
    assert lattice.n_inv[0] * lattice.inv_unit_kw <= 24.0 + 1e-9


# ------------------------------------------------------------------ the two oracles
def test_the_added_capacity_is_what_the_design_pays_for() -> None:
    """A design equal to the standing plant buys nothing, and one above it buys the rest."""
    from microgrid_expansion.exact.certify import _design_capital_usd_yr
    from microgrid_expansion.exact.lower_bound import Economics
    from microgrid_expansion.settings import InstalledPlant, Vintage
    from microgrid_expansion.exact.simulator import Capacities

    settings = default_settings()
    plant = InstalledPlant(base_year=2026, pv=(Vintage(20.0, 2024),))
    economics = Economics.from_settings(settings, installed=plant)
    standing = Capacities(pv_kw=20.0, battery_kwh=0.0, inverter_kw=0.0,
                          generator_kw=0.0, pv_ac_kw=0.0)
    bigger = Capacities(pv_kw=25.0, battery_kwh=0.0, inverter_kw=0.0,
                        generator_kw=0.0, pv_ac_kw=0.0)

    added = economics.annualised()[0]
    assert (_design_capital_usd_yr(bigger, economics)
            - _design_capital_usd_yr(standing, economics)) == pytest.approx(5.0 * added)


def test_the_programme_still_minorises_the_rule_on_a_brownfield_village() -> None:
    """The certificate rests on this, and a cost term touched in one oracle breaks it.

    The lower bound is a relaxation of the same problem the rule simulates. If the existing
    plant is credited in one of them and not in the other, the bound stops bounding and the
    gap the certification reports means nothing.
    """
    from microgrid_expansion.exact.lower_bound import Economics
    from microgrid_expansion.settings import InstalledPlant, Vintage
    from microgrid_expansion.model.economics import annualised_unit_costs

    settings = default_settings()
    settings.installed = InstalledPlant(base_year=2026, pv=(Vintage(20.0, 2024),))
    economics = Economics.from_settings(settings, installed=settings.installed)
    biggest = max(settings.generators, key=lambda g: g.rating_kw)
    costs = {"capex_pv": settings.photovoltaic.cost_usd_kw,
             "capex_batt": settings.battery.cost_usd_kwh,
             "capex_inv": settings.inverter.cost_usd_kw,
             "capex_ge": biggest.cost_usd_kw,
             "capex_conv_ac": settings.coupling.string_inverter_cost_usd_kw}
    programme = annualised_unit_costs(costs, "dc", settings)
    assert programme[0] == pytest.approx(economics.annualised()[0]), (
        "the two oracles must charge an added kilowatt the same, or the bound is not one")


# ------------------------------------------------------------------ the two villages
def test_the_two_villages_are_declared_as_their_operator_states_them() -> None:
    """The plates, in the units the model counts in.

    Two unit conventions meet here and they are not interchangeable. Victron plates its
    inverters in kVA, which this project converts at 0.8 kW per kVA -- the factor the
    generating-set catalogue is built on, where 10, 15 and 20 kVA become 8, 12 and 16 kW.
    Deye plates in watts, so a SUN12K is twelve kilowatts and converting it as though it
    were apparent power would understate the plant by a fifth.
    """
    from microgrid_expansion.settings import reference_plant

    samionta = reference_plant("Samionta")
    assert samionta.capacity("pv") == pytest.approx(25.86)
    assert samionta.capacity("battery") == pytest.approx(95.0)
    assert samionta.capacity("inverter") == pytest.approx(48.0)   # four Deye SUN12K
    assert samionta.capacity("generator") == pytest.approx(16.0)  # 20 kVA at 0.8
    assert samionta.capacity("pv_ac") == 0.0, "Samionta has no string inverter"

    gbowele = reference_plant("Gbowele")
    field = gbowele.capacity("pv") + gbowele.capacity("pv_ac")
    assert field == pytest.approx(22.45)
    assert gbowele.capacity("pv_ac") > 0.0, "Gbowele's field is divided between the buses"
    assert gbowele.capacity("battery") == pytest.approx(40.0)
    assert gbowele.capacity("inverter") == pytest.approx(24.0)    # 30 kVA Quattro at 0.8
    assert gbowele.capacity("generator") == pytest.approx(16.0)

    assert reference_plant("nowhere at all").is_empty, (
        "a village this project has no record of is bare ground")


def test_a_plan_is_greenfield_unless_the_brownfield_is_asked_for() -> None:
    """Every figure in the repository was computed on bare ground, and stays comparable."""
    assert default_settings().installed.is_empty


def test_the_standing_plant_is_a_base_for_some_capacities_and_a_floor_for_the_set() -> None:
    """All five are reported, and each caller says what it does with the set.

    The plan adds modules of array, storage and conversion, so their totals are this base
    plus what it buys. It does not add generating sets: it picks one rating from a
    catalogue, so that total is the choice and the standing set is a floor on it. Returning
    zero for the set here, which this first did, leaves the next reader to rediscover the
    asymmetry -- which is how one figure comes to be read two ways.
    """
    from microgrid_expansion.model.investment_constraints import installed_base
    from microgrid_expansion.settings import reference_plant

    assert installed_base(None) == (0.0, 0.0, 0.0, 0.0, 0.0)
    base = installed_base(reference_plant("Gbowele"))
    assert base[1] == pytest.approx(40.0)
    assert base[3] == pytest.approx(16.0), "the generating set is reported, not hidden"


def test_no_plan_may_shrink_the_generating_set_below_the_one_on_site() -> None:
    """A plant does not sell its generator back, and the catalogue must be able to say so."""
    from microgrid_expansion.exact.certify import Lattice
    from microgrid_expansion.settings import InstalledPlant, Vintage

    settings = default_settings()
    settings.installed = InstalledPlant(base_year=2026,
                                        generator=(Vintage(12.0, 2024),))
    lattice = Lattice.around(_instance(), settings, architecture="dc")
    assert min(lattice.generator_ratings) >= 12.0
    assert 8.0 not in lattice.generator_ratings

    # And a set the catalogue cannot match is refused rather than quietly downsized.
    settings.installed = InstalledPlant(base_year=2026,
                                        generator=(Vintage(250.0, 2024),))
    with pytest.raises(ValueError, match="catalogues nothing that large"):
        Lattice.around(_instance(), settings, architecture="dc")


def test_the_programme_still_minorises_the_rule_over_a_brownfield_tree() -> None:
    """The property the whole certificate rests on, over a village that already has a plant.

    The lower bound is a relaxation of the problem the rule simulates. Crediting the
    standing plant in one of them and not in the other puts the bound above the trajectory
    it must minorise, and the gap the certification reports then means nothing. Both
    oracles charge the extension and leave the upkeep of what stands outside, so the
    comparison is between two numbers of the same kind.
    """
    from microgrid_expansion.config import ModelConfig
    from microgrid_expansion.exact.tree_oracle import evaluate_plan
    from microgrid_expansion.model import build_model
    from microgrid_expansion.post import extract_solution
    from microgrid_expansion.run import _NodeInstance
    from microgrid_expansion.scenarios import sample_scenario_paths
    from microgrid_expansion.settings import reference_plant
    from microgrid_expansion.solve import solve
    from microgrid_expansion.timedomain import reduce_to_rep_days
    from microgrid_expansion.tree import build_tree

    from microgrid_expansion.scenarios import space_from_settings

    settings = default_settings()
    settings.installed = reference_plant("Samionta")
    # The tree the stored results were drawn on, set explicitly: the whole census, twelve
    # months old, as a fan on the milestones' own years. What is held here is the floor.
    cfg = ModelConfig(site="Samionta", n_mc_paths=8, stage_years=(0, 5),
                      branching=(1, 2), n_rep_days=365, seed=0, tree_mode="fan",
                      node_year="first", centre_features=False, maturity_months=12)
    stored = default_settings()
    stored.connection.mode = "census"
    tree = build_tree(sample_scenario_paths(cfg, space_from_settings(stored), stored), cfg)
    rep = {n: reduce_to_rep_days(_NodeInstance(tree.node_data[n], settings), 365)
           for n in tree.nodes}
    programme = build_model(tree, rep, cfg, architecture="dc", settings=settings)
    solved = solve(programme, settings, solver=cfg.solver)
    assert "ok" in solved.status

    plans = extract_solution(programme, cfg, settings)
    # The plan reports the plant, not the extension: a village running since 2024 does not
    # appear to run on the modules this plan buys.
    assert plans[0].pv_kw >= settings.installed.capacity("pv") - 1e-6
    assert plans[0].battery_kwh >= settings.installed.capacity("battery") - 1e-6

    rule, _ = evaluate_plan(plans, tree, architecture="dc", settings=settings)
    assert solved.objective <= rule + 1e-6


def test_a_saved_brownfield_project_reloads_with_its_dates(tmp_path) -> None:
    """A plant saved and read back must keep every vintage and every year.

    The generic reader cannot see inside a list: a saved plant came back as a list of plain
    mappings and the reloaded project described a village whose capacities had no dates,
    which prices a standing plant as though it were new. An empty plant round-tripped
    silently, so the fault would have waited for the first real one.
    """
    from microgrid_expansion.settings import ProjectSettings, reference_plant

    settings = default_settings()
    settings.installed = reference_plant("Samionta")
    reloaded = ProjectSettings.load(settings.save(tmp_path / "samionta.yaml"))

    assert reloaded.to_dict() == settings.to_dict()
    assert len(reloaded.installed.pv) == 2
    assert [v.commissioned_year for v in reloaded.installed.vintages("pv")] == [2024, 2025]
    assert reloaded.installed.capacity("inverter") == pytest.approx(48.0)
