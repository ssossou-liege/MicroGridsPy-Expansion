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
    assert solver_limits(settings, "gurobi") == {"TimeLimit": 120}
    assert solver_limits(settings, "highs") == {"time_limit": 120}

    settings.solver.threads = 4
    assert solver_limits(settings, "gurobi") == {"TimeLimit": 120, "Threads": 4}
    # Zero means every core, which is what both solvers do unasked.
    settings.solver.threads = 0
    assert "Threads" not in solver_limits(settings, "gurobi")
    # A solver this project has not met is handed nothing rather than a guess.
    assert solver_limits(settings, "cbc") == {}


def test_the_tolerance_is_left_to_the_solver_and_said_so() -> None:
    """One per cent is declared and a hundredth of that is what every bound used.

    Passing the declared figure would loosen every stored result at once, so it is not
    passed, and the reason is written where the wiring is rather than left to be rediscovered.
    """
    import inspect

    from microgrid_expansion.solve import driver

    assert "mip_gap" not in driver.SOLVER_NAMES.get("gurobi", {})
    assert "tolerance" in inspect.getdoc(driver.solver_limits)


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
