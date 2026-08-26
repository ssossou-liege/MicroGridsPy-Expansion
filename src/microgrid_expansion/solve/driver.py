"""Solve the tree programme, with the project's solver and its silences."""
from __future__ import annotations

from dataclasses import dataclass

from ..settings import ProjectSettings, default_settings


@dataclass
class Solution:
    """What a solve returns beyond the objective."""

    status: str
    objective: float
    seconds: float


def solve(programme, settings: ProjectSettings | None = None, **overrides) -> Solution:
    """Solve a built programme and report its status honestly.

    A programme that does not solve returns an infinite objective rather than raising: over
    a tree, one architecture may hold no feasible plan at all — an array ceiling that no
    inverter in the catalogue can satisfy, say — and that is a result the search uses, not
    an error it should abort on.
    """
    import time

    settings = default_settings() if settings is None else settings
    name = overrides.pop("solver", None) or settings.solver.name
    quiet = {"highs": {"output_flag": False}, "gurobi": {"OutputFlag": 0}}
    if name == "gurobi":
        import gurobipy
        gurobipy.setParam("OutputFlag", 0)

    options = dict(quiet.get(name, {}))
    options.update(overrides)
    started = time.time()
    programme.model.solve(solver_name=name, progress=False, **options)
    status = str(programme.model.status)
    value = (float(programme.model.objective.value) if "ok" in status else float("inf"))
    return Solution(status=status, objective=value, seconds=time.time() - started)
