import os
import numpy as np
import pandas as pd
import xarray as xr
import cdsapi
from scipy.stats import norm

from datetime import datetime
from pathlib import Path

# ==============================================================================
# CONFIGURATION & SITE PARAMETERS
# ==============================================================================

# GBOWELE

LAT_TARGET = 7.62
LON_TARGET = 2.20
MICRO_BOX = [LAT_TARGET + 0.13, LON_TARGET - 0.13, LAT_TARGET - 0.13, LON_TARGET + 0.13]

# Timeline parameters
current_year = datetime.now().year
HIST_YEARS = list(range(current_year - 5, current_year))  # Last 5 years for historical calibration
SIMULATION_YEARS = [current_year + (5 * i) for i in range(5)] # Next 20 years in 5-year increments

# SSP5-8.5 is deliberately excluded: its emission trajectory is now widely regarded as
# implausible rather than as a business-as-usual baseline, so it would widen the spread of
# the resource scenarios without informing the sizing decision.
SCENARIOS = ["ssp1_2_6", "ssp2_4_5", "ssp3_7_0"]
GCM_MODELS = ["ipsl_cm6a_lr", "ec_earth3", "gfdl_esm4"]

output_dir = Path.cwd().resolve() / "downloaded_data"
os.makedirs(output_dir, exist_ok=True)

save_dir = Path.cwd().resolve()

c = cdsapi.Client()

# ==============================================================================
# FUNCTIONS FOR SOLAR GEOMETRY & STOCHASTIC PERTURBATION
# ==============================================================================
def compute_cos_zenith(lat, lon, day_of_year, hour):
    """Calculates the cosine of the solar zenith angle."""
    dec = 23.45 * np.sin(np.radians(360 / 365 * (day_of_year - 80)))
    hour_angle = 15 * (hour - 12)
    cos_zenith = (np.sin(np.radians(lat)) * np.sin(np.radians(dec)) + 
                  np.cos(np.radians(lat)) * np.cos(np.radians(dec)) * np.cos(np.radians(hour_angle)))
    return max(0.0, cos_zenith)

def generate_clear_sky_ghi(lat, lon, time_index, transmission_factor=1.0):
    """Generates a theoretical clear sky GHI profile (W/m2) using a simplified clear-sky model."""
    solar_constant = 1361.0  # W/m2
    clear_sky = []
    for timestamp in time_index:
        doy = timestamp.dayofyear
        hour = timestamp.hour
        cos_z = compute_cos_zenith(lat, lon, doy, hour)
        # Apply the transmission factor to account for atmospheric effects (e.g., aerosols, water vapor)
        clear_sky.append(solar_constant * transmission_factor * cos_z)
    return np.array(clear_sky)

# ==============================================================================
# DOWNLOAD HISTORICAL ERA5 DATA (HOURLY)
# ==============================================================================
era5_file = f"{output_dir}/era5_historical_hourly.nc"
if not os.path.exists(era5_file):
    print("--> Downloading 5-year historical hourly ERA5 weather data...")
    c.retrieve(
        "reanalysis-era5-land-timeseries",
        {
            "variable": [
                "surface_solar_radiation_downwards",  # ssrd (GHI)
                "2m_temperature",                     # t2m (Air Temperature)
                "10m_u_component_of_wind",                     # si10 (Wind Speed)
                "10m_v_component_of_wind"                      # si10 (Wind Speed)
            ],
            "location": {"longitude": LON_TARGET, "latitude": LAT_TARGET},
            "date": [f"{HIST_YEARS[0]}-01-01/{HIST_YEARS[-1]}-12-31"],
            "data_format": "netcdf"
        }        
    ).download(era5_file)

# ==============================================================================
# ANALYZE HISTORICAL K_T VARIABILITY (STOCHASTIC MODEL CALIBRATION)
# ==============================================================================
print("--> Processing historical data and calibrating weather profiles...")
ds_era5 = xr.open_dataset(era5_file)

