import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from sqlmodel import Session

from app.core.db import get_engine
from app.domain.catalog_import import CatalogImportReport, import_catalog_csv


def run_import_cli(argv: Sequence[str] | None = None) -> CatalogImportReport:
    parser = argparse.ArgumentParser(
        description="Import seed catalog CSV into DealScour household catalog."
    )
    parser.add_argument("csv_path", type=Path, help="Path to seed catalog CSV file")
    parser.add_argument(
        "--household",
        type=int,
        default=1,
        help="Household ID to import catalog products into (default: 1)",
    )
    args = parser.parse_args(argv)

    engine = get_engine()
    with Session(engine) as session:
        report = import_catalog_csv(
            session=session,
            household_id=args.household,
            csv_path=args.csv_path,
        )
    print(report.model_dump_json())
    return report


if __name__ == "__main__":
    run_import_cli(sys.argv[1:])
