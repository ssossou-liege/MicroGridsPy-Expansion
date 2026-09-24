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

That installs the model, the interface, the open-source solver and numba, which compiles the
two hour-by-hour dispatch kernels. Numba is not an optimisation to bolt on later: a simulated
year costs about a millisecond compiled and about fifty interpreted, and a certification
spends nearly all its time there, so it is the difference between half a minute and half an
hour. If it is ever missing, too old, or shadowed by another file on the path, the tool warns
once and carries on with the interpreted kernels, which give the same numbers to the last
digit.

Two things are optional:

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
mgpy-ui
```

The interface opens in a window of its own, not in a browser tab: **Windows** and **macOS**
use the web view they ship, and on **Linux** the Qt bindings come from the environment above,
so nothing needs installing by hand. If a window cannot be made the tool says why and opens
your browser instead — the same interface either way. You can also ask for that outright, or
for the server alone:

```bash
mgpy-ui --browser     # open in the default browser
mgpy-ui --serve       # server only, no window (for a remote session)
```

Nothing leaves the machine: the server listens on the loopback address, and the only
network the tool ever uses is the map's background tiles and the one-off download of a
site's meteorological series.

### First run

The interface opens on a homepage offering three ways in: **Create a new project**, **Open a
project**, and **Try it on a real village** — Samionta or Gbowele, the two surveyed
communities the behavioural archetypes were calibrated on, whose households, enterprises and
meteorological series ship with the tool.

A study then runs as four pages, and the button at the bottom right moves between them.

1. **A new project** — name the study, name the community, place it on the map, and state
   the households by type and the productive activities by class, as the field survey
   recorded them. The time zone is taken from the longitude rather than asked for.
2. **Uses and archetypes** — the consumption behaviours the demand is built on, with their
   provenance, editable where local knowledge contradicts them.
3. **Assumptions** — prices, service lives, the grid and the cost of everything beyond the
   plant. Every value carries the source of its default.
4. **The decision** — what to build this year.

There is one action and one answer. The tool exists to settle a single question — what a
community should buy now, before knowing which way its demand will go — so the scenario tree
and the certified reference year are two halves of that one answer rather than two studies
to arbitrate between. The tree returns the year-0 plant; the reference year, certified by
exhaustion, is where the tariff, the return and the hour-by-hour dispatch are computed. The
page says plainly which of the two is proven optimal: the reference year is, and the year-0
decision over the whole tree is the root of a coordinated descent on which no bound has yet
been closed.

Expect ten minutes or so on a fresh clone and a few minutes afterwards: a community's demand
is simulated appliance by appliance and then cached. The cache is keyed on the calibration
tables, on the code that reads them and on the appliance library, so it rebuilds when any of
those change and never serves the demand of a model that no longer exists.

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

## Licence

Apache License 2.0 — see [LICENSE](LICENSE). You may use, modify and redistribute this
work, including commercially, provided the licence and the copyright notice travel with
it and you state what you changed.

[NOTICE](NOTICE) records what this project owes to others: the name and logo it takes
from MicroGridsPy, the uGrid/uGridNet policy the rule-based controller follows, the
vendored copy of Leaflet, and the provenance of the meteorological and climate data. No
MicroGridsPy source code is included here; the two projects share no code beyond the
boilerplate every Python file carries.
