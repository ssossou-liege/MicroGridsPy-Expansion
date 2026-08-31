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
- [x] **Demand generator** (`demand/generator.py`). One RAMP user per household so the
  fractional calibrated appliance counts are honoured in expectation, minute-resolution
  simulation aggregated to hourly kW, twelve months concatenated into a year. Runs in ~75 s.
- [x] **Transferability to sites without meter data** (`demand/maturity.py`,
  `demand/growth.py`). The first calibration conditioned the mixture on *site* and calendar
  month, which does not transfer: predicting either reference village from the other gives
  **50 %** and **130 %** error on daily energy. Conditioning on **months since connection**
  instead resolves why — the two villages agree to **5 %** at connection and diverge
  afterwards, one growing **×2.31** over two years and the other **×1.12**. The mixture is
  now `P(C | T, maturity)` pooled across sites with equal site weight, so a locality with a
  census and no meter record can be simulated, which is the situation of every site the
  model is meant to size.
- [x] **One authoritative partition** (`demand/partition.py`). Two segmentations coexisted
  — k-means (which discovered the archetypes) and nearest-reference-profile (which the RAMP
  appliance parameters are calibrated against). They agree exactly on inactive and atypical
  observations but on only **57 % of archetype labels**. Comparing appliance sets with the
  k-means statistics manufactured an apparent calibration gap that does not exist: on the
  operative partition the appliance sets reproduce their own archetypes to **1.00 and 1.01**
  for the two largest. Everything downstream now resolves the partition through one module.
- [x] **Archetype moment-matching** (`demand/calibration.py`). Two factors per archetype —
  a power scale and a duration scale — fitted against the operative partition's measured
  energy and peak. Residuals: **C0 +5.5 %/−3.6 %, C1 −3.4 %/+2.6 %, C2 +1.2 %/−0.5 %**.
  C3 is left uncorrected: it holds 4 observations out of 1 818, too few to fit against.
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
- [ ] **Give archetype C3 empirical support.** It carries calibrated appliance parameters
  but only 4 of the 1 818 measured household-months fall into it, so nothing validates it
  and nothing corrects it. Either it is an archetype these two villages do not exhibit, and
  should be dropped or re-derived, or the reference profile that defines it is misplaced.

---

### Growth uncertainty — an explicit axis, not a point estimate

With two reference villages one cannot estimate how a third will grow: there is one that
grows and one that does not. Rather than average them into a trajectory describing neither,
the two behaviours are carried as an envelope — `slow` (Samionta), `fast` (Gbowele) and a
site-balanced `central` — each being a mixture law measured at a real site, so nothing is
extrapolated. **A sizing must be computed at both bounds**, and the width of the resulting
bracket is an honest statement of what two calibration sites can support.

- [ ] **Widen the calibration base.** The growth envelope rests on two villages. A third
  and fourth reference site would let the between-site variance be estimated rather than
  merely bracketed, and would give household categories HH2 and HH3 — 13 households at one
  site today — some support of their own.
- [ ] **Carry the trajectory into the scenario tree.** The growth envelope is the natural
  demand axis of the L4 tree; the branches are already measured.

---

## L2 — Real oracles and real economics on one site (P0, largely done 2026-08-19)

Goal: replace the toy instance with the real ones, on L1's data, single scenario. This is
the minimum publishable result.

- [x] **Rule-based simulator, the upper-bound oracle** (`exact/simulator.py`). The
  generation-balance decision rule ported faithfully — priority order, night-reserve
  look-ahead, temperature-dependent capacity and self-discharge, quadratic part-load
  efficiency — but applied under the model's own physics. The reference implementation
  updates storage without round-trip losses, has no minimum stable loading and lets an
  uncoverable deficit vanish; all three would put the trajectory outside `F(x)` and void
  the bound. Fuel reproduces the manufacturer's curve to **0.4 %** at 50, 75 and 100 % load.
- [x] **Cost-optimal dispatch, the lower-bound oracle** (`exact/lower_bound.py`). Capacities
  box-bounded, commitment relaxed or integral, in linopy. The linear fuel curve is fitted
  as a **minorant** of the true consumption rather than through it — the tangent parallel to
  the chord, touching at 75 % load, valid everywhere with a 2.2 % mean gap. A least-squares
  fit would overestimate consumption at some outputs and could prune the optimal design.
