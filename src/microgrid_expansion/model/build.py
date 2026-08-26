"""Assemble the deterministic-equivalent programme over the scenario tree.

This is the *lower* oracle of the certification, generalised from one year to the tree: it
answers what a plan would cost under perfectly anticipative dispatch. The upper oracle
remains the controller, simulated node by node, because no formulation of it exists to hand
a solver — which is the premise of the whole method rather than a limitation of this module.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..config import ModelConfig
from ..exact.lower_bound import fuel_minorant
from ..exact.simulator import BatteryModel, GeneratorModel
from ..settings import ProjectSettings, default_settings
from ..timedomain.rep_days import RepDays
from ..tree.tree_model import ScenarioTree
from .coords import build_coords
from .dispatch_constraints import add_dispatch_constraints
from .economics import add_objective
from .investment_constraints import add_investment_constraints
from .variables import add_variables


@dataclass
class TreeProgramme:
    """A built programme and what is needed to read its solution back."""

    model: object
    coords: object
    variables: dict
    architecture: str


def catalogue_minorant(settings: ProjectSettings, cfg: ModelConfig) -> tuple[float, float]:
    """A fuel line lying below every unit of the catalogue.

    The programme chooses which generating set to install, so its fuel model must minorise
    whichever it picks. Taking the minorant of one unit — the largest, say — and applying it
    to a plan that installs the smallest charges the programme the efficiency of a machine it
    did not buy: the small unit burns a quarter more per kilowatt-hour, and the difference
    lands squarely in the price of the heuristic, which is measured between this programme
    and a simulation that does use the right curve.
    """
    from ..exact.simulator import GeneratorModel

    intercepts, slopes = [], []
    for spec in settings.generators:
        model = GeneratorModel.from_spec(spec, settings.economics.diesel_price_usd_l)
        intercept, slope = fuel_minorant(model, spec.rating_kw)
        intercepts.append(intercept)
        slopes.append(slope)
    return min(intercepts), min(slopes)


def node_data(tree: ScenarioTree, rep: dict[int, RepDays]) -> dict[int, dict]:
    """Reduced operating arrays per node, on the ``(rday, htod)`` grid."""
    blocks = {}
    for node in tree.nodes:
        days = rep[node]
        blocks[node] = {
            "demand": days.demand,
            "yield": days.specific_yield,
            "usable": days.usable_fraction,
            "retention": 1.0 - np.clip(days.self_discharge, 0.0, 1.0),
            "weights": days.weight,
            "costs": tree.node_data[node].costs,
        }
    return blocks


def build_model(tree: ScenarioTree, rep: dict[int, RepDays], cfg: ModelConfig,
                architecture: str = "dc", relax_commitment: bool = True,
                settings: ProjectSettings | None = None,
                opening_condition: str = "fixed") -> TreeProgramme:
    """Build the tree-wide programme for one coupling architecture."""
    import linopy

    settings = default_settings() if settings is None else settings
    coords = build_coords(tree, rep, cfg)
    battery = BatteryModel.from_spec(settings.battery)
    biggest = max(settings.generators, key=lambda g: g.rating_kw)
    generator = GeneratorModel.from_spec(biggest, settings.economics.diesel_price_usd_l)

    model = linopy.Model()
    variables = add_variables(model, coords, relax_commitment=relax_commitment)
    add_investment_constraints(model, variables, coords, cfg, architecture=architecture)
    data = node_data(tree, rep)
    add_dispatch_constraints(model, variables, coords, cfg, data, battery, generator,
                             architecture=architecture,
                             opening_condition=opening_condition)
    add_objective(model, variables, coords, cfg, data, generator,
                  catalogue_minorant(settings, cfg),
                  architecture=architecture, settings=settings)
    return TreeProgramme(model=model, coords=coords, variables=variables,
                         architecture=architecture)