era5_time = pd.to_datetime(ds_era5["valid_time"].values)

# Conversion of units for ERA5 variables
era5_ghi = ds_era5["ssrd"].values / 3600.0  # Convert J/m2 to W/m2
era5_temp = ds_era5["t2m"].values - 273.15  # Convert Kelvin to Celsius
era5_wind = np.sqrt(ds_era5["u10"].values**2 + ds_era5["v10"].values**2)  # Calculate wind speed: sqrt(u^2 + v^2) m/s


# Calculate local transmission factor based on historical clear-sky GHI vs ERA5 GHI during daytime hours
raw_clear_sky = generate_clear_sky_ghi(LAT_TARGET, LON_TARGET, era5_time, transmission_factor=1.0)

# Find the clear sky days in the ERA5 data by selecting the 98th percentile of the real ratio during mid-day
daytime = raw_clear_sky > 200.0
local_ratios = era5_ghi[daytime] / raw_clear_sky[daytime]
local_transmission_factor = np.percentile(local_ratios, 98)

historical_clear_sky = generate_clear_sky_ghi(LAT_TARGET, LON_TARGET, era5_time, transmission_factor=local_transmission_factor)

# Calculate historical Clearness Index (Kt), avoiding division by zero at night
kt_historical = np.zeros_like(era5_ghi)
daytime_mask = historical_clear_sky > 50.0  # Only analyze daytime hours where radiation is significant
kt_historical[daytime_mask] = era5_ghi[daytime_mask] / historical_clear_sky[daytime_mask]
# Clip to physical limits
kt_historical = np.clip(kt_historical, 0.0, 1.1)

# Extract the high-frequency stochastic residuals (fluctuations around the mean daytime Kt)
daytime_kt_values = kt_historical[daytime_mask]
kt_mean = np.mean(daytime_kt_values)
kt_std = np.std(daytime_kt_values)
print(f"Calibrated Clearness Index parameters -> Mean: {kt_mean:.3f}, StdDev (Cloud volatility): {kt_std:.3f}")

# ==============================================================================
# EXPORT HISTORICAL ERA5 DATA TO CSV
# ==============================================================================
print("--> Exporting historical ERA5 profiles to CSV...")

# Create a clean DataFrame for the historical data
df_era5_out = pd.DataFrame({
    "timestamp": era5_time,
    "irradiance_w_m2": era5_ghi,
    "temperature_C": era5_temp,
    "wind_speed_m_s": era5_wind,
    "year": era5_time.year  
})

df_era5_out.reset_index(drop=True, inplace=True)

# Save the historical reference profile
output_era5_csv = f"{save_dir}/historical_weather_{HIST_YEARS[0]}_{HIST_YEARS[-1]}.csv"
df_era5_out.to_csv(output_era5_csv, index=False)
print(f"Generated Historical ERA5 Reference File -> {output_era5_csv}")

# ==============================================================================
# DOWNLOAD CMIP6 CLIMATE PROJECTIONS & GENERATE PERTURBED FUTURE PROFILES
# ==============================================================================
variables_cmip6 = {
    "rsds": "surface_downwelling_shortwave_radiation",
    "tas": "near_surface_air_temperature",
    "sfcWind": "near_surface_wind_speed"
}

