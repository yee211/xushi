"""Alembic 迁移环境：连接串取自 DATABASE_URL，使用 psycopg3 方言。"""
import os

from alembic import context
from sqlalchemy import create_engine, pool

config = context.config

url = os.getenv("DATABASE_URL", "postgresql://postgres@127.0.0.1:5432/xushi_schedule")
if url.startswith("postgresql://"):
    url = "postgresql+psycopg://" + url[len("postgresql://"):]
elif url.startswith("postgres://"):
    url = "postgresql+psycopg://" + url[len("postgres://"):]


def run_migrations_offline() -> None:
    context.configure(url=url, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(url, poolclass=pool.NullPool, connect_args={"connect_timeout": 10})
    with engine.connect() as connection:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
