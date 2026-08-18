# Roadmap — microgrid-expansion

Next moves for the multi-stage stochastic capacity-expansion model and its core
contribution: **certified-optimal sizing under the fixed rule-based dispatch controller**
(dispatch-relaxation lower bound + branch-and-simulate; the "price of the heuristic
dispatch"). See [docs/formulation/model.tex](formulation/model.tex), section
*Certified-optimal sizing under the rule-based dispatch policy*.

The project is built **one layer at a time**: each layer is completed, tested and
documented before the next one starts, so that at every moment the repository contains a
working model rather than a scaffold. Layers are numbered L0–L5 and supersede the earlier
phase numbering.

---

## Current state (2026-08-18)

**Working**

- ✅ Formulation document (`docs/formulation/model.tex`) — sets, parameters, variables,
  constraints, objective, scenario construction, **+ the certified-optimality section**
  (Assumption 1, Proposition 1, branch-and-simulate, price of the heuristic, parameterised
  rule class). Compiles.
- ✅ Prototype of the contribution: `src/microgrid_expansion/exact/` (`dispatch.py`,
  `branch_and_simulate.py`, `controller.py`, `brownfield.py`, `plot.py`).
  Single-day toy result: `z_B* = (30 PV, 10 batt)` vs `z_A* = (29, 8)`, price 3.3 %,
  proven optimal, 120 rule simulations + 171 LPs against 697 by enumeration.
  Figure `results/branch_and_simulate_lattice.png`.
- ✅ Test suite green (19 passed, 3 skipped) under the `mgpy_dev` conda environment.
- ✅ Measured demand data for the two reference sites (Gbowele, Samionta): meter readings,
  household roster, monthly behavioural clustering and hierarchical Dirichlet-multinomial
  mixture probabilities — `src/microgrid_expansion/demand/`, outputs in
  `data/ramp_params/reference/`.
- ✅ RAMP appliance calibration per behavioural cluster —
  `data/ramp_params/reference/cluster_params.csv` (4 clusters, 7 appliance classes).
- ✅ Hourly ERA5-Land series 2016–2025 for both sites — irradiance, temperature and wind
  — plus the CMIP6 downscaling chain for the scenario tree (`resource/era5.py`,
  `resource/cmip6.py`, `data/irradiance/`).
- ✅ Literature scan: contribution confirmed novel.

**Not yet working**

- ⬜ The main pipeline (`scenarios → tree → timedomain → model → solve → post`) is still a
  skeleton: 15 modules raise `NotImplementedError`, so `python -m microgrid_expansion.run`
  stops at the first stub.
- ⬜ The oracles are still the single-day toy: no real 8760 demand, no real specific yield,
  no real net-present-cost accounting behind the certificate.
- ⬜ No stochastic demand generator yet: the calibration exists, but nothing turns it into
  an 8760-hour community profile.
- ⬜ No representative-day reduction (`k`-medoids to be implemented in-repo; the
  `scikit-learn-extra` package is unmaintained and binary-incompatible with NumPy ≥ 2).

---

## L0 — Foundations & housekeeping ✅ (2026-08-18)

- [x] **Repair the environment.** The editable install pointed at the repository's former
  path, so `import microgrid_expansion` failed everywhere. Reinstalled in `mgpy_dev`;
  added `pyarrow` (parquet) and `python-docx`; `environment.yml` and `pyproject.toml`
  brought in line with what is actually used.
  *Done when* `python -m pytest tests/ -q` passes — it does.
- [x] **Remove the external-repository references** from the source, the tests and the
  documentation; provenance is now stated by describing the data, not by naming a path.
- [x] **Make `demand/` an importable layer** — package `__init__`, a central path module,
  and a library API beside the command-line entry points. The default input/output paths
  previously raised, so neither script could run as documented.
- [x] **Restore reproducibility of the demand calibration.** The segmentation and the
  mixture model used different robust-outlier thresholds (4.0 vs 4.5), so re-running the
  segmentation with its documented defaults silently produced a *different* partition
  from the one the committed calibration and the RAMP appliance parameters rest on
  (4 recomposed clusters, 10 extra outliers, permuted labels). Thresholds harmonised at
  4.5; `tests/test_demand_calibration.py` now asserts exact reproduction of the committed
  reference CSVs from the raw readings.

---

## L1 — Data layer: one site, one year (P0, largely done 2026-08-18)

Goal: for a given site and calendar year, produce the two 8760-hour series the model
consumes — community demand `D` [kW] and photovoltaic specific yield `Y` [kW/kW] — from
the measured and calibrated inputs, reproducibly and with a seed.

- [x] **Site registry** (`sites.py`). Census, data files and coordinates per site; the
  pipeline resolves everything through `get_site(name)`. Samionta and Gbowele both
  registered. Two gaps recorded rather than guessed: Samionta's coordinates are unknown,
  and Gbowele has no irradiance series yet.
- [x] **Demand generator** (`demand/generator.py`). Community composition drawn from the
  twelve monthly posterior mixtures, one RAMP user per household so the fractional
  calibrated appliance counts are honoured in expectation, minute-resolution simulation
  aggregated to hourly kW, twelve months concatenated into a year. Runs in ~75 s.
  Validation (`python -m microgrid_expansion.demand.validate`): annual energy **+7.0 %**
  against the measured extrapolation, seasonal amplitude 2.22x against 2.09x measured,
  month-to-month correlation **0.863**.
- [x] **Archetype moment-matching** (`demand/calibration.py`). The appliance calibration
  does not on its own reproduce the measured archetype statistics (see below), so two
  factors per archetype — a power scale and a duration scale — are fitted against the
  measured daily energy and peak. Residuals after fitting: ~8 % on energy, ~10 % on peak.
  Factors stored in `data/ramp_params/reference/archetype_scaling.csv`.
- [x] **Specific-yield converter** (`resource/yield_model.py`). NOCT cell-temperature
  model, module temperature coefficient and derating; also exposes the battery
  usable-capacity factor `F^e` and self-discharge `A`. Samionta 2024 under a stated
  isothermal assumption: **1 394 kWh/kW**, capacity factor 0.159 — plausible at 7.6° N.
- [x] **Meteorological series re-acquired from ERA5-Land** for both sites, carrying
  irradiance, two-metre temperature and ten-metre wind (2016–2025, 87 672 h). The
  acquisition moved into the package (`resource/era5.py`, `resource/cmip6.py`) with the
  script reduced to a CLI over it. Two conversion conventions were verified against the
  computed solar noon and are now pinned by tests. Specific yield with measured
  temperature and wind through a Faiman cell model: Samionta 1 389–1 453 kWh/kW,
  Gbowele 1 440–1 508 kWh/kW.
- [ ] **Re-calibrate the appliance sets of C0 and C3.** Their calibrated stock amounts to
  85 W and 83 W installed against measured peaks of 413 W and 200 W: the appliance list
  cannot physically produce the observed peaks, so high-power appliances are missing. The
  moment-matching correction compensates in aggregate (power factors 9.4 and 5.2) but a
  scale factor is not a substitute for the missing appliances.

---

## L2 — Real oracles and real economics on one site (P0)

Goal: replace the toy instance with the real ones, on L1's data, single scenario. This is
the minimum publishable result.

- [ ] **Rule-based simulator (upper-bound oracle).** Port the uGrid `GenControl()`
  faithfully: battery temperature effects and self-discharge, quadratic generator fuel
  characteristic, and the night-reserve look-ahead. *Done when* it reproduces the reference
  controller's dispatch on a shared 8760 within tolerance, and its trajectory is verified
  to satisfy `F(x)` (Assumption 1).
- [ ] **Cost-optimal dispatch (lower-bound oracle).** The representative-day MILP in
  linopy, capacities as box-bounded variables, in two modes: LP relaxation (fast, valid
  bound) and MILP (tight bound). *Done when* LP ≤ MILP ≤ rule at every sample point.
- [ ] **Net-present-cost accounting.** Capital recovery, replacement, salvage, NPC and
  LCOE in `post/kpis.py`, feeding annualised cost into both oracles.
  *Done when* one sizing reproduces the reference benchmark
  (PV 8.2 kW, batt 17.2 kWh, gen 5.85 kW, LCOE 0.3211).

---

## L3 — Certified sizing on real data (P0)

- [ ] **Representative days.** Weighted `k`-medoids implemented in-repo; derive `W`, `F^e`
  and `R` per the formulation. *Done when* representative-day costs match the full 8760
  within ~5 %.
- [ ] **Generalise the lattice** to (PV panels, battery modules, generator size, inverter
  size); branch on every integer and catalogue dimension. *Done when* branch-and-simulate
  certifies the optimum on a ≥ 3-D lattice and matches enumeration on a coarse grid.
- [ ] **First real certified result.** Report `z_B*`, `z_A*`, `Δ_heur` (absolute and
  relative), certified gap, runtime and oracle-call count against enumeration, for
  Samionta and then Gbowele. *Done when* a results table and figure are written under
  `results/` and `tests/test_benchmark.py` passes.

**Risk:** Assumption 1. Verify the ported `GenControl` never leaves `F(x)` (no simultaneous
charge and discharge, minimum loading and state-of-charge trips respected). If it can,
document the correction or restrict `F(x)` accordingly.

---

## L4 — Stochastic multi-scenario / tree extension (P1)

Goal: expected `Δ_heur` across a reduced scenario tree — the full result.

- [ ] **Scenario generation** — `scenarios/{demand_paths,pv_paths,cost_paths,mc_sampler,
  assemble}.py`: demand trajectories from L1 with connection growth, SSP yield profiles
  from the downscaling framework, fuel and capital-cost trajectories, policy draws.
  *Done when* `sample_scenario_paths(cfg)` returns resolved `ScenarioPath`s with 8760 arrays.
- [ ] **Scenario reduction + tree** — `tree/{reduce,build_tree}.py` (per-stage medoid
  reduction → branching tree, path probabilities, reduction error reported).
  *Done when* `build_tree` returns a `ScenarioTree` with `check_probabilities()` passing.
- [ ] **Deterministic-equivalent MILP** — fill `model/{coords,variables,
  investment_constraints,dispatch_constraints,economics,build}.py`. The relaxed solve is
  the tree-wide lower bound. *Done when* `build_model` solves and reproduces the
  single-node case of L2.
- [ ] **Branch-and-simulate over the tree** — outer branch over the per-node capacity plan;
  lower bound from the tree relaxation on the capacity box, upper bound from rule
  simulation per (node, scenario, representative day). Wire through `run.py`.
  *Done when* `python -m microgrid_expansion.run` returns expected NPC/LCOE and expected
  `Δ_heur` with a certificate.

---

## L5 — Theory hardening & the open question (P1, ongoing)

- [ ] **Prove Assumption 1 for the uGrid controller** rigorously (feasibility within
  `F(x)`); enumerate and dispatch edge cases. *Done when* a lemma and proof are in model.tex.
- [ ] **Tighten / accelerate the bound.** Monotonicity-based pruning (operating cost
  decreasing in capacity, capital cost increasing), size-specific big-M, and an LP-vs-MILP
  trade-off study. *Done when* node counts drop measurably and the effect is tabulated.
- [ ] **Multi-stage SDDiP angle (open research).** Test the conjecture that a fixed
  (non-optimising) rule-based recourse removes the integer recourse that obstructs
  SDDP/SDDiP, making exact multi-stage decomposition possible. Start with a proof sketch
  and a targeted literature check. *Done when* either a proof or counterexample exists, or
  it is scoped out with justification.
- [ ] **Complexity / convergence note** for branch-and-simulate (finite lattice ⇒ finite
  termination; gap behaviour vs bound tightness). *Done when* stated in model.tex.

---

## Dissemination (P2)

- [ ] **Paper / chapter outline** centred on the method and the price-of-heuristic result,
  positioned against HOMER/iHOGA (no certificate) and the MILP camp (cost-optimal only).
- [ ] **Reproducibility**: CI running `pytest`; pinned solver versions; every stochastic
  step seeded. *Done when* a fresh clone reproduces the headline numbers.

---

## Open questions / watch-list

- Does the lower-bound inequality hold under *all* the diesel minimum-load, reserve and
  unit-commitment rules, or can the rule sometimes leave `F(x)`? (Assumption 1 — L5.)
- Multi-stage adaptivity with a *fixed* policy: open-loop plan versus a parameterised
  decision rule for the upper-bound simulation (the bound and certificate are unaffected).
- The rule-based-sizing space is active (Nespoli & Medici, Nov 2025) — re-scan before
  submission to confirm novelty still holds.
- Tightness of `Δ_heur`: a small gap justifies the heuristic's simplicity; a large gap is
  itself the headline result. Either way it is reportable.