for ssp in SCENARIOS:
    for year in SIMULATION_YEARS:
        gcm_data = {var: [] for var in variables_cmip6.keys()}
        
        for model in GCM_MODELS:
            for var_key, var_name in variables_cmip6.items():
                filename = f"{output_dir}/raw_daily_{model}_{ssp}_{var_key}_{year}.nc"
                
                if not os.path.exists(filename):
                    print(f"--> Downloading CMIP6: Model={model} | SSP={ssp} | Var={var_key} | Year={year}")
                    try:
                        c.retrieve(
                            "projections-cmip6",
                            {
                                "format": "zip",
                                "temporal_resolution": "daily",
                                "experiment": ssp,
                                "level": "single_levels",
                                "variable": var_name,
                                "model": model,
                                "date": f"{year}-01-01/{year}-12-31",
                                "area": MICRO_BOX,
                            },
                            f"{filename}.zip"
                        )
                        os.system(f"unzip -q {filename}.zip -d {output_dir} && mv {output_dir}/*.nc {filename} 2>/dev/null")
                        os.system(f"rm -f {filename}.zip")
                    except Exception as e:
                        print(f"Failed download for {model} {var_key}: {e}")
                
                if os.path.exists(filename):
                    ds = xr.open_dataset(filename)
                    # Handle variable naming alignment in different modeling centers
                    var_name_in_file = [v for v in ds.variables if v in variables_cmip6.keys()][0]
                    
                    # Coordinate structure normalization for CMIP6 models
                    gcm_lat = "latitude" if "latitude" in ds.coords else "lat"
                    gcm_lon = "longitude" if "longitude" in ds.coords else "lon"
                    
                    gcm_data[var_key].append(ds[var_name_in_file].sel({gcm_lat: LAT_TARGET, gcm_lon: LON_TARGET}, method="nearest"))

        # Process Multi-Model Mean and Temporal Downscaling to Hourly step
        if all(len(gcm_data[v]) == len(GCM_MODELS) for v in variables_cmip6.keys()):
            mmm_daily = {}
            for var_key in variables_cmip6.keys():
                combined = xr.concat(gcm_data[var_key], dim="model")
                mmm_daily[var_key] = combined.mean(dim="model").values

            # Initialize hourly index for the simulation year
            time_index = pd.date_range(start=f"{year}-01-01", end=f"{year}-12-31 23:00:00", freq="h")
            future_clear_sky = generate_clear_sky_ghi(LAT_TARGET, LON_TARGET, time_index, local_transmission_factor)
            
            # Disaggregate GHI daily mean trend into deterministic hours
            hourly_ghi_det = []
            for doy, daily_ghi in enumerate(mmm_daily["rsds"]):
                hours = np.arange(24)
                cos_z_day = np.array([compute_cos_zenith(LAT_TARGET, LON_TARGET, doy + 1, h) for h in hours])
                day_profile = (cos_z_day / np.sum(cos_z_day)) * (daily_ghi * 24) if np.sum(cos_z_day) > 0 else np.zeros(24)
                hourly_ghi_det.extend(day_profile)
            hourly_ghi_det = np.array(hourly_ghi_det[:len(time_index)])

            # Apply stochastic cloud noise using calibrated historical variance
            np.random.seed(42)
            stochastic_noise = np.random.normal(loc=0.0, scale=kt_std, size=len(time_index))
            hourly_ghi_stoch = np.zeros_like(hourly_ghi_det)
            for i in range(len(time_index)):
                if future_clear_sky[i] > 50.0:
                    kt_det = hourly_ghi_det[i] / future_clear_sky[i]
                    kt_stoch = np.clip(kt_det + stochastic_noise[i], 0.0, 1.0)
                    hourly_ghi_stoch[i] = kt_stoch * future_clear_sky[i]

            # Map thermal and mechanical variables from daily mean to hours
            # Temperature repeats the daily mean, Wind speed applies uniform distribution
            hourly_temp = np.repeat(mmm_daily["tas"] - 273.15, 24)[:len(time_index)] # Kelvin to C
            hourly_wind = np.repeat(mmm_daily["sfcWind"], 24)[:len(time_index)]

            # Save full multi-variable file for investment sizing loops
            df_future_out = pd.DataFrame({
                "timestamp": time_index,
                "irradiance_w_m2": hourly_ghi_stoch,
                "temperature_C": hourly_temp,
                "wind_speed_m_s": hourly_wind,
                "year": year
            })
            
            output_csv = f"{save_dir}/weather_{ssp}_{year}.csv"
            df_future_out.to_csv(output_csv, index=False)
            print(f"Generated Full Weather File -> {output_csv} (Variables: GHI, Temp, Wind)")