- [x] **Life-cycle accounting** (`post/economics.py`). Capital, maintenance, replacement of
  each asset whose life expires within the horizon, and straight-line salvage of the last
  vintage. At the published reference sizing under plausible operation the levelised cost
  lands within **2.4 %** of the published 0.3211 $/kWh.
- [x] **Proposition 1 verified on real data** (`exact/verify_bound.py`): relaxation ≤
  mixed-integer ≤ rule at every sampled design, with Assumption 1 holding throughout.
  Gap between rule and optimum: **0 to 6.3 %**.

### Two findings that change the formulation

- **The cyclic closure is incompatible with a causal controller.** The formulation closes
  each representative day on its state of charge. A controller does not: it ends where its
  decisions leave it, generally poorer. Imposing the closure on the *bound* constrains it
  where the controller is unconstrained, and the bound then exceeds the quantity it bounds —
  observed here, worth up to 15 % of the operating cost over a week. The lower bound
  therefore leaves the terminal state free by default; `model.tex` needs a note.
- **The battery temperature model must be defined once.** The resource layer and the
  controller carried different curves for the same usable-capacity ceiling, which put the
  simulated trajectory outside the set the bound was computed over — Assumption 1 failed on
  1.55 % of hours. Both now delegate to `battery.py`.

- [x] **Battery chemistry is selected, not inherited** (`battery.py`). Unifying the two
  conflicting capacity curves, the *ported* one was kept — IEEE 485, which describes a
  lead-acid pack — although the configuration specifies a lithium-iron-phosphate pack. That
  privileged the provenance of a curve over its applicability. The chemistry is now an
  explicit setting validated against the pack: **LFP is the default**, flat across the
  temperate band and derating at both ends; lead-acid is retained because reproducing the
  reference controller requires it. Both the resource layer and the controller resolve the
  same curve for the same chemistry, and the instance cache distinguishes them.
- [ ] **Full-year mixed-integer solve.** 8 760 commitment binaries is impractical
  (minutes to hours); the ordering was verified over ten-day windows. Representative days
  (L3) are what make the tight bound tractable over a year.

---

## L3 — Certified sizing on real data (P0, complete 2026-08-25)

- [x] **Representative days** (`timedomain/rep_days.py`, `timedomain/kmedoids.py`).
  Weighted k-medoids implemented in-repo — the only maintained package offering it is
  binary-incompatible with current NumPy, and eighty lines of well-understood algorithm is
  not worth a dependency. Medoids are *real days*, so the compressed year keeps genuine
  peaks rather than a flattened average. At twelve days on Samionta: annual energy
  **−0.02 %**, resource **+0.50 %**, peak **−3.7 %**. The peak compresses worst, as a
  handful of days cannot hold every extreme of a year.
- [x] **Generalised lattice and branch-and-simulate** (`exact/certify.py`). Four dimensions
  — photovoltaic modules, battery modules, inverter modules and the generator catalogue —
  plus the coupling architecture, certified separately. Sized around the instance:
  **110 208 buildable designs** for Samionta under direct-current coupling, 144 525 under
  alternating.
- [x] **Coupling architecture, and the designs it rules out** (`settings.CouplingSpec`,
  `exact/simulator.py`, `exact/lower_bound.py`). The array does not reach the load for
  free: under direct-current coupling everything it sends the load crosses the hybrid
  inverter, under alternating coupling everything entering storage does. Neither was
  modelled, and the conversion equipment was not costed at all, so the search was free to
  wire a 29 kW array to a 12.5 kW inverter. The array is now bounded by what its converter
  admits — 1.3 × the inverter under direct coupling, parity under alternating — which
  **removes 47 % of the Cartesian lattice as plants that cannot be wired**. No charge
  controller is sized outside the hybrid inverter: two regulators on one lithium bank must
  answer to the same battery-management conversation, which confines that arrangement to a
  single manufacturer's ecosystem. The lower bound was rewritten in explicit flows, the
  aggregated balance being unable to say which flows cross the inverter.
