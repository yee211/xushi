import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv
from psycopg import sql

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

database_name = "class_schedule"
admin_url = os.environ["POSTGRES_ADMIN_URL"]

with psycopg.connect(admin_url, autocommit=True) as connection:
    exists = connection.execute(
        "SELECT 1 FROM pg_database WHERE datname = %s", (database_name,)
    ).fetchone()
    if not exists:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))

print(f"Database {database_name} is ready.")
