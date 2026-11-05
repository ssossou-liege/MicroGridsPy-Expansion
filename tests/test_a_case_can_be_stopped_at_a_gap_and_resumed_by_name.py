"""A case may be stopped at a stated gap, and a stopped chain resumed where it broke.

Every case of the value-of-tree study had been solved to the solver's own tolerance, which
on this tree closes to about a hundredth of a per cent in a few minutes. One case does not:
with the central growth trajectory held certain, the search ran five hours and thirty
gigabytes without closing, on a problem its neighbours solve in five minutes. The solution
was there early; what cost the hours was proving that the last sixty-seven dollars of
seventy-eight thousand could not be saved.

So a gap is askable, and these tests hold the three things that makes safe. The gap and the
memory cap reach the solver under the name that solver answers to, and are dropped rather
than renamed for a solver that has no such setting. Asking for neither leaves the default
path exactly as it was, so the cases already solved to tolerance keep their meaning. And a
chain stopped part of the way through can be resumed case by case, so that the nine hours
already spent are not spent again to recover the seventh case.
"""
from __future__ import annotations

import pytest

from microgrid_expansion.exact.tree_value import (SOLVER_OPTION_NAMES, main,
                                                  solver_options_for, weight_cases)


def test_the_gap_and_the_cap_reach_gurobi_under_its_own_names() -> None:
    assert solver_options_for("gurobi", 1e-3, 8.0) == {"MIPGap": 0.001,
                                                       "NodefileStart": 8.0}


def test_a_solver_without_a_memory_cap_is_not_handed_one() -> None:
    """Passing a setting a solver does not know is an error, not a courtesy."""
    assert solver_options_for("highs", 1e-3, 8.0) == {"mip_rel_gap": 0.001}
    assert "nodefile_gb" not in SOLVER_OPTION_NAMES["highs"]


def test_an_unknown_solver_is_asked_for_the_gap_by_the_common_name() -> None:
    assert solver_options_for("cbc", 1e-3, None) == {"mip_rel_gap": 0.001}


def test_asking_for_nothing_changes_nothing() -> None:
    """The default path must stay the default path: no option, no stopping early."""
    assert solver_options_for("gurobi", None, None) == {}
    assert solver_options_for("highs", None, None) == {}


def test_the_cases_carry_the_names_a_resume_is_given() -> None:
    """Resuming by name is only possible if the names are stable across runs."""
    names = [case.name for case in weight_cases(0)]
    assert "central_known" in names and "fast_known" in names
    assert names == [case.name for case in weight_cases(0)]


def test_a_resume_that_names_no_case_of_this_question_is_refused() -> None:
    """Better to stop than to write an empty run over nine hours of records."""
    with pytest.raises(SystemExit):
        main(["--question", "weights", "--only", "no_such_case"])
