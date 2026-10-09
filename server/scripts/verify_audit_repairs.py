"""Run migration round trips and all tests against a disposable local schema."""
import os
import subprocess
import sys
import uuid
from pathlib import Path

import psycopg
from psycopg import sql

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db import DATABASE_URL  # noqa: E402


def main():
    name = 'xushi_audit_' + uuid.uuid4().hex
    env = dict(os.environ, DATABASE_URL=DATABASE_URL, APP_ENV='test',
               TEST_ACADEMIC_QUEUE_DB='1', TEST_ACADEMIC_DIRECTORY_DB='1',
               AGENT_REDIS_URL='', REDIS_URL='', PYTHONIOENCODING='utf-8')
    root = Path(__file__).resolve().parents[1]
    with psycopg.connect(DATABASE_URL, autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(name)))
        env['DATABASE_URL'] = DATABASE_URL
        env['PGOPTIONS'] = '-c search_path=' + name
        try:
            def run(*args):
                subprocess.run([sys.executable, *args], cwd=root, env=env, check=True)
            print('Checking fresh migration upgrade', flush=True)
            run('-m', 'alembic', 'upgrade', 'head')
            run('-m', 'alembic', 'upgrade', 'head')
            run('-m', 'alembic', 'downgrade', '0001_baseline')
            run('-m', 'alembic', 'upgrade', 'head')
            run('-c', 'from app.db import init_db; init_db(); init_db()')
            # Validate init_db independently, before any Alembic migration exists.
            initial = name + '_init'
            admin.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(initial)))
            try:
                env['PGOPTIONS'] = '-c search_path=' + initial
                run('-c', "from app.db import init_db,connect\ninit_db(); init_db()\n"
                    "with connect() as db:\n"
                    "    assert db.execute(\"SELECT to_regclass('daily_push_logs') AS t\").fetchone()['t']\n"
                    "    db.execute(\"SELECT context_token FROM user_identities LIMIT 0\")\n")
                run('-m', 'alembic', 'upgrade', 'head')
                run('-m', 'alembic', 'downgrade', '0001_baseline')
                run('-m', 'alembic', 'upgrade', 'head')
            finally:
                admin.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(initial)))
                env['PGOPTIONS'] = '-c search_path=' + name
            run('-m', 'pytest', 'tests', '-q', '-p', 'no:cacheprovider', '--tb=short')
        finally:
            admin.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(name)))
            print('Disposable schema removed', flush=True)


if __name__ == '__main__':
    main()