- [x] **Assets recovered over their own lives.** Every asset had been annualised at the
  project's 25-year factor, making a 10-year inverter look two fifths cheaper than it is —
  precisely the bias that produces oversized converters. Each is now recovered over its own
  service life.
- [x] **Certified results on real data** — six certificates: both sites on the central
  growth trajectory, Samionta at both bounds of its growth envelope and at both bounds of the
  value-of-lost-load range, each racing the two coupling architectures. Optimality proven by
  exhaustion: on Samionta central, all **110 208 buildable designs** accounted for, 58.7 %
  discarded without simulation, two relaxations, 49 min. Direct-current coupling wins all
  six, by 438–814 $/yr. Certified plant at Samionta: **22.5 kW · 60 kWh · 17.5 kW · 8 kW**;
  at Gbowele **16.0 kW · 45 kWh · 12.5 kW · 8 kW**. Unserved energy nil throughout. Levelised
  cost 169–185 FCFA/kWh against a 160 target, closed by a 5–14 % capital subsidy.
- [x] **The price of the heuristic, measured**: 7.2–10.4 % of annualised cost (558–679 $/yr).

### What the certificates establish

**The deficit of anticipation is paid in storage, not in generation.** Across all six cases
the rule-based optimum carries **9 % to 29 % more storage** than the cost-optimal one, never
less, while the array is the same to within two or three per cent with no systematic
direction and the inverter is equal or smaller. A controller with no view of the coming hours
must hold a reserve to reach the next solar surplus, and that reserve immobilises capacity a
foresighted dispatch never had to buy; generation is set by the annual energy balance, which
foresight does not change. This corrects the conjecture drawn from the toy case — a uniformly
more generous plant — and sharpens what it implies: existing exact methods do not undersize
the installation, they undersize its **storage**, by ten to thirty per cent on these cases.

**The value of lost load does not bind.** Varying it six-fold, from 0.50 to 3.00 $/kWh,
leaves the certificate bit-for-bit unchanged: the optimal plant serves the whole demand, so
the parameter never enters the cost. At current equipment prices it is cheaper to serve every
kilowatt-hour than to shed any, which spares the study from having to establish a notoriously
unmeasurable parameter — so long as costs stay in the observed range.


### Three findings that reshape the algorithm

- **The gap cannot close, and closing it was never the criterion.** As boxes shrink, a
  singleton's bound is exactly the cost-optimal value at that design, so the smallest bound
  tends to `z_A*` while the incumbent tends to `z_B*`: their difference tends to
  `Δ_heur > 0`. Optimality is therefore proven by **exhaustion** — every design either
  discarded by a bound or evaluated by a simulation — not by a vanishing gap. The first
  implementation terminated on the gap and would have run essentially for ever.
- **The oracle cost ratio is the reverse of the toy's, and it dictates the design.**
  Simulating the controller over a year takes **52 ms**; the relaxation takes **3.0 s**,
  sixty times more. A relaxation is therefore worth its price only for a box holding more
  than about sixty designs; below that, enumerating with the cheap oracle is both faster and
  exact. The search accordingly buys a strong incumbent with a multi-resolution sweep of
  simulations — 1 956 of them reach 10 470 $/an on the full lattice in 84 s, against 163 min
  to enumerate it — and spends relaxations only on discarding whole regions.
- **Half the lattice was never a plant.** Enumerating capacities independently of one
  another produced designs no installer could wire, and a certificate over such a set proves
  optimality against phantoms. Coverage is therefore counted over buildable designs only:
  a box's unwirable corners are not candidates the certificate has to account for, and
  counting them among the discarded would claim a lattice larger than the one that exists.
  A box holding no buildable design has an infinite bound, which is how the search discards
  it rather than aborting on an infeasible programme.

---

## L3b — Productive uses in the demand model (P0, complete 2026-08-25)

