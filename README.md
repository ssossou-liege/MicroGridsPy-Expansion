# microgrid-expansion (Development in Progress...)

A multi-stage stochastic capacity-expansion model for sizing off-grid microgrids
(PV array + diesel generator + battery + hybrid inverter + community load)
under uncertainty.

The model is an adaptive multi-stage stochastic program formulated on a scenario
tree and solved as a single deterministic-equivalent MILP with
[linopy](https://linopy.readthedocs.io/) (HiGHS by default, Gurobi optional). Unlike a cost-optimal dispatch, the operational layer encodes the **uGrid rule-based generation-balance control** as binary-light MILP constraints.

## Layout

```Check the development status in docs/ROADMAP.md```

```
docs/formulation/model.tex   Academic formulation (sets, parameters, variables,
                             constraints, objective, scenario construction).
data/                        Measured and calibrated inputs (see data/README.md).
src/microgrid_expansion/     Implementation:
  scenarios/                 Monte-Carlo sampling of the four uncertainty families.
  tree/                      Scenario reduction and scenario-tree construction.
  timedomain/                Representative-day (k-medoids) time-domain reduction.
  model/                     linopy variables, constraints, economics, model assembly.
  solve/                     Solver driver (HiGHS / Gurobi).
  post/                      Solution extraction, KPIs (NPC / LCOE), reporting.
  demand/                    Behavioural clustering and mixture probabilities from
                             measured meter readings (calibration of the RAMP inputs).
  exact/                     Certified sizing under the rule-based controller:
                             dispatch oracles and branch-and-simulate.
  run.py                     End-to-end orchestrator.
tests/                       Assembly, dispatch-fidelity and benchmark checks.
```

## Quick start

```bash
conda env create -f environment.yml
conda activate mgpy_dev
pip install -e .
python -m microgrid_expansion.run        # build tree -> assemble MILP -> solve -> KPIs
```

## Modelling choices

- **Structure:** adaptive multi-stage stochastic program on a scenario tree
  (two-stage is the special case of a single investment node at year 0).
- **Objective:** risk-neutral — minimise probability-weighted expected discounted
  total cost; report LCOE.
- **Dispatch:** uGrid generation-balance control encoded as MILP constraints, one
  binary per timestep (generator on/off).
- **Design variables:** integer increments of capacity (PV panels, battery modules)
  plus discrete generator/inverter catalogs, decided per tree node with
  structural non-anticipativity.

See [docs/formulation/model.tex](docs/formulation/model.tex) for the full mathematical
formulation.
