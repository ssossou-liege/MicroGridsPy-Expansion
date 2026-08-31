"""Turn the long RAMP parameter table into the wide one the reference sheets use.

A one-off conversion kept beside the data it converts. The long form -- one row per
(cluster, appliance, parameter) -- is what the calibration writes; the wide form, one row
per appliance with a column per parameter, is what a person reads and what the reference
workbook expects. Paths are placeholders: set them before running.
"""
import pandas as pd

LONG_FILE = "long_table.csv"
WIDE_FILE = "wide_table.csv"

long_frame = pd.read_csv(LONG_FILE)

# cluster, n_users and appliance stay as the index; the values of "parameter" become
# columns.
wide = long_frame.pivot_table(
    index=["cluster", "n_users", "appliance"],
    columns="parameter",
    values="value",
    aggfunc="first",
).reset_index()

wide = wide.rename(columns={"n_users": "num_users", "appliance": "name"})

# Present in the reference sheet, empty in the calibration output.
wide["user_name"] = ""

COLUMN_ORDER = [
    "cluster",
    "user_name",
    "num_users",
    "name",
    "number",
    "power",
    "func_time",
    "func_cycle",
    "occasional_use",
    "w1_start",
    "w1_end",
]

# Reordered without assuming every parameter is present: a calibration that did not fit an
# appliance leaves its column out entirely, and that is not a reason to fail here.
final = wide[[column for column in COLUMN_ORDER if column in wide.columns]]

# The reference sheet shows the cluster number and its user count on the group's first row
# only, which is a reading convenience rather than a property of the data.
final.loc[final.duplicated(subset=["cluster"]), ["cluster", "num_users"]] = ""

final.to_csv(WIDE_FILE, index=False)

print(f"written {WIDE_FILE}")