The demand model is calibrated and scaled on households alone. Over the last twelve months of
meter data, productive-use enterprises account for **75.6 % of measured energy at Samionta**
and 49.1 % at Gbowele — fourteen enterprises at Samionta consuming nearly four times what
forty-nine households consume. The model therefore omits half the energy at one site and four
fifths at the other, and omits precisely its **daytime** part: households draw 23 % of their
energy between 07:00 and 18:00 at Samionta, productive users 67 %. Aggregated, Samionta's
demand is majority-daytime (59 %) with its peak at 19:00, not the nocturnal profile the model
produces.

The L3 certificates are sound computations of the demand they were given, but that demand no
longer describes these villages. At risk in particular: the coupling verdict — direct-current
coupling wins here because nearly all energy transits storage, and a daytime load is exactly
where alternating coupling pays — and the storage finding, a daytime load mobilising less
night reserve.

- [x] **Productive-use archetypes** (`demand/productive.py`,
  `demand/build_productive_profiles.py`). Six activity classes from the survey, their
  magnitude and shape from the meters — the survey's own nameplate powers are entered as
  zero for forty-two per cent of the equipment it records, so a bottom-up appliance model
  would rest on the one field the survey does not support. The classes differ in kind:
  milling is 82 % diurnal, incubation 45 %, and a single average enterprise would erase the
  daytime load that decides the coupling.
- [x] **Enterprises as a connection trajectory, not a count.** Nobody knows in advance who
  will start a business, so their number is drawn (Poisson) from an intensity conditioned on
  the age of the connection and bracketed by the two reference sites. Intensity is referred
  to *connected* households rather than to the census: an enterprise appears beside existing
  supply, and a ratio taken over dwellings not yet connected would not transfer. The mix of
  classes belongs to the trajectory too — one village has few large enterprises, the other
  many small ones, and a pooled mix reproduced neither, overstating the second twofold.
  Simulated counts land on the observed ones: **14 against 14** at Samionta, 45 against 43
  at Gbowele.
- [x] **The household model's shape, and the defect that hid it** (`demand/generator.py`,
  `demand/build_archetype_shapes.py`). The calibration records a security lamp starting at
  18:48 and burning **720 minutes**, dusk to dawn, and leaves its end unrecorded because
  that end is dawn. The code read the absence as *midnight*: the window collapsed to 313
  minutes and the twelve-hour duty with it, so simulated households drew **nothing at all**
  between midnight and sunrise — the steadiest load the meters record, and the one a battery
  carries through the night. Wrapping windows are now expressed as RAMP's two windows, which
  it only honours when told at appliance creation how many to expect. Daytime share falls
  from 47 % to **21 %** against 23 % measured. The moment-matching factors, fitted to
  compensate the truncation, were refitted; archetypes 0, 1 and 2 land within 4 % of
  measured energy and peak.
- [x] **Measured hourly shapes per archetype** — they did not exist. The calibration targeted
  daily energy and peak power, two scalars, and so had never confronted the appliance
  parameters with the shape they produce. That is how the defect survived.
- [x] **Re-certified** on the corrected demand. Six certificates, all proven by exhaustion,
  all fully covered, Proposition 1 satisfied throughout, every design buildable. Direct-current
  coupling wins all six by 969–2 210 $/yr. **41 min per case on average, 247 min in all**,
  against seventeen hours per case before the search was corrected.

| Case | PV | Storage | Inverter | Genset | z_B* | Δ_heur | LCOE | Subsidy |
|---|---|---|---|---|---|---|---|---|
| Gbowele central | 35.5 kW | 95 kWh | 27.5 kW | 8 kW | 11 949 | 660 (5.8 %) | 166 | 3.9 % |
| Samionta slow | 32.5 kW | 95 kWh | 25.0 kW | 8 kW | 11 018 | 620 (6.0 %) | 183 | 12.6 % |
| Samionta central | 52.0 kW | 135 kWh | 40.0 kW | 8 kW | 16 247 | 734 (4.7 %) | 161 | 0.9 % |
| Samionta fast | 71.5 kW | 175 kWh | 55.0 kW | 8 kW | 21 100 | 852 (4.2 %) | 156 | none |

