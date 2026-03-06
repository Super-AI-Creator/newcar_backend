import argparse
import sys

from app.core.database import SessionLocal
from app.services.sheets_sync import sync_offers, sync_scores


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--offers", action="store_true")
    parser.add_argument("--scores", action="store_true")
    args = parser.parse_args()

    if not args.offers and not args.scores:
        print("Nothing to sync. Use --offers and/or --scores")
        return 1

    db = SessionLocal()
    try:
        if args.offers:
            count, row_hash = sync_offers(db)
            print(f"Synced offers: {count} rows (hash={row_hash})")
        if args.scores:
            count, row_hash = sync_scores(db)
            print(f"Synced scores: {count} rows (hash={row_hash})")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
