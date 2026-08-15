"""Bounded, resumable historical-data backfill for local research.

The database queues are durable, so stopping this process is safe: the next
run resumes pending work.  It deliberately stops on a provider quota response
instead of retrying aggressively.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from time import sleep


# Keep this standalone, resumable tool runnable with the bundled local
# dependencies, just like scripts/run_local_server.py.
ROOT = Path(__file__).resolve().parents[1]
LOCAL_PACKAGES = ROOT / ".local-packages"
if LOCAL_PACKAGES.exists():
    sys.path.insert(0, str(LOCAL_PACKAGES))
sys.path.insert(0, r"C:\codex_runtime\taiwan_stock_packages")
sys.path.insert(0, str(ROOT))

from app.config import settings
from app.database import Database
from app.fundamental_batch import run_fundamental_batch, run_price_history_batch


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batches", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--pause-seconds", type=float, default=3)
    args = parser.parse_args()
    database = Database(settings.database_path)
    database.initialize()
    for number in range(max(args.batches, 0)):
        fundamentals = run_fundamental_batch(
            database, target_limit=None, batch_size=args.batch_size, years=5,
            retry_failed=False,
        )
        prices = run_price_history_batch(
            database, target_limit=None, batch_size=args.batch_size, years=3,
            retry_failed=False,
        )
        print(json.dumps({"batch": number + 1, "fundamentals": fundamentals,
                          "prices": prices}, ensure_ascii=False), flush=True)
        if fundamentals["quota_paused"]:
            break
        if number + 1 < args.batches:
            sleep(max(args.pause_seconds, 0))


if __name__ == "__main__":
    main()