**The deficit of anticipation is paid in storage, and in storage alone.** The rule-based
optimum carries **9–12 % more storage** than the cost-optimal one; the array is identical to
the kilowatt in all six cases, as are the inverter and the genset. Existing exact methods
therefore do not undersize the installation — they undersize its **storage**, by about a tenth.

Caveat to carry: Δ_heur is measured at the nominal reserve multiplier, which is not optimal —
halving it saves some 5 % on a trial design. Part of the 4.2–6.0 % is therefore *tuning*,
recoverable by a parameter sent to the controller remotely, not irreducible myopia. Decomposing
it into three terms — nominal setting, best setting, residual against perfect foresight — is
the next useful step and is directly operational.

### What made these certificates computable

- [x] **Narrowing the lattice by bound, not by judgement.** A generous lattice is the price of
  not excluding the optimum by assumption, and on a doubled demand it offered a million
  designs. Trimming by eye would be a pre-sizing heuristic, and a heuristic that excludes the
  optimum turns a certificate into an assertion. The relaxation over `{d ≥ k}` is
  non-decreasing in `k`, so the smallest excluded `k` is found by **bisection in eight
  relaxations**. Removes **99 % of the lattice in under four minutes**.
- [x] **Branch-and-simulate over enumeration.** Enumeration was chosen when the lattice held
  200 000 points and a relaxation cost sixty simulations. At a million the arithmetic reverses.
- [x] **The integer search given to the solver.** z_A* is an integer programme and was being
  handled by relax-round-pin — a hand-written branch-and-bound without guarantees. Declared
  integer with the genset catalogue as a binary selection, Gurobi solves it in **ten seconds**
  and returns a design **118 $/yr better**. That rounding error exceeded Δ_heur itself and
  reversed its sign, producing a negative price of the heuristic that Proposition 1 forbids.
- [x] **The buildability guard reduced to one place.** A certified design violated the
  array-to-converter ceiling — 60 kW of array behind a 22 kW inverter — because the guard sat
  at three call sites and was missing at the fourth, the centre of a box. Under direct-current
  coupling that ceiling is the only thing standing between the search and free photovoltaic
  capacity. Sixth instance in this project of one quantity defined in several places.

Residuals, stated rather than hidden: compared per connected unit, households come out +35 %
at Samionta and +70 % at Gbowele, enterprises −45 % and +92 %. The sign reverses between
sites, which is the expected behaviour of a transferable model whose envelope brackets rather
than reproduces — but the bracket is wide, and archetype 3 is still unfitted for want of
observations.

---

## L4 — Stochastic multi-scenario / tree extension (P0, complete 2026-08-26)

Goal: expected `Δ_heur` across a reduced scenario tree — the full result.

- [x] **Climate series in one document per site** (`resource/cmip6.py`,
  `data/irradiance/download.py`). Acquired from
  **NASA's downscaled CMIP6 archive** rather than from the raw model output: it is already
  bias-corrected to a quarter degree — the step this study could not otherwise validate —
  and its subset service returns one grid point openly, so a site needs kilobytes where the
  raw archive needs hundreds of megabytes a year *and* a licence agreement the Copernicus
  route refused. Three pathways × three models × five milestone years × two sites, produced.
  Watch the grid label: it is a property of the model (`gr1`, `gr`, `gn`) and a wrong one
  returns a 404 indistinguishable from a model that does not publish the pathway. The
  fifteen series of a site are merged into one document indexed by pathway and year rather
  than left as fifteen files with those keys encoded in their names, where nothing can read
  them without parsing a string.
- [x] **Cost trajectories** (`settings.CostTrajectory`), sourced and declared. Photovoltaic
  from experience curves (26 % per doubling 1976–2025, falling towards 17 % by 2050;
  balance-of-system learning far more slowly than modules) corrected for African mini-grid
  capital having fallen a fifth over 2020–2024 from twice the global level. Storage from a
  national laboratory's three cases (−17 %, −30 %, −52 % over 2022–2035, flattening after).
  Fuel does not learn: near-term outlooks are dominated by shocks and long-run scenarios
  disagree in sign, so its band is centred on a flat real price and is marked **unverified**,
  which is why it is an uncertainty axis rather than a parameter.
