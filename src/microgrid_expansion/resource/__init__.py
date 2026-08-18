"""Conversion of the meteorological series into the quantities the model consumes.

The sizing model does not use irradiance directly: it uses the photovoltaic *specific
yield* -- power produced per unit of installed capacity -- together with the two
temperature-dependent battery quantities that the storage constraints require, namely the
usable-capacity factor and the self-discharge rate.
"""
from .yield_model import (
    ModuleSpec,
    ResourceYear,
    battery_self_discharge,
    battery_usable_fraction,
    cell_temperature,
    load_irradiance,
    specific_yield,
    simulate_resource_year,
)

__all__ = [
    "ModuleSpec",
    "ResourceYear",
    "battery_self_discharge",
    "battery_usable_fraction",
    "cell_temperature",
    "load_irradiance",
    "specific_yield",
    "simulate_resource_year",
]
