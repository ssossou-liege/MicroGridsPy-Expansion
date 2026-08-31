"""The behavioural archetypes, what they describe, and how to make them yours.

The four archetypes shipped with the tool were derived from 1 818 household-months of
quarter-hourly meter records in two Beninese villages. That provenance is a limit as much as
a credential: a community whose evenings run later, whose mills run longer, or whose tariff
buys a different appliance mix will not be described by them, and a sizing built on borrowed
behaviour is a sizing built on someone else's village.

Three ways out are offered, in increasing order of effort and of fidelity. The archetypes can
be used as they stand, which is defensible for a West African village of comparable size and
tariff, provided it is said. Their headline characteristics can be adjusted, which is what a
developer who knows the community does when the shipped figures are visibly wrong. Or they can
be rebuilt outright from the user's own meter records, which is what the two reference
villages themselves went through.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

from ..paths import REFERENCE_DIR, USER_SITES_DIR

PROFILES = REFERENCE_DIR / "archetype_profiles.csv"

#: What each archetype is, in the words a developer would use about a household.
DESCRIPTIONS: dict[str, str] = {
    "0": "Average consumption, spread through the day",
    "1": "Frugal, strictly evening",
    "2": "Heavy consumer",
    "3": "Steady, low peak",
}

#: Where the shipped figures come from, shown wherever they are used.
CALIBRATION_NOTE = (
    "Calibrated on 1 818 household-months of quarter-hourly records from 141 households in "
    "two Beninese villages. To be checked before any use on a community whose uses, tariff "
    "or hours differ."
)


@dataclass
class Archetype:
    """One behavioural class, as the interface shows and edits it."""

    cluster: str
    label: str
    share_pct: float
    mean_daily_kwh: float
    mean_peak_w: float
    mean_load_factor: float
    n_observations: int
    well_supported: bool

    def to_dict(self) -> dict:
        return asdict(self)


def _overrides_path(site: str) -> Path:
    keep = "".join(c if c.isalnum() or c in " -_" else "" for c in site)
    return USER_SITES_DIR / f"{keep.strip().replace(' ', '-').lower()}.archetypes.json"


def shipped() -> list[Archetype]:
    """The archetypes as calibrated, before any local adjustment."""
    frame = pd.read_csv(PROFILES, dtype={"cluster": str})
    total = float(frame["n_observations"].sum()) or 1.0
    return [
        Archetype(
            cluster=str(row.cluster),
            label=DESCRIPTIONS.get(str(row.cluster), f"Archetype {row.cluster}"),
            share_pct=round(100.0 * row.n_observations / total, 1),
            mean_daily_kwh=round(float(row.mean_daily_kwh), 4),
            mean_peak_w=round(float(row.mean_peak_w), 1),
            mean_load_factor=round(float(row.mean_load_factor), 4),
            n_observations=int(row.n_observations),
            well_supported=bool(row.has_support),
        )
        for row in frame.itertuples()
    ]


def for_site(site: str) -> tuple[list[Archetype], bool]:
    """The archetypes in force for a site, and whether they were adjusted locally."""
    base = {a.cluster: a for a in shipped()}
    path = _overrides_path(site)
    if not path.exists():
        return list(base.values()), False
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return list(base.values()), False
    for cluster, changes in (stored.get("archetypes") or {}).items():
        if cluster not in base:
            continue
        for key, value in changes.items():
            if key in ("mean_daily_kwh", "mean_peak_w", "mean_load_factor"):
                setattr(base[cluster], key, float(value))
    return list(base.values()), True


def adjust(site: str, archetypes: dict[str, dict]) -> Path:
    """Record a site's local adjustments, leaving the shipped calibration untouched."""
    USER_SITES_DIR.mkdir(parents=True, exist_ok=True)
    path = _overrides_path(site)
    path.write_text(json.dumps({"site": site, "archetypes": archetypes},
                               indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def reset(site: str) -> bool:
    path = _overrides_path(site)
    if not path.exists():
        return False
    path.unlink()
    return True


def rebuild_from_meters(readings: Path, customers: Path) -> list[Archetype]:
    """Derive archetypes from the user's own records, the way the shipped ones were derived.

    Runs the same segmentation the reference villages went through: monthly features per
    household, winsorising, outlier rejection by median absolute deviation, then clustering
    in the three descriptors. Returns what it found without writing anything, so that a
    developer can compare it against the shipped set before adopting it.
    """
    from . import partition as P

    customers_frame = pd.read_parquet(customers) if customers.suffix == ".parquet" \
        else pd.read_csv(customers)
    readings_frame = pd.read_parquet(readings) if readings.suffix == ".parquet" \
        else pd.read_csv(readings)
    features = P.compute_monthly_features(readings_frame, customers_frame)
    segmented = P.assign_clusters_from_reference_profiles(features)

    active = segmented[~segmented.is_inactive & ~segmented.is_outlier]
    total = float(len(active)) or 1.0
    out = []
    for cluster, block in active.groupby("cluster"):
        out.append(Archetype(
            cluster=str(cluster),
            label=DESCRIPTIONS.get(str(cluster), f"Archetype {cluster}"),
            share_pct=round(100.0 * len(block) / total, 1),
            mean_daily_kwh=round(float(block.mean_daily_kWh.mean()), 4),
            mean_peak_w=round(float(block.peak_power.mean()), 1),
            mean_load_factor=round(float(block.load_factor.mean()), 4),
            n_observations=int(len(block)),
            well_supported=len(block) >= P.MIN_SUPPORT,
        ))
    return sorted(out, key=lambda a: a.cluster)


def scaling_for(site: str):
    """The moment-matching factors a site's adjusted archetypes imply.

    The generator reconciles its appliance sets to two measured statistics through two
    factors: power scales every rated power, moving peak and energy together, and time
    scales every duration, moving energy alone. Peak is therefore proportional to the power
    factor and energy to the product of the two, which inverts exactly:

        power' = power x (peak' / peak)
        time'  = time  x (energy' / energy) / (peak' / peak)

    So an adjusted archetype propagates into the simulated load without refitting anything,
    and without the adjustment being a number the user changes while the sizing ignores it.
    """
    from .generator import ArchetypeScaling

    base = ArchetypeScaling.load()
    shipped_by_cluster = {a.cluster: a for a in shipped()}
    local, adjusted = for_site(site)
    if not adjusted:
        return base

    power = dict(base.power)
    time = dict(base.time)
    for a in local:
        reference = shipped_by_cluster.get(a.cluster)
        if reference is None:
            continue
        peak_ratio = (a.mean_peak_w / reference.mean_peak_w
                      if reference.mean_peak_w > 0 else 1.0)
        energy_ratio = (a.mean_daily_kwh / reference.mean_daily_kwh
                        if reference.mean_daily_kwh > 0 else 1.0)
        if peak_ratio <= 0 or energy_ratio <= 0:
            continue
        power[a.cluster] = float(base.power.get(a.cluster, 1.0)) * peak_ratio
        time[a.cluster] = (float(base.time.get(a.cluster, 1.0))
                           * energy_ratio / peak_ratio)
    return ArchetypeScaling(power=power, time=time)


def fingerprint(site: str) -> str:
    """A short digest of a site's adjustments, so a cached year is not reused across them."""
    import hashlib

    local, adjusted = for_site(site)
    if not adjusted:
        return "std"
    payload = ";".join(f"{a.cluster}:{a.mean_daily_kwh:.6f}:{a.mean_peak_w:.4f}"
                       for a in sorted(local, key=lambda x: x.cluster))
    return hashlib.sha1(payload.encode()).hexdigest()[:8]