- [x] **Scenario generation** — `scenarios/`. Growth trajectory and cost future are drawn
  once per path and held; pathway and policy are redrawn per stage. Demand realisations come
  from cached pools: given trajectory and maturity the generator's draws are exchangeable, so
  a pool of four sampled with replacement represents the conditional distribution as
  faithfully as a fresh run per path, at a hundredth of the cost — and a fresh run per path
  is not merely expensive but impossible.
- [x] **Scenario reduction + tree** — `tree/`. Medoid reduction on what a sizing is
  sensitive to (energy, peak, when it falls, resource, their correlation, prices), nested as
  a fan: with two reference sites there is no basis for saying a village that grew quickly to
  year five is likelier to grow quickly to year ten. Distortion reported per stage.
- [x] **Deterministic-equivalent programme** — `model/`. The lower oracle, generalised from
  one year to the tree, inheriting every L3 correction: coupling architecture arbitrated on
  the tree, array-to-converter ceiling at each node, assets recovered over their own lives,
  flows split by destination.
- [x] **Branch-and-simulate over the tree** — `exact/tree_oracle.py`, `exact/tree_certify.py`,
  `run.py`. The upper oracle simulates the controller node by node; a descent from the
  programme's plan finds the plan the controller itself prefers.

### Four modelling traps, all of which broke Proposition 1 before being found

- **The `rule_faithful` encoding.** The skeleton offered a variant adding the night-reserve
  floor to the cost objective and claiming to reproduce the field controller. It is deleted:
  the rule trajectory sits below that floor in 4–60 % of hours, and a programme minimising
  over a horizon is anticipative where the controller is causal.
- **A representative day runs sunrise to sunrise, not midnight to midnight.** The calendar
  day cuts the night in half and leaves the shorter half at the end: on the reference site
  the evening peak falls at 19:00, four hours before the array runs out, while the night it
  opens lasts thirteen. A controller whose whole function is to carry that night saw a third
  of it. Rolling the year to the hour the array starts producing **halves the error a
  compressed year makes on operating cost, from about 35 % to 14 %**, and it is what makes a
  cyclic condition meaningful — at sunrise the pack is at its daily low, so requiring it to
  return there says only that a representative day neither borrows from tomorrow nor lends to
  it. (Tested against the continuous recursion the programme uses, the cyclic and fixed
  openings turn out to give identical bounds: the recursion already runs across the year, so
  the condition is not binding.)
- **Representative days still cannot measure the price of the heuristic.** Aligned or not,
  each opens at a fixed state of charge, which is a free daily recharge; the residual 14 %
  does not shrink with more days. And the quantity measured *is* the unpredictability
  between days: simulated alone the price triples, repeated it collapses to a fifth. So
  compression is imposed on the programme, where it costs 0.6 % of the bound at 64 aligned
  days and buys a twelvefold speed-up; it is never imposed on the simulation, which runs the
  whole year at fifty milliseconds a node.
- **A day-by-day storage recursion hands out free recharges.** Splitting a node's year into
  independent days opened each at the same state of charge — 365 free recharges a year, worth
  about a sixth of annualised cost, putting the bound below anything achievable. The
  recursion runs continuously across the year, opening where the controller opens and ending
  free. Closing it would break the bound the other way, as L3 already measured.
- **Two oracles, two fuel curves.** The programme minorised with the largest unit's curve
  while the simulation used the installed unit's — a quarter of a litre per kilowatt-hour
  separates the ends of this catalogue. Both now use a minorant valid across it, and the
  same defect was found and fixed in L3, where the search had been evaluating every design
  with the largest generator's curve regardless of which it installed.

### Result

Samionta, three stages (years 0, 10, 20), seven nodes, whole years, both architectures raced:
direct-current coupling wins; here-and-now plant **45.5 kW · 135 kWh · 35 kW · 8 kW**,
expanding to 71.5 kW · 185 kWh in the 68 % branch and standing pat in the other. Expected
levelised cost **144 FCFA/kWh**, unserved energy nil at every node, price of the heuristic
**6.8 %** — an upper bound, the plan coming from a descent rather than an exhaustive
certification.

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
