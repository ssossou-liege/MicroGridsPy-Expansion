# data/ — provenance

Inputs in this directory are copied (not symlinked) so this repository stays
self-contained and reproducible. Each entry records what the data is, where it comes
from, and what produces it.

| Local path | Origin | Description | Status |
|---|---|---|---|
| `demand/household_customers.csv` | Operator customer roster | 141 sampled households: code, socio-economic type (HH1–HH3), site, connection date | ✅ |
| `demand/customer_info.parquet` | Operator customer database | Customer attributes for the two reference sites | ✅ |
| `demand/archive_customers.csv` | Written by `demand/build_connection_curves.py --census`, from the meter archive and the operator's field census of both villages, received on 7 November 2026 | The customers of the meter archive the roster does not list: code, site, type, household category, connection month (that of the first reading) and the source of the type (`census`, or `profile` where the census gives none). Read by the offline builds only: the connection curves, for the extended record the tables hold, and the meter archive, whose census codes it stands in for when the workbooks are not given; nothing the generation runs opens it. The census itself holds personal data and stays outside the repository; only its code and type columns are read | ✅ |
| `demand/gbo_meter_readings.parquet` | Built by `demand/build_meter_archive.py` from the operator's monthly exports, rebuilt on 7 November 2026 with each reading given to the code that held the meter when it was taken | Quarter-hourly per-customer power readings, Gbowele | ✅ |
| `demand/sam_meter_readings.parquet` | Built by `demand/build_meter_archive.py` from the operator's monthly exports, rebuilt on 7 November 2026 as above | Quarter-hourly per-customer power readings, Samionta | ✅ |
| `ramp_params/reference/*.csv` | Produced by `src/microgrid_expansion/demand/` | Monthly household features, behavioural cluster assignments, per-site monthly cluster summaries, global cluster profiles, and the hierarchical mixture probabilities | ✅ |
| `ramp_params/reference/cluster_params.csv` | RAMP calibration on the same meter data | Appliance parameters (power, count, functioning time, use windows, duty cycle) for each of the 4 behavioural clusters | ✅ |
| `irradiance/samionta_weather_hourly_2016_2025.csv` | ERA5-Land via the Copernicus Climate Data Store | Hourly irradiance, 2 m air temperature and 10 m wind, Samionta (7.0955 N, 2.2446 E), 2016–2025 | ✅ |
| `irradiance/gbowele_weather_hourly_2016_2025.csv` | ERA5-Land via the Copernicus Climate Data Store | Same quantities for Gbowele (7.62 N, 2.20 E) | ✅ |
| `irradiance/raw/` | Climate Data Store downloads | Cached NetCDF archives, so reprocessing never re-queues a request | ✅ (not committed) |
| `irradiance/download.py` | CLI over `microgrid_expansion.resource.{era5,cmip6}` | Acquisition of the historical series and of the SSP projections | ✅ |
| `irradiance/<site>_<pathway>_<year>_hourly.csv` | `download.py cmip6`, from NASA's downscaled CMIP6 archive | Hourly irradiance, temperature and wind under SSP1-2.6 / SSP2-4.5 / SSP3-7.0, at the milestone years of the scenario tree | ✅ |
| `ramp_params/reference/archetype_hourly_shapes.csv` | Measured, by `demand/build_archetype_shapes.py` | Mean 24-hour shape of each behavioural archetype, normalised. The calibration targeted daily energy and peak alone, so the shape had never been a target | ✅ |
| `ramp_params/reference/pue_class_profiles.csv` | Meter records of all 57 enterprises | Mean hourly load of one enterprise of each activity class, and its day-to-day spread | ✅ |
| `ramp_params/reference/pue_class_mix.csv` | Activity survey joined to the roster | Share of connections in each class, per growth trajectory | ✅ |
| `ramp_params/reference/pue_connection_intensity.csv` | Connection dates of both sites | Enterprises connected per *connected* household, by maturity band and trajectory | ✅ |
| `ramp_params/reference/own_levels.csv` | Meter records of the customers of the record, households, productive users and places of worship, joined to the activity survey and to the segmentation of the record's households | Each customer's type, the shape it draws (a household's archetype, a productive user's class, the class of a place of worship), connection month, mean daily energy over its last twelve months of readings (each reading over its own period), monthly factors where a year is covered, day-to-day spread and highest hourly power: what a village with a plant starts from | ✅ |
| `ramp_params/reference/archetype_scaling.csv` | Fitted by `microgrid_expansion.demand.calibration` | Power and duration factors reconciling the appliance calibration with the measured archetype statistics | ✅ |
| Economic and technical parameters | `src/microgrid_expansion/settings.py`, overridable per project | Discount rate, unit costs, generator catalogue, battery chemistry, tariff target | ✅ |

## Reproducibility

The meter archive both of them read is itself regenerated from the operator's monthly
exports, which live outside this repository and are therefore named on the command line,
with the operator's field census, of which only the code column is read:

```bash
python -m microgrid_expansion.demand.build_meter_archive \
    --exports <directory of monthly exports> --meters <the operator's register of meters> \
    --census Samionta=<workbook> --census Gbowele=<workbook>
```

A reading belongs to the code that held the meter when it was taken: a code readable once
its spaces are removed is that code, a test code is nobody's, and only an unreadable code
is recovered through the register's owner of the meter. A code the roster or the census
knows is a customer whatever the type of its meter; the register's types exclude the
others.

