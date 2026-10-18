"""Nightly SQLite backup (ARCHITECTURE §7): online-safe copy via the sqlite3 backup API, keeps the newest N.

Usage (inside the app container):  python scripts/backup.py [--keep 14]
Cron on the host:  0 3 * * *  docker compose exec -T app python scripts/backup.py
"""

import argparse
import sqlite3
from datetime import UTC, datetime

from app.core.config import db_path_from_env


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep", type=int, default=14)
    args = parser.parse_args()

    db_path = db_path_from_env()
    backup_dir = db_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"dealscour-{datetime.now(UTC):%Y%m%d-%H%M%S}.db"

    with sqlite3.connect(db_path) as src, sqlite3.connect(target) as dst:
        src.backup(dst)

    backups = sorted(backup_dir.glob("dealscour-*.db"))
    for old in backups[: max(0, len(backups) - args.keep)]:
        old.unlink()
    print(f"backup written: {target}")


if __name__ == "__main__":
    main()
