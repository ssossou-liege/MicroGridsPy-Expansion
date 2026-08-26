# data/ — provenance

Inputs in this directory are copied (not symlinked) so this repository stays
self-contained and reproducible. Each entry records what the data is, where it comes
from, and what produces it.

| Local path | Origin | Description | Status |
|---|---|---|---|
| `demand/household_customers.csv` | Operator customer roster | 141 sampled households: code, socio-economic type (HH1–HH3), site, connection date | ✅ |
| `demand/customer_info.parquet` | Operator customer database | Customer attributes for the two reference sites | ✅ |
| `demand/gbo_meter_readings.parquet` | Smart-meter archive, Gbowele | Quarter-hourly per-customer power readings | ✅ |
| `demand/sam_meter_readings.parquet` | Smart-meter archive, Samionta | Quarter-hourly per-customer power readings | ✅ |
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
| `ramp_params/reference/archetype_scaling.csv` | Fitted by `microgrid_expansion.demand.calibration` | Power and duration factors reconciling the appliance calibration with the measured archetype statistics | ✅ |
| Economic and technical parameters | `src/microgrid_expansion/settings.py`, overridable per project | Discount rate, unit costs, generator catalogue, battery chemistry, tariff target | ✅ |

## Reproducibility

The calibration in `ramp_params/reference/` is regenerated from the raw meter readings by

```bash
python -m microgrid_expansion.demand.build_monthly_household_clusters
python -m microgrid_expansion.demand.build_mixture_probabilities
```

Both scripts write to `ramp_params/reference/` by default and are deterministic given
their default settings. `tests/test_demand_calibration.py` re-runs the segmentation and
asserts that it reproduces the committed CSVs exactly, so that the calibration and the
code that produces it cannot drift apart unnoticed.

The robust-outlier threshold must be the same in both scripts (currently 4.5): the
mixture model assigns observations to the clusters the first script defines, so a
mismatch would silently segment the same households two different ways.

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
