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
| `irradiance/sam_solar_irradiance_hourly_2016_2025.csv` | ERA5 reanalysis via the Copernicus Climate Data Store | Hourly global horizontal irradiance, Samionta, 2016–2025 | ✅ |
| `irradiance/download.py` | ERA5 + CMIP6 multi-model ensemble | Downscaling framework producing SSP-consistent hourly irradiance, air temperature and wind (see `irradiance/README.md`) | ✅ script, ⬜ outputs |
| `irradiance/` per-SSP series | Output of `download.py` | SSP1-2.6 / SSP2-4.5 / SSP3-7.0 hourly profiles per milestone year | ⬜ pending |
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
- Climate scenarios are not yet generated; the available irradiance is the historical
  ERA5 series. SSP-downscaled irradiance is added here as `download.py` is run.
- Three pathways are retained (SSP1-2.6, SSP2-4.5, SSP3-7.0). SSP5-8.5 is deliberately
  excluded as an implausible high-forcing trajectory rather than a business-as-usual
  baseline; see the formulation's uncertainty-space section.
- Survey-derived appliance ownership and usage distributions feed the Monte-Carlo demand
  sampler through the per-cluster RAMP parameters above.
