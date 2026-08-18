"""Assembly / shape check.

Build a minimal tree (single node, single representative day) and confirm the linopy
model assembles, solves, and reproduces the reference stage-3 dispatch on identical
inputs under the ``baseline`` variant. (Verification step 1 in the plan.)
"""
import pytest

from microgrid_expansion.config import ModelConfig


@pytest.mark.skip(reason="Skeleton: implement once model layer is filled in.")
def test_tiny_tree_assembles_and_solves():
    cfg = ModelConfig(
        stage_years=(0,),
        branching=(1,),
        n_mc_paths=1,
        n_rep_days=1,
        dispatch_variant="baseline",
    )
    cfg.validate()
    # paths = sample_scenario_paths(cfg)
    # tree = build_tree(paths, cfg)
    # rep = {0: reduce_to_rep_days(tree.node_data[0], 1, 0)}
    # model = build_model(tree, rep, cfg)
    # result = solve(model, cfg)
    # assert result.status == "ok"
    raise NotImplementedError
