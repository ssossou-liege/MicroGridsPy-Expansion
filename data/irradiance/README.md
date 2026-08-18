**IMPORTANT NOTICE !!!**
Go to the Climate Data Store on this link to setup API
https://cds.climate.copernicus.eu/how-to-api

Here we use a comprehensive computational framework designed to downscale and synthesize multi-variable climate data. Operating at the intersection of long-term climate change projection and high-frequency resource volatility, the system bridges the structural resolution gap inherent in Global Climate Models (GCMs). It systematically translates macroscopic climate trajectories into localized, multi-variable engineering time-series tailored for infrastructure simulation.

       [ 5-Year Historical ERA5 ]             [ Multi-Model GCM Ensemble ]
                    │                                      │
                    ▼                                      ▼
         ┌─────────────────────┐                ┌─────────────────────┐
         │ Clear-Sky Envelope  │                │ Daily Mean Horizons │
         │   Auto-Calibration  │                │ (SSP Climate Paths) │
         └──────────┬──────────┘                └──────────┬──────────┘
                    │                                      │
                    ▼                                      ▼
         ┌─────────────────────┐                ┌─────────────────────┐
         │ Clearness Index     │                │ Astronomical Hourly │
         │ Stochastic Variance │                │    Disaggregation   │
         └──────────┬──────────┘                └──────────┬──────────┘
                    │                                      │
                    └──────────────────┬───────────────────┘
                                       │
                                       ▼
                            ┌─────────────────────┐
                            │ Integrated Sizing   │
                            │   Profiles (CSV)    │
                            │ ───────────────     │
                            │  GHI (Stochastic)   │
                            │  Air Temperature    │
                            │  Wind Vector Mod.   │
                            └─────────────────────┘

The underlying architecture unifies historical weather reanalysis records from the fifth-generation European Centre for Medium-Range Weather Forecasts (ERA5) with forward-looking climate projections derived from the Coupled Model Intercomparison Project Phase 6 (CMIP6). By harmonizing these distinct data streams, the framework generates cohesive, continuous weather profiles. Each output dataset tracks a specific Shared Socioeconomic Pathway (SSP) across a discrete twenty-year planning horizon, providing an empirical baseline.

### Atmospheric Clearness Calibration and Volatility Modeling

The sequence begins with an autonomous empirical assessment of local atmospheric properties. Utilizing a continuous five-year historical hourly window updated relative to the execution epoch, the algorithm evaluates the local top-of-atmosphere solar constant ($1361 \text{ W/m}^2$) against actual ground-level Global Horizontal Irradiance (GHI). Instead of prescribing static regional coefficients, the framework executes an automatic calibration routine. By isolating the $98\text{th}$ percentile of daytime solar transmission under peak solar elevations, it deduces a unique, site-specific atmospheric transmission ceiling. This localized boundary accounts for persistent geographic features such as regional humidity, aerosol columns, or cyclical dust phenomena like the West African Harmattan.

Once this clear-sky envelope is established, the framework isolates cloud-induced volatility by computing a historical Clearness Index ($K_t$) across all daytime intervals. The variance of these microstructural deviations is statistically parsed to define a local stochastic atmospheric disturbance profile.

### Multi-Model Ensemble Harmonization and Temporal Disaggregation

To project resource availability into future decades, the framework evaluates structural climate uncertainties by constructing a multi-model ensemble from independent international modeling suites, including the Institut Pierre-Simon Laplace (IPSL-CM6A-LR), the European Consortium (EC-Earth3), and the Geophysical Fluid Dynamics Laboratory (GFDL-ESM4). Daily downwelling shortwave radiation, surface air temperature, and near-surface wind speed vectors are aggregated across three standard IPCC warming scenarios (SSP1-2.6, SSP2-4.5, and SSP3-7.0). The high-forcing pathway SSP5-8.5 is deliberately excluded: its emission trajectory is now widely regarded as implausible rather than as a business-as-usual baseline, so retaining it would widen the spread of the resource scenarios without informing the sizing decision.

The daily deterministic mean trends provided by the multi-model ensemble are then disaggregated to an hourly resolution using astronomical geometry. For every day of the projected simulation period, the theoretical solar zenith angle is resolved step-by-step, shaping the lised, daily macro-scale energy budget into a physically coherent hourly diurnal bell curve.

### Stochastic Synthesis and Multi-Variable Integration

The definitive stage involves superimposing high-frequency stochastic noise onto the deterministic future solar vectors. Using the variance derived during the historical calibration phase, a Gaussian perturbation matrix simulates local transient cloud-shading events—the characteristic "teeth" profile observed in real-world solar arrays. To maintain physical boundaries, an hourly clipping filter suppresses non-physical perturbations during nocturnal frames and prevents irradiance values from exceeding the theoretical clear-sky limit.

Simultaneously, the environmental co-variables essential for precise PV cell thermodynamics—ambient air temperature and cooling wind speed vectors—are dynamically synchronized with the solar profile. The finalized, integrated datasets are compiled into standardized matrices containing continuous time-series of irradiance, ambient temperature, and wind velocity.

### Engineering Utility 

The resulting datasets provide high-fidelity inputs for robust sizing and dispatch algorithms. By providing synchronized environmental variables rather than isolated solar metrics, the framework enables the direct application of advanced convective-cooling formulations, such as the Faiman or Sandia cell temperature models.

During peak diurnal periods where high ambient temperatures degrade PV module voltage and reduce net efficiency, the explicit representation of localized wind vectors allows the sizing optimization model to accurately resolve cell cooling. Furthermore, by evaluating system performance against the stochastically perturbed solar profiles rather than idealized, smoothed GCM averages, the optimization engine captures the true stress conditions imposed by short-term power intermittency. 