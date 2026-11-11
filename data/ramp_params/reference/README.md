# Calibration tables

Every table here is produced by one of the build scripts of `microgrid_expansion.demand`,
and none of them is edited by hand. What matters about each one, and what this file exists
to say, is whether the demand generation reads it.

The cache key of a simulated year hashes the tables the generation reads, so that a
recalibration cannot leave a stored year describing a model that no longer exists. It
deliberately leaves out the tables written for inspection: hashing those rebuilt every
cached year, three hours and a half for the two reference villages, whenever a figure
nobody reads was redrawn.

The two lists below are checked against `instances._NOT_READ_AT_GENERATION` by
`tests/test_nothing_is_declared_without_a_reader.py`, so a table that changes side has to
change side here as well.

## Read at generation

Hashed into the demand fingerprint. Changing one of these invalidates every cached year.

| table | read by | what it carries |
| --- | --- | --- |
| `archetype_hourly_shapes.csv` | `generator.py` | the measured hourly shape of each archetype, which a household of a village's record draws its own level on; written by `build_archetype_shapes.py`, and compared with the shape the appliance library generates |
| `archetype_profiles.csv` | `archetypes.py`, `partition.py` | the four household archetypes, their support and their central daily energy, peak and load factor |
| `archetype_reference_profiles.csv` | `build_mixture_probabilities.py` | the reference profile each household-month is assigned to the nearest of |
| `archetype_scaling.csv` | `generator.py`, `calibration.py` | the power and time scaling applied to an archetype's appliance usage |
| `cluster_params.csv` | `generator.py`, `demand/__init__.py` | the appliance parameters, one row per archetype, appliance and parameter |
| `community_class_profiles.csv` | `uses.py` | the hourly shape of each class of community building, with its daily energy and its variability |
| `connection_curves.csv` | `connection.py` | the logistic connection curve of each reference village's household stock net of departures, under four plateau variants (estimate, the two ends of the plateau's profile interval, census), with standard errors, the identification of the plateau and the months the record covers; written by `build_connection_curves.py` |
| `connection_observed.csv` | `connection.py` | customers per reference village, type (household category or productive user), connection month and, for a household whose failed meter was not replaced, the month it left the grid: the observed state a brownfield plan starts from; written by `build_connection_curves.py` |
| `mixture_by_maturity.csv` | `maturity.py` | the mixture law conditioned on months since connection, with its prior, its posterior and the shrinkage weight |
| `pue_class_mix.csv` | `productive.py` | the mix of productive-use classes under each growth trajectory |
| `pue_class_profiles.csv` | `productive.py` | the hourly shape of each productive-use class |
| `pue_connection_intensity.csv` | `productive.py` | consumption per productive connection by maturity, under each growth trajectory |
| `own_levels.csv` | `connection.py` | each customer the record of a reference village holds, households, productive users and places of worship, at its own level: its type, the shape it draws and where the shape comes from (a household's archetype, from the segmentation of the record's households; a productive user's class, from the activity survey or from its record where the survey missed it; the class `place_of_worship`), connection and departure months, its mean daily energy over its last twelve months of readings, each reading over its own period, a factor per calendar month where its readings cover a year, its day-to-day spread and the highest hourly power its meter recorded; the customers a brownfield plan starts from; written by `build_own_levels.py` |

## Written for inspection

Nothing the generation runs reads these. They are the record of the segmentation, kept so
that a calibration can be checked against the meters rather than taken on trust.

| table | written by | what it carries |
| --- | --- | --- |
| `global_cluster_profiles.csv` | `build_monthly_household_clusters.py` | the robust and arithmetic descriptors of each cluster, with its membership |
| `monthly_household_features.csv` | `build_monthly_household_clusters.py` | one row per household and month: energy, peak, load factor, the days observed and the days the readings cover, each reading over its own period |
| `monthly_household_cluster_assignments.csv` | `build_monthly_household_clusters.py` | the same rows with the cluster each was assigned to |
| `gbowele_monthly_cluster_summary.csv` | `build_monthly_household_clusters.py` | Gbowele month by month: the cluster mix by customer type and the peak |
| `samionta_monthly_cluster_summary.csv` | `build_monthly_household_clusters.py` | Samionta month by month, as above |
| `meter_status.csv` | `build_connection_curves.py` | every customer code of the roster or the meter archive: its type and where the type comes from, its connection month, its first and last reading, and whether its meter still records, has failed (with the month the household left), never recorded, or is no customer's; the list the field team confirms |
| `mixture_probabilities_type_month.csv` | `build_mixture_probabilities.py` | the mixture law by customer type and calendar month, superseded by the maturity-conditioned one and read now only by `validate.py` |

`pivot.py` beside them is a helper for reading these tables by hand; nothing imports it.
