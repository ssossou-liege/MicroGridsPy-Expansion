"""Canonical filesystem locations of the repository's inputs and outputs.

Every module resolves paths through this one, so that scripts behave identically
whatever the working directory they are launched from, and so that relocating a data
directory is a single-line change.
"""
from __future__ import annotations

from pathlib import Path

#: Repository root (the directory containing ``src/``, ``data/``, ``docs/``).
ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = ROOT / "data"
DEMAND_DIR = DATA_DIR / "demand"
IRRADIANCE_DIR = DATA_DIR / "irradiance"
RAMP_DIR = DATA_DIR / "ramp_params"
REFERENCE_DIR = RAMP_DIR / "reference"
COSTS_DIR = DATA_DIR / "costs"

DOCS_DIR = ROOT / "docs"
RESULTS_DIR = ROOT / "results"


def require(path: Path) -> Path:
    """Return ``path``, raising a directed error if it does not exist."""
    if not path.exists():
        raise FileNotFoundError(
            f"{path} is missing. Expected it relative to the repository root {ROOT}; "
            "see data/README.md for how each input is produced."
        )
    return path
