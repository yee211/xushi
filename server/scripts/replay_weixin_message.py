"""Explicitly replay one quarantined iLink message without rewinding the bot cursor."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.channels.weixin.client import ILinkClient  # noqa: E402
from app.channels.weixin.store import (  # noqa: E402
    load_accounts,
    prepare_replay,
    restore_dead_letter,
)
from app.channels.weixin.worker import process_message  # noqa: E402
from app.db import connect  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", required=True)
    parser.add_argument("--message", required=True)
    args = parser.parse_args()
    with connect() as db:
        credentials = next((c for c, _, _ in load_accounts(db) if c.account_id == args.account), None)
        if credentials is None:
            parser.error("Account is not active or credentials are unreadable")
        message = prepare_replay(db, args.account, args.message)
    client = ILinkClient(credentials)
    try:
        if not process_message(client, message):
            with connect() as db:
                restore_dead_letter(db, args.account, args.message)
            raise SystemExit("Replay failed; message restored to dead letter, inspect the error before retrying")
        print("Replay completed")
    finally:
        client.close()


if __name__ == "__main__":
    main()
