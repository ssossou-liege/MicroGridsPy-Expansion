"""A setting a project can declare is read, or it is not there.

An audit of the package found eight figures a developer could set and nobody could use. They
are worse than missing: the interface offers a field, the project saves it, the run ignores
it, and the answer describes a plant nobody asked for. Four of them are wired up here, and
the others were deleted; these tests hold both halves, because a field removed and a field
read look identical from outside until someone adds the field back.

The module's own parameters are the clearest case. ``PhotovoltaicSpec`` carries the nominal
operating cell temperature, the temperature coefficient, the derate and the two Faiman
coefficients; ``yield_model`` had them again as the defaults of ``ModuleSpec``, with the
same values, and used those. A site declared dirtier than the reference was answered with
the reference's yield.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from microgrid_expansion.config import ModelConfig
from microgrid_expansion.settings import default_settings


# ------------------------------------------------------------------- the module
def test_the_module_a_project_describes_is_the_one_the_yield_is_computed_for() -> None:
    from microgrid_expansion.resource.yield_model import ModuleSpec, module_from

    settings = default_settings()
    assert module_from(settings.photovoltaic) == ModuleSpec(), (
        "the default project and the default module no longer agree; one of them moved")

    dirty = default_settings()
    dirty.photovoltaic = replace(dirty.photovoltaic, derate=0.70, noct_c=50.0,
                                 temperature_coefficient_per_k=-0.0045,
                                 faiman_u0_w_m2_k=20.0, faiman_u1_w_s_m3_k=5.0)
    module = module_from(dirty.photovoltaic)
    assert (module.derate, module.noct_c, module.gamma_per_k,
            module.u0_w_m2_k, module.u1_w_s_m3_k) == (0.70, 50.0, -0.0045, 20.0, 5.0)


def test_a_dirtier_array_produces_less() -> None:
    """The derate multiplies the yield, and that is the whole of the test."""
    from microgrid_expansion.resource.yield_model import ModuleSpec, specific_yield

    ghi = np.linspace(0.0, 900.0, 48)
    temperature = np.full(48, 30.0)
    clean = specific_yield(ghi, temperature, ModuleSpec())
    dirty = specific_yield(ghi, temperature, ModuleSpec(derate=0.70))
    assert float(dirty.sum()) == pytest.approx(float(clean.sum()) * 0.70 / 0.85)


def test_the_tree_resource_is_computed_for_the_same_module() -> None:
    """The certified year and the tree it sits in must describe one array."""
    from microgrid_expansion.resource.yield_model import ModuleSpec
    from microgrid_expansion.scenarios import pv_paths

    plain = pv_paths.simulate_stage_pv("ssp245", 0, "Samionta",
                                       np.random.default_rng(0))
    dirty = pv_paths.simulate_stage_pv("ssp245", 0, "Samionta",
                                       np.random.default_rng(0),
                                       module=ModuleSpec(derate=0.70))
    assert float(dirty[0].sum()) == pytest.approx(float(plain[0].sum()) * 0.70 / 0.85)


def test_a_changed_module_changes_the_cached_year_and_the_default_changes_nothing() -> None:
    """A cache that ignores the module would serve the reference array's year.

    Appended only when it differs from the package's, for the reason the roster and the
    community uses are: written into every key, five figures nobody had changed would have
    invalidated every cached year on every machine.
    """
    from microgrid_expansion import instances
    from microgrid_expansion.resource.yield_model import ModuleSpec, module_from

    assert instances._module_fingerprint(module_from(default_settings().photovoltaic)) == ""
    assert instances._module_fingerprint(None) == ""
    moved = instances._module_fingerprint(ModuleSpec(derate=0.70))
    assert moved and "0.7" in moved

    same = dict(site="Samionta", year=2025, trajectory="central", maturity_months=12,
                seed=0, chemistry="lfp")
    assert instances._cache_key(**same) == instances._cache_key(**same, module="")
    assert instances._cache_key(**same) != instances._cache_key(**same, module=moved)


# ------------------------------------------------------------------- the solver
def test_the_limits_a_project_states_reach_the_solver() -> None:
    from microgrid_expansion.solve.driver import solver_limits

    settings = default_settings()
    settings.solver.time_limit_s = 120
    gap = settings.solver.mip_gap
    assert solver_limits(settings, "gurobi") == {"TimeLimit": 120, "MIPGap": gap}
    assert solver_limits(settings, "highs") == {"time_limit": 120, "mip_rel_gap": gap}

    settings.solver.threads = 4
    assert solver_limits(settings, "gurobi") == {"TimeLimit": 120, "MIPGap": gap,
                                                "Threads": 4}
    # Zero means every core, which is what both solvers do unasked.
    settings.solver.threads = 0
    assert "Threads" not in solver_limits(settings, "gurobi")
    # A solver this project has not met is handed nothing rather than a guess.
    assert solver_limits(settings, "cbc") == {}


def test_the_tolerance_a_project_states_is_the_one_its_results_were_computed_at() -> None:
    """The declared figure was the defect, not the wiring.

    One per cent was declared and never passed, while every bound in this repository was
    computed at the solvers' own tolerance, a hundredth of that. Passing the declared
    figure would have loosened all of them at once, and it would have loosened the
    quantity the method exists to measure: the price of the heuristic is of the order of
    five per cent, so a one-per-cent tolerance consumes a fifth of it and the gap reported
    would be partly the solver's slack.

    So the declaration is corrected to the figure the results came from, and then it is
    passed. A study that wants a looser gap says so on its own command line, which the
    driver lets win over the project.
    """
    from microgrid_expansion.solve.driver import solver_limits

    settings = default_settings()
    assert settings.solver.mip_gap == pytest.approx(1e-4), (
        "the declared tolerance is no longer the one every stored bound was computed at")
    assert solver_limits(settings, "gurobi")["MIPGap"] == pytest.approx(1e-4)
    assert solver_limits(settings, "highs")["mip_rel_gap"] == pytest.approx(1e-4)

    settings.solver.mip_gap = 0.02
    assert solver_limits(settings, "gurobi")["MIPGap"] == pytest.approx(0.02)
    assert solver_limits(settings, "highs")["mip_rel_gap"] == pytest.approx(0.02)
    # A solver this project has not met is still handed nothing rather than a guess.
    assert solver_limits(settings, "cbc") == {}


# --------------------------------------------------------------------- the grid
def test_the_grid_declares_no_date_the_plan_cannot_use() -> None:
    """The arrival of the line is a hazard per milestone, not a year.

    ``arrival_year`` was declared, documented as being used by the expansion plan, and read
    by nothing. What the plan actually reads is ``arrival_uncertain`` and the hazard by
    stage, which is the modelling the field's docstring described; the date was the earlier
    design and survived it.
    """
    from microgrid_expansion.settings import GridSpec

    grid = GridSpec()
    assert not hasattr(grid, "arrival_year"), (
        "a date the plan cannot read is declared on the grid specification")
    # What replaced it is read, and the test says where.
    source = (Path(__import__("microgrid_expansion").__file__).parent
              / "scenarios" / "uncertainty_space.py").read_text(encoding="utf-8")
    assert "arrival_uncertain" in source and "arrival_hazard_by_stage" in source


def test_the_configuration_declares_nothing_the_project_already_declares() -> None:
    """Four copies, read by nobody, each a second place to set one thing."""
    cfg = ModelConfig()
    for gone in ("time_limit_s", "mip_gap", "threads", "battery_chemistry"):
        assert not hasattr(cfg, gone), (
            f"{gone} is declared on the configuration as well as in the settings")


# --------------------------------------------------------------------- the site
def test_the_village_is_named_once() -> None:
    from microgrid_expansion.run import _configuration, run

    class _Args:
        site = "Gbowele"
        solver = default_settings().solver.name
        rep_days = 2
        mc_paths = 4
        seed = 0
        stage_years = [0, 5]
        branching = [1, 2]
        network_loss = 0.13

    cfg, settings = _configuration(_Args())
    assert cfg.site == "Gbowele" and settings.site == "Gbowele"
    assert cfg.horizon_years == settings.economics.horizon_years
    assert cfg.discount_rate == pytest.approx(settings.economics.discount_rate)

    # And a pair that disagrees is refused before anything is computed.
    other = default_settings()
    other.site = "Samionta"
    with pytest.raises(ValueError, match="one village per run"):
        run(cfg, settings=other)


# ------------------------------------------------------------ the command line
def test_no_command_offers_an_option_it_does_not_read() -> None:
    """``--n-clusters`` promised a count the operative partition cannot change.

    The segmentation assigns each household-month to the nearest of the four reference
    profiles the appliance calibration fixed. The number of archetypes is a property of
    that table, so the option was not merely unread, it was unreadable.
    """
    import inspect

    from microgrid_expansion.demand import build_mixture_probabilities

    source = inspect.getsource(build_mixture_probabilities)
    assert 'add_argument("--n-clusters"' not in source, "the option is declared again"
    assert "No --n-clusters" in source, "the removal is not explained where it was"
    assert "n_clusters" not in inspect.signature(
        build_mixture_probabilities.assign_clusters_from_reference_profiles).parameters


# -------------------------------------------------------------- the calibration
def _script(name: str) -> str:
    package = Path(__import__("microgrid_expansion").__file__).parent
    return (package / "demand" / name).read_text(encoding="utf-8")


def test_the_calibration_block_holds_only_what_the_offline_scripts_read() -> None:
    """Nine method parameters were declared and read by nobody. Four of them belong here.

    Those four are what the two segmentation scripts take on their command lines, and they
    have to agree with each other: the help text of the outlier threshold asks the reader,
    in words, to keep the value the same as the other script's. Reading both from one place
    is that sentence made structural.

    The other five were constants of the generation code with the same values, and they
    stay there. A figure that reaches the generation has to be in the demand cache key, or
    a project that changes it is served the cached years of the project that did not; and
    putting the block in the key would rebuild every stored year, three hours and a half,
    whenever one of the parameters that cannot reach a cached year was touched. That is the
    defect this cache key was just repaired of, from the other end.
    """
    from dataclasses import fields

    from microgrid_expansion.settings import CalibrationSettings

    assert {f.name for f in fields(CalibrationSettings)} == {
        "n_archetypes", "winsor_lower_quantile", "winsor_upper_quantile",
        "outlier_mad_threshold"}

    clusters = _script("build_monthly_household_clusters.py")
    mixture = _script("build_mixture_probabilities.py")
    for name in ("winsor_lower_quantile", "winsor_upper_quantile",
                 "outlier_mad_threshold"):
        assert f"calibration.{name}" in clusters, name
        assert f"calibration.{name}" in mixture, name
    assert "calibration.n_archetypes" in clusters


def test_a_constant_of_the_generation_is_not_declared_in_the_settings_as_well() -> None:
    """The five that moved out, and where each of them lives now."""
    from microgrid_expansion.demand import generator, maturity, partition
    from microgrid_expansion.settings import CalibrationSettings

    block = CalibrationSettings()
    for gone in ("min_support", "mixture_prior_strength", "maturity_edges_months",
                 "ramp_time_variability", "ramp_window_variability"):
        assert not hasattr(block, gone), f"{gone} is declared in two places"

    assert partition.MIN_SUPPORT == 30
    assert maturity.PRIOR_STRENGTH == 20.0
    assert maturity.MATURITY_EDGES == (-1, 3, 6, 12, 24, 1200)
    assert generator.TIME_VARIABILITY == 0.2
    assert generator.WINDOW_VARIABILITY == 0.15


def test_the_metering_interval_is_stated_once() -> None:
    """A tenth field was declared, read by nobody, and said in the code twice over.

    The interval at which the reference meters report decided two calculations and lived in
    two units: a quarter of an hour where the readings are turned into energy, fifteen
    minutes where a profile is averaged down. Two copies that agreed, which is how a pair of
    copies spends its life until it stops.
    """
    from microgrid_expansion.demand import calibration
    from microgrid_expansion.demand.build_monthly_household_clusters import INTERVAL_HOURS
    from microgrid_expansion.settings import CalibrationSettings

    assert not hasattr(CalibrationSettings(), "meter_interval_minutes")
    assert INTERVAL_HOURS == 0.25
    assert calibration.METER_INTERVAL_MIN == 15
    source = _script("calibration.py")
    assert "INTERVAL_HOURS" in source, (
        "the calibration states the interval itself again instead of reading it")
