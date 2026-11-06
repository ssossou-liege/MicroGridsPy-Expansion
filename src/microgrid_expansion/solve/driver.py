"""Solve the tree programme, with the project's solver and its silences."""
from __future__ import annotations

from dataclasses import dataclass

from ..settings import ProjectSettings, default_settings


@dataclass
class Solution:
    """What a solve returns beyond the objective.

    ``objective`` is the best feasible plan the solver found. On a mixed-integer programme
    that is an *upper* bound on the programme's own optimum, because the solver stops at a
    tolerance rather than at zero; ``dual_bound`` is the guaranteed lower one. The two are
    not interchangeable, and the difference decides whether a certificate is a certificate:
    a bound used to discard a box must minorise every plan in it, and the incumbent does
    not. On this tree the two differ by of the order of a hundredth of a per cent, which is
    small enough to be invisible and large enough to prune the optimum.
    """

    status: str
    objective: float
    seconds: float
    dual_bound: float = float("nan")

    @property
    def bound(self) -> float:
        """The value safe to use as a lower bound, whatever the solver reported."""
        if self.objective == float("inf"):
            return float("inf")
        if self.dual_bound != self.dual_bound:            # no dual bound was available
            return self.objective
        return min(self.dual_bound, self.objective)

    @property
    def mip_gap(self) -> float:
        """Relative distance still open between the incumbent and the dual bound."""
        if self.objective in (float("inf"), 0.0) or self.dual_bound != self.dual_bound:
            return float("nan")
        return abs(self.objective - self.dual_bound) / abs(self.objective)


#: What the project's solver settings are called by each solver. A limit declared and never
#: passed is worse than no limit: the figure sits in the settings, the interface offers it,
#: and the solve runs until it finishes whatever the project asked for.
SOLVER_NAMES = {
    "gurobi": {"time_limit_s": "TimeLimit", "threads": "Threads", "mip_gap": "MIPGap"},
    "highs": {"time_limit_s": "time_limit", "threads": "threads",
              "mip_rel_gap": "mip_rel_gap"},
}


def solver_limits(settings: ProjectSettings, name: str) -> dict:
    """The project's solver limits, under the names ``name`` answers to.

    The time limit is always passed. Threads are passed only when the project names a
    number: zero means *every core*, which is already what both solvers do, and sending it
    explicitly would differ from the default on a solver this project has not met.

    The tolerance is passed as well, and the figure it passes was the defect rather than
    the wiring: one per cent was declared and never sent, while every bound here was
    computed at the solvers' own tolerance, a hundredth of that. Sending the declared
    figure would have loosened every stored result at once, and the gap a certificate
    reports would have been partly the solver's slack rather than the price of myopia. The
    declaration is now the figure the results came from, so it can be sent.
    """
    names = SOLVER_NAMES.get(name, {})
    limits = {}
    if "time_limit_s" in names and settings.solver.time_limit_s:
        limits[names["time_limit_s"]] = int(settings.solver.time_limit_s)
    gap = next((names[key] for key in ("mip_gap", "mip_rel_gap") if key in names), None)
    if gap is not None and settings.solver.mip_gap:
        limits[gap] = float(settings.solver.mip_gap)
    if "threads" in names and settings.solver.threads:
        limits[names["threads"]] = int(settings.solver.threads)
    return limits


def _dual_bound(model) -> float:
    """The solver's own guaranteed lower bound, by whichever name it gives it.

    Returned as ``nan`` when the solver does not expose one -- a pure linear programme has
    no gap to report, and a solver this project has not met should degrade to the incumbent
    rather than to a wrong number.
    """
    backend = getattr(model, "solver_model", None)
    if backend is None:
        return float("nan")
    for attribute in ("ObjBound", "objbound"):            # Gurobi
        value = getattr(backend, attribute, None)
        if isinstance(value, (int, float)):
            return float(value)
    try:                                                   # HiGHS
        return float(backend.getInfo().mip_dual_bound)
    except Exception:                                      # noqa: BLE001 - absent is fine
        return float("nan")


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
    options.update(solver_limits(settings, name))
    # What the caller asks for wins over what the project declares: a study that states a
    # tolerance or a memory cap for one solve is saying something the settings cannot.
    options.update(overrides)
    started = time.time()
    programme.model.solve(solver_name=name, progress=False, **options)
    status = str(programme.model.status)
    value = (float(programme.model.objective.value) if "ok" in status else float("inf"))
    dual = _dual_bound(programme.model) if "ok" in status else float("nan")
    return Solution(status=status, objective=value, seconds=time.time() - started,
                    dual_bound=dual)
