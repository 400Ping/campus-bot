"""Backfill note summaries for all users.

Usage:
    python -m services.backfill_summaries
    # 或直接
    python services/backfill_summaries.py
"""
import sys, pathlib

# allow running as script
if __package__ is None:
    sys.path.append(str(pathlib.Path(__file__).resolve().parent.parent))

from services.notes_service import ensure_summaries_for_all  # type: ignore

def main():
    updated = ensure_summaries_for_all(limit_per_user=500)
    print(f"Backfill done. Updated {updated} summaries.")

if __name__ == "__main__":
    main()
