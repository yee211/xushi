"""pg_dump 备份 / pg_restore 恢复。

用法：
    python scripts/backup_database.py backup backups/wx_$(date +%F).dump
    python scripts/backup_database.py restore backups/wx_2026-09-12.dump
依赖 DATABASE_URL 环境变量（自动读取 server/.env）。
"""
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
URL = os.getenv("DATABASE_URL", "")


def target(url: str) -> dict:
    parsed = urlparse(url)
    return {
        "host": parsed.hostname or "127.0.0.1",
        "port": str(parsed.port or 5432),
        "user": parsed.username or "postgres",
        "db": parsed.path.lstrip("/"),
        "password": parsed.password or "",
    }


def main() -> None:
    if len(sys.argv) != 3 or sys.argv[1] not in {"backup", "restore"}:
        print(__doc__)
        sys.exit(1)
    action, file = sys.argv[1], sys.argv[2]
    info = target(URL)
    env = {**os.environ, "PGPASSWORD": info["password"]}
    common = ["-h", info["host"], "-p", info["port"], "-U", info["user"], "-d", info["db"]]
    if action == "backup":
        Path(file).parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["pg_dump", "-Fc", *common, "-f", file], env=env, check=True)
        print(f"已备份到 {file}")
    else:
        subprocess.run(["pg_restore", "-Fc", "-c", *common, file], env=env, check=True)
        print(f"已从 {file} 恢复")


if __name__ == "__main__":
    main()
