# microgrid-expansion (Development in Progress...)

A multi-stage stochastic capacity-expansion model for sizing off-grid microgrids
(PV array + diesel generator + battery + hybrid inverter + community load)
under uncertainty.

The model is an adaptive multi-stage stochastic program formulated on a scenario tree and
solved as a single deterministic-equivalent MILP with
[linopy](https://linopy.readthedocs.io/); the faster of Gurobi and HiGHS is detected at
startup.

It takes its name and its interface conventions from
[MicroGridsPy](https://github.com/SESAM-Polimi/MicroGridsPy-SESAM), the micro-grid sizing
model developed at Politecnico di Milano, and extends it: where that model sizes a plant,
this one certifies the sizing against the controller that will run it, and plans the
expansion of that plant across a scenario tree.

What distinguishes it is that the plant is sized against the controller it will actually
run under. The rule-based controller is **simulated**, not encoded: an earlier attempt to
write it as MILP constraints was withdrawn, the rule's own trajectory sitting below the
night-reserve floor in four to sixty per cent of hours, so the constraint excluded the
behaviour it claimed to describe. Simulating it gives an upper bound, the cost-optimal
relaxation gives a lower one, and the search certifies the optimum between them: every
sizing of the admissible set is either evaluated or excluded by a proven bound.

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
  resource/                  Meteorological series, climate pathways, grid availability.
  ui/                        Local server and the page it serves (the graphical interface).
  run.py                     End-to-end orchestrator.
tests/                       Assembly, dispatch-fidelity and benchmark checks.
```

## Installing

The same four commands on every platform. They need [Miniconda or
Anaconda](https://docs.conda.io/projects/miniconda/) and, on Windows, the *Anaconda
Prompt* rather than the ordinary command prompt.

```bash
git clone git@github.com:ssossou-liege/MicroGridsPy-Expansion.git
cd MicroGridsPy-Expansion
conda env create -f environment.yml
conda activate mgpy_dev
```

That installs the model, the interface and the open-source solver. Two things are optional:

- **Gurobi** solves the tree programme in about half the time of HiGHS. It is installed
  already; it only needs a licence, free for academic use, from
  [gurobi.com](https://www.gurobi.com/academia/). Without one the tool falls back to HiGHS
  on its own and says so.
- **Climate Data Store credentials** are needed only to fetch the meteorological series of
  a site you describe yourself. Register at
  [cds.climate.copernicus.eu](https://cds.climate.copernicus.eu/) and put the key in
  `~/.cdsapirc` (`%USERPROFILE%\.cdsapirc` on Windows). The two bundled example villages
  already carry their series.

## Running the interface

```bash
microgrid-ui
```

The interface opens in a window of its own, not in a browser tab: **Windows** and **macOS**
use the web view they ship, and on **Linux** the Qt bindings come from the environment above,
so nothing needs installing by hand. If a window cannot be made the tool says why and opens
your browser instead — the same interface either way. You can also ask for that outright, or
for the server alone:

```bash
microgrid-ui --browser     # open in the default browser
microgrid-ui --serve       # server only, no window (for a remote session)
```

Nothing leaves the machine: the server listens on the loopback address, and the only
network the tool ever uses is the map's background tiles and the one-off download of a
site's meteorological series.

### First run

The interface opens on **Community**. Two example villages are already there, the ones the
behavioural archetypes were calibrated on; pick one and press **Size the plant**. Expect a
few minutes the first time and about half a minute afterwards: a community's demand is
simulated appliance by appliance and then cached, and a fresh clone has nothing cached yet.
The cache is keyed on the calibration tables, on the code that reads them and on the
appliance library, so it rebuilds when any of those change and never serves the demand of a
model that no longer exists.

To size your own community, choose *New community*, place the point on the map, state how
many households and how many productive uses you expect, then fetch the meteorological
series for that point.

The interface is in English. The picker in the top right switches it to French, and the
choice is remembered — including in the printable report and in the CSV exports, whose
headers follow the language you were reading.

## Running from the command line

```bash
python -m microgrid_expansion.exact.certify --site Gbowele    # certified sizing, one year
python -m microgrid_expansion.run --site Samionta             # multi-stage expansion plan
```

## Modelling choices

- **Structure:** adaptive multi-stage stochastic program on a scenario tree
  (two-stage is the special case of a single investment node at year 0).
- **Objective:** risk-neutral — minimise probability-weighted expected discounted
  total cost; report LCOE.
- **Dispatch:** the deployed rule-based controller, simulated rather than encoded, and
  compared against a cost-optimal relaxation. The gap between the two is reported as the
  price of the heuristic — what the plant costs because its controller is causal rather
  than clairvoyant, which the reference sizings put at four to nine per cent, paid almost
  entirely in storage.
- **Coupling:** the array divides between the battery bus and the load bus, each part
  limited by its own converter; the two pure arrangements are the corners of that split.
- **National grid:** optional, intermittent, and its arrival over the horizon can be
  treated as an uncertainty rather than a date.
- **Design variables:** integer increments of capacity (PV panels, battery modules)
  plus discrete generator/inverter catalogs, decided per tree node with
  structural non-anticipativity.

See [docs/formulation/model.tex](docs/formulation/model.tex) for the full mathematical
formulation.