It reports, before writing, how much of the archive it replaces comes back unchanged, and
`--verify` writes nothing at all. The exports timestamp each reading with a UTC offset and
the archive carries site local time, an hour ahead; nothing in the files tells the two
apart, so that check is the only thing standing between a calibration and an hour's shift
in every load it is fitted to.

The calibration in `ramp_params/reference/` is regenerated from the archive by the
following chain, in this order: each step reads what the ones before it wrote.

```bash
python -m microgrid_expansion.demand.build_monthly_household_clusters
python -m microgrid_expansion.demand.partition
python -m microgrid_expansion.demand.build_archetype_shapes
python -m microgrid_expansion.demand.maturity
python -m microgrid_expansion.demand.build_mixture_probabilities
python -m microgrid_expansion.demand.build_productive_profiles --survey <activity survey>
python -m microgrid_expansion.demand.build_own_levels --survey <activity survey>
python -m microgrid_expansion.demand.build_community_profiles
python -m microgrid_expansion.demand.calibration
```

The steps that take an energy from the archive, the household segmentation, the productive
class profiles and the own levels, read each reading over its own period, the time since
the code's previous reading capped at a day (`demand/readings.py`): a meter that reports
once after a gap in communication carries the gap's mean power, which a quarter-hour apiece
dropped. Every step writes to `ramp_params/reference/` by default and is deterministic given
its default settings, except the last: the scaling factors are fitted against RAMP simulations
and move by the Monte-Carlo noise of sixty households from one run to the next.
`tests/test_demand_calibration.py` re-runs the segmentation and asserts that it reproduces
the committed CSVs exactly, so that the calibration and the code that produces it cannot
drift apart unnoticed.

Two of these tables are also written on first use when they are absent, which is why a
rebuild runs the chain rather than relying on a stale file being noticed: an extended
archive leaves `archetype_profiles.csv` and `mixture_by_maturity.csv` describing the
shorter record, and nothing asks for them again.

The robust-outlier threshold must be the same in the segmentation and in the mixture
model (currently 4.5): the mixture model assigns observations to the clusters the
segmentation defines, so a mismatch would silently segment the same households two
different ways.

## Parameters, and how they declare their own standing

No numerical value is written into the code that computes with it. Every parameter is
declared once in `settings.py`, which a project overrides through a settings file
(`python -m microgrid_expansion.settings template`); `config.py` derives its constants from
that declaration and holds none of its own. A value the study has not verified against a
source carries a provenance marked unverified and is listed by

```bash
python -m microgrid_expansion.settings check
```

so that a placeholder can never pass silently for a measurement. Two remain: the diesel
price, which is the central value of a sensitivity axis rather than a fixed datum, and the
value of lost load, which is argued from the tariff rather than measured.

The generator catalogue quotes the consumption its manufacturer publishes at half, three-
quarter and full load for each unit of the Perkins 400 series in the range this study needs
(10, 15 and 20 kVA, converted to active power at the catalogue power factor). Their curves
are measured unit by unit rather than one curve rescaled across sizes — their specific
consumption is not monotone in rating, which a scaled curve could not reproduce and which
matters because the certificate arbitrates between exactly these sizes.

The coupling architecture is a parameter with consequences, not a label. Under direct-current
coupling the array is admitted by the hybrid inverter's integrated trackers, at about 1.3 kW
of array per kilowatt of inverter on current three-phase units, and nothing further is
bought: no charge controller is sized outside the inverter, two regulators on one lithium
bank being safe only where both answer to the same battery-management conversation. Under
alternating-current coupling the array carries its own string inverters at 50 000 FCFA/kW
and is held at parity with the hybrid inverter, since off grid whatever the load does not
take must be absorbable by the battery inverter. Set `coupling.architecture` to `dc`, `ac`,
or `auto` to have both certified and the cheaper reported.

## Notes

- The census totals used to scale the sampled households to the full communities are
  declared in `build_monthly_household_clusters.py` (Gbowele: 143 HH1, 5 HH2, 11 HH3;
  Samionta: 231 HH1).
- The meteorological series are produced by
  `python data/irradiance/download.py era5 --site <name>`. Two conventions in that
  conversion were verified against the site's computed solar noon and are pinned by
  `tests/test_era5_acquisition.py`: the time-series product accumulates irradiance **over
  each hour** (so the flux is the value divided by 3600, not a first difference), and it
  labels each value by the **end** of that hour (so relabelling to local hour-beginning
  means subtracting one hour and adding the UTC offset — which cancel exactly for West
  Africa Time). Getting either wrong distorts or displaces the day without raising.
- Climate projections come from NASA's downscaled CMIP6 archive rather than from the raw
  model output. Two reasons: it is already bias-corrected to a quarter of a degree, which is
  the downscaling step this study would otherwise have to perform and could not validate;
  and its subset service returns a single grid point openly, so a site needs kilobytes where
  the raw archive needs hundreds of megabytes per variable-year and a licence agreement that
  the Copernicus route would not grant without a manual acceptance. Three models are averaged
  before downscaling — the spread between modelling centres over West Africa is comparable to
  the spread between pathways at this horizon. Note that the grid label in a file name is a
  property of the model (`gr1`, `gr`, `gn`), and that requesting the wrong one returns a 404
  indistinguishable from a model which does not publish that pathway.
- Three pathways are retained (SSP1-2.6, SSP2-4.5, SSP3-7.0). SSP5-8.5 is deliberately
  excluded as an implausible high-forcing trajectory rather than a business-as-usual
  baseline; see the formulation's uncertainty-space section.
- Survey-derived appliance ownership and usage distributions feed the Monte-Carlo demand
  sampler through the per-cluster RAMP parameters above.
