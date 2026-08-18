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
| `irradiance/` per-SSP series | Output of `download.py cmip6` | SSP1-2.6 / SSP2-4.5 / SSP3-7.0 hourly profiles per milestone year | ⬜ pending (layer L4) |
| `ramp_params/reference/archetype_scaling.csv` | Fitted by `microgrid_expansion.demand.calibration` | Power and duration factors reconciling the appliance calibration with the measured archetype statistics | ✅ |
| `costs/` | Economic constants, currently in `src/microgrid_expansion/config.py` | Capital-cost and fuel-price trajectories | ⬜ pending |

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
- Climate scenarios are not yet generated; the available series are the historical ERA5
  reanalysis. SSP-downscaled series are added here as `download.py cmip6` is run.
- Three pathways are retained (SSP1-2.6, SSP2-4.5, SSP3-7.0). SSP5-8.5 is deliberately
  excluded as an implausible high-forcing trajectory rather than a business-as-usual
  baseline; see the formulation's uncertainty-space section.
- Survey-derived appliance ownership and usage distributions feed the Monte-Carlo demand
  sampler through the per-cluster RAMP parameters above.
