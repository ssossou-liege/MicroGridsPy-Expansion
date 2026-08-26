#!/usr/bin/env python3
"""Acquisition of the meteorological series for a site.

Thin command-line entry point over the acquisition modules of the package, so that the
same code serves the command line, the test suite and a user interface.

    # historical reanalysis: irradiance, temperature and wind (layers L1-L3)
    python data/irradiance/download.py era5 --site Samionta

    # climate projections for the scenario tree (layer L4)
    python data/irradiance/download.py cmip6 --site Samionta --year 2031

Requires Climate Data Store credentials in ~/.cdsapirc; see the notice in README.md.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from microgrid_expansion.resource import era5                      # noqa: E402
from microgrid_expansion.resource import cmip6                     # noqa: E402
from microgrid_expansion.sites import get_site                     # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    historical = sub.add_parser("era5", help="historical reanalysis series")
    historical.add_argument("--site", required=True)
    historical.add_argument("--first-year", type=int, default=2016)
    historical.add_argument("--last-year", type=int, default=2025)
    historical.add_argument("--overwrite", action="store_true")

    projection = sub.add_parser("cmip6", help="climate projections (scenario tree)")
    projection.add_argument("--site", required=True)
    projection.add_argument("--years", type=int, nargs="+", required=True,
                            help="milestone years of the scenario tree")
    projection.add_argument("--scenarios", nargs="*", default=list(cmip6.SCENARIOS))
    projection.add_argument("--models", nargs="*", default=list(cmip6.GCM_MODELS))
    projection.add_argument("--seed", type=int, default=0)

    args = parser.parse_args(argv)
    site = get_site(args.site)

    if args.command == "era5":
        era5.download_era5(site, args.first_year, args.last_year,
                           overwrite=args.overwrite)
        return 0

    for scenario in args.scenarios:
        for year in args.years:
            written = cmip6.write_hourly_series(site, scenario, year,
                                                models=tuple(args.models),
                                                seed=args.seed)
            print(f"  {scenario:8s} {year}  "
                  f"{written.name if written else 'indisponible'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
