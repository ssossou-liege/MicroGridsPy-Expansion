"""Productive uses: how many enterprises connect, and what each of them draws.

Households and productive users are not the same modelling problem. A community's
households are counted once, before the grid is built, and the question is how many of
them connect and how their consumption matures. Enterprises cannot be counted that way:
nobody knows in advance who will start a business, and the census taken before
construction says nothing about it. Their number is therefore carried as a *trajectory*
conditioned on the age of the connection, drawn stochastically, and bracketed by the same
envelope as household growth --- which is an honest statement of what two reference sites
support, and no more.

What each enterprise draws is taken from measurement rather than from an appliance model.
The survey conducted on these sites records activity, working hours and use windows
reliably, but forty-two per cent of its nameplate powers are entered as zero: mills,
incubators and refrigerators whose rating plate the surveyor could not read, the technical
label having been photographed sixteen times out of fifty. Building a bottom-up appliance
model on that would be building on the one field the survey does not support. The meter
records, by contrast, cover every connected enterprise. Activity class comes from the
survey; magnitude and shape come from the meters.

Classes matter because these users are extremely unequal: the five largest account for
sixty-one per cent of the energy the sampled enterprises consume, and their shapes differ
in kind rather than in degree. Milling, sewing and sawing are frankly diurnal, peaking in
the afternoon; refrigeration and egg incubation run around the clock; the many small
trading activities keep the evening profile of a household. A single average enterprise
would reproduce none of them, and would in particular erase the daytime load that decides
whether an array should be coupled on the direct or the alternating side.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..paths import REFERENCE_DIR

#: Activity classes, in the order they are reported.
CLASSES = ("refrigeration", "milling", "incubation", "tailoring", "sawmill", "small_trade")

#: Enterprises the survey did not reach. They are not unclassified in the sense of being
#: unknown: they are the small trading activities the survey deliberately passed over in
#: favour of the large consumers, and their measured profile is reported as its own class
#: rather than folded into an average that would misdescribe both ends.
UNSURVEYED = "small_trade"

HOURS = tuple(range(24))


def classify(activity: str) -> str:
    """Map a declared economic activity to one of the modelled classes."""
    text = unicodedata.normalize("NFKD", str(activity).upper())
    text = "".join(c for c in text if not unicodedata.combining(c))
    if any(k in text for k in ("GLACE", "BOISSON", "JUS", "POISSONNERIE",
                               "CONGEL", "FRAICH")):
        return "refrigeration"
    if any(k in text for k in ("MOULIN", "MOUTURE")):
        return "milling"
    if any(k in text for k in ("COUVEUSE", "COUVAISON", "ECLOSION", "OEUF")):
        return "incubation"
    if any(k in text for k in ("COUTURE", "TAILLEUR")):
        return "tailoring"
    if "SCIERIE" in text:
        return "sawmill"
    return UNSURVEYED


@dataclass(frozen=True)
class ProductiveCalibration:
    """Everything the generator needs about productive users, read from the CSVs."""

    profiles: pd.DataFrame        # class x hour -> mean kW per connected unit
    mix: pd.DataFrame             # class x trajectory -> share of connections
    intensity: pd.DataFrame       # maturity band x trajectory -> units per census household

    @classmethod
    def load(cls) -> "ProductiveCalibration":
        d = REFERENCE_DIR
        profiles = pd.read_csv(d / "pue_class_profiles.csv", index_col="activity_class")
        # Hour columns arrive as strings; anything else — the day-to-day spread — keeps
        # its name.
        profiles.columns = [int(c) if str(c).isdigit() else c for c in profiles.columns]
        mix = pd.read_csv(d / "pue_class_mix.csv", index_col="activity_class")
        # The table is stored rounded; a multinomial draw needs probabilities that sum to
        # one exactly, and one part in a million the wrong way makes it refuse.
        mix = mix / mix.sum(axis=0)
        intensity = pd.read_csv(d / "pue_connection_intensity.csv",
                                index_col="maturity")
        return cls(profiles=profiles, mix=mix, intensity=intensity)


def sample_units(calibration: ProductiveCalibration, n_connected: int,
                 maturity_band: str, trajectory: str,
                 rng: np.random.Generator,
                 expected_units: int | None = None) -> dict[str, int]:
    """Draw how many enterprises of each class are connected.

    ``n_connected`` counts the households already on the grid, not the community's census:
    enterprises appear alongside existing connections, and a ratio taken over dwellings
    that are not yet connected would not transfer to a site whose connection has advanced
    at another pace.

    The expected number follows the connection intensity measured at the reference sites
    for this maturity and trajectory; the realised number is a Poisson draw around it,
    business creation being a counting process rather than a fixed roster. Classes are
    then allocated multinomially from the observed mix.

    ``expected_units`` overrides that expectation with what the developer expects on this
    site, which is usually better information than a ratio transferred from two other
    villages: the mill and the welder decide whether the plant is daytime-heavy or
    evening-heavy, and someone who has surveyed the community knows how many are coming.
    It replaces the mean, not the draw -- the count stays uncertain because business
    creation is.
    """
    band = maturity_band if maturity_band in calibration.intensity.index \
        else calibration.intensity.index[-1]
    column = trajectory if trajectory in calibration.intensity.columns else "central"
    expected = (float(expected_units) if expected_units is not None
                else float(calibration.intensity.loc[band, column]) * n_connected)
    total = int(rng.poisson(max(expected, 0.0)))
    if total == 0:
        return {c: 0 for c in calibration.mix.index}
    shares = calibration.mix[column if column in calibration.mix.columns else "central"]
    draw = rng.multinomial(total, shares.to_numpy())
    return dict(zip(calibration.mix.index, (int(n) for n in draw)))


def monthly_profile_kw(counts: dict[str, int], calibration: ProductiveCalibration,
                       days: int, rng: np.random.Generator) -> np.ndarray:
    """Hourly load of the connected enterprises over one month [kW].

    Each class contributes its measured mean day, scaled each day by a draw whose spread
    reproduces the day-to-day variability measured for that class. Repeating a mean day
    unchanged would flatten exactly the peaks a storage sizing is most sensitive to; a mill
    that runs hard two days in three is not a mill running steadily at two thirds.
    """
    hours = [h for h in range(24) if h in calibration.profiles.columns]
    total = np.zeros(days * 24)
    for klass, n in counts.items():
        if not n or klass not in calibration.profiles.index:
            continue
        shape = calibration.profiles.loc[klass, hours].to_numpy(dtype=float)
        spread = float(calibration.profiles.loc[klass].get("daily_cv", 0.0) or 0.0)
        # Log-normal about a unit mean, so the drawn days average to the measured day.
        sigma = float(np.sqrt(np.log1p(spread ** 2)))
        factors = rng.lognormal(-0.5 * sigma ** 2, sigma, size=(n, days))
        total += (factors.sum(axis=0)[:, None] * shape[None, :]).ravel()
    return total
