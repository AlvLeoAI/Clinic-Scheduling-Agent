"""Purge stored chat text (items, hashes, replies) of sessions expired beyond retention.

Dry run by default; --apply writes. CHAT_RETENTION_DAYS sets the retention period.
"""

import argparse
import json

from sqlalchemy.orm import Session

from app.core.clock import utc_now
from app.core.config import Settings
from app.db.session import build_engine
from app.services.retention import purge_expired_chat


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Delete; without it, only count.")
    parser.add_argument(
        "--retention-days", type=int, help="Override CHAT_RETENTION_DAYS for this run."
    )
    args = parser.parse_args(argv)
    settings = Settings()
    days = args.retention_days if args.retention_days is not None else settings.chat_retention_days
    if days < 1:
        parser.error("--retention-days must be at least 1.")
    engine = build_engine(settings)
    try:
        with Session(engine) as db, db.begin():
            result = purge_expired_chat(db, now=utc_now(), retention_days=days, apply=args.apply)
    finally:
        engine.dispose()
    print(
        json.dumps(
            {"mode": "apply" if args.apply else "dry-run", "retention_days": days}
            | result.as_dict()
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
