"""Explicit, one-shot migration runner; never invoked by API startup."""
import os
from pathlib import Path
from psycopg import connect


def main() -> None:
    migrations = sorted((Path(__file__).parent.parent / "storage" / "migrations").glob("*.sql"))
    with connect(os.environ["DATABASE_URL"]) as connection, connection.cursor() as cursor:
        cursor.execute("CREATE SCHEMA IF NOT EXISTS audit")
        cursor.execute("CREATE TABLE IF NOT EXISTS audit.schema_migrations (version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())")
        for migration in migrations:
            cursor.execute("SELECT 1 FROM audit.schema_migrations WHERE version = %s", (migration.name,))
            if cursor.fetchone() is None:
                cursor.execute(migration.read_text())
                cursor.execute("INSERT INTO audit.schema_migrations (version) VALUES (%s)", (migration.name,))


if __name__ == "__main__":
    main()
