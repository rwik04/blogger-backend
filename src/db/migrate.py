"""Minimal migration runner: applies pending `.sql` files from
`db/migrations/`, in filename order, tracked in a `schema_migrations` table
so each file only ever runs once. No dependency on Alembic or similar —
matches the rest of this repo's "small and explicit" approach to
infrastructure.

Usage:
    uv run python -m db.migrate
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from sqlalchemy import text

from db.engine import get_engine

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

_ENSURE_TRACKING_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename    text PRIMARY KEY,
    applied_at  timestamptz NOT NULL DEFAULT now()
);
"""


def run_migrations() -> list[str]:
    """Applies every not-yet-applied `.sql` file in `db/migrations/`. Returns
    the filenames actually applied (empty list if everything was already
    up to date)."""
    engine = get_engine()

    with engine.begin() as conn:
        conn.execute(text(_ENSURE_TRACKING_TABLE))
        applied = {row[0] for row in conn.execute(text("SELECT filename FROM schema_migrations"))}

    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not migration_files:
        logger.info("No migration files found in %s", MIGRATIONS_DIR)
        return []

    newly_applied: list[str] = []
    for path in migration_files:
        if path.name in applied:
            logger.info("Skipping already-applied migration: %s", path.name)
            continue

        logger.info("Applying migration: %s", path.name)
        sql = path.read_text()

        # Migration files contain multiple `;`-separated statements — run via
        # a raw psycopg2 cursor (SQLAlchemy's `text()` assumes one statement).
        raw_conn = engine.raw_connection()
        try:
            cursor = raw_conn.cursor()
            try:
                cursor.execute(sql)
            finally:
                cursor.close()
            raw_conn.commit()
        except Exception:
            raw_conn.rollback()
            logger.exception("Migration failed: %s", path.name)
            raise
        finally:
            raw_conn.close()

        with engine.begin() as conn:
            conn.execute(text("INSERT INTO schema_migrations (filename) VALUES (:filename)"), {"filename": path.name})

        logger.info("Applied migration: %s", path.name)
        newly_applied.append(path.name)

    return newly_applied


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        applied = run_migrations()
    except Exception:
        logger.exception("Migration run failed")
        return 1

    if applied:
        logger.info("Applied %d migration(s): %s", len(applied), ", ".join(applied))
    else:
        logger.info("Database already up to date.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
