# Sensitivities of session 4 bis

Each directory holds the runs of one sensitivity of
`docs/design/progressive_connection_and_persistence.md` (sections 12 and 14), computed under
the shipped defaults with one reading changed. Nothing in `src/`, `data/` or `sites.py` was
edited to produce them: the reading changed is given to the command, as an option or as a
project file, or, for the census of Gbowele, in memory by the short script below. The files
keep the names the commands give them, so a sensitivity is told from the base case by its
directory, and each certificate records the reading in its `connection` block
(`high_plateau`, `census`, `productive_intensity_scale`).

| Directory | Reading changed | Section 14 | Runs |
|---|---|---|---|
| `node_year_first/` | a node carries the first year of its span, not the last | point 18 | Samionta's tree |
| `high_plateau_census/` | the high trajectory's plateau is Gbowele's census, 159, not its profile lower bound, 124 | decision 1, point 20 | the bench certificate and Samionta's tree |
| `gbowele_census_171/` | Gbowele's census is the operator's field census, 171 households (HH1 144, HH2 16, HH3 11), and its connection curves are refitted at it | point 10 | Gbowele's greenfield and brownfield certificates |
| `productive_intensity_44_over_60.8/` | the productive-use intensity of the rule times 44/60.8, Gbowele's productive users metered at `T` over those the rule expects | point 14 | the bench certificate |
| `productive_intensity_16_over_11.4/` | the same intensity times 16/11.4, Samionta's ratio | point 14 | the bench certificate |

## How each was run

The project files hold only what they change; everything they omit stays at its default.

```
# node_year_first
python -m microgrid_expansion.run --site Samionta --node-year first --out results/sensitivities/node_year_first

# high_plateau_census, with high_plateau_census.yaml holding
#   connection:
#     high_plateau: census
python -m microgrid_expansion.exact.certify --site Samionta --project high_plateau_census.yaml --out results/sensitivities/high_plateau_census
python -m microgrid_expansion.run --site Samionta --project high_plateau_census.yaml --out results/sensitivities/high_plateau_census

# productive_intensity_*, with a project file holding one line,
#   productive_intensity_scale: 0.7236842105263158      (44/60.8)
#   productive_intensity_scale: 1.4035087719298245      (16/11.4)
python -m microgrid_expansion.exact.certify --site Samionta --project <file> --out results/sensitivities/<directory>
```

The census of Gbowele lives in `sites.py` and its connection curves in
`data/ramp_params/reference/connection_curves.csv`, and no option reaches either. The
sensitivity changes both in memory and then runs the shipped command; the demand cache keys
carry the census and the connection schedule, so nothing computed at 159 households is
served or overwritten:

```python
import dataclasses, sys
from microgrid_expansion import sites
from microgrid_expansion.demand import build_connection_curves as bcc, connection
from microgrid_expansion.exact import certify

sites.TEMPLATES["Gbowele"] = dataclasses.replace(
    sites.TEMPLATES["Gbowele"], census={"HH1": 144, "HH2": 16, "HH3": 11})
curves = bcc.build()[0].round(6)          # fit_site reads the template's census
connection._curves_table = lambda: curves
certify.main(["--site", "Gbowele", "--out", "results/sensitivities/gbowele_census_171",
              *sys.argv[1:]])             # nothing, then --brownfield
```

Refitted at 171 households, Gbowele's plateau is still not identified: its interval at 95 %
runs from 128 to 171 households (124 to 159 at the census of `sites.py`), the lower bound at
a rate of 0.1303 a month and a midpoint at 20.7 months of village age, the census at 0.1118
and 25.5 months.
