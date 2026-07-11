#!/usr/bin/env python3
"""Shelfmark sort keys for natural (numeric-aware) ordering.

The browse APIs order manuscripts by (collection, sort_key). Because the sort
only ever compares shelfmarks within one collection — where the non-numeric
scaffolding ("Harley MS", "Cosin MS V.v.") is consistent — the key is simply
the shelfmark with every digit run zero-padded to a fixed width. Roman
numerals are left alone: letters like C, D, and M are genuinely part of many
shelfmarks, and the BL's own catalogue tolerates alphabetic Roman ordering.

Run as a script to backfill the sort_key column for all manuscripts:

    python3 scripts/sort_keys.py

Idempotent — recomputes every row and only writes the ones that changed.
New importers don't need to set sort_key themselves: deploy_production.sh
runs this backfill before every export, and the APIs fall back to raw
shelfmark ordering (COALESCE) for any row not yet backfilled.
"""

import re
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / 'database' / 'compilatio.db'

PAD_WIDTH = 6


def compute_sort_key(shelfmark: str) -> str:
    """Zero-pad every digit run in a shelfmark to PAD_WIDTH characters."""
    return re.sub(r'\d+', lambda m: m.group(0).zfill(PAD_WIDTH), shelfmark)


def backfill(conn: sqlite3.Connection) -> int:
    """Recompute sort_key for every manuscript. Returns number of rows updated."""
    cursor = conn.cursor()
    cursor.execute("SELECT id, shelfmark, sort_key FROM manuscripts")
    updates = []
    for ms_id, shelfmark, current in cursor.fetchall():
        key = compute_sort_key(shelfmark)
        if len(key) > 255:
            print(f"[!] sort_key exceeds 255 chars for manuscript {ms_id}: {shelfmark!r}",
                  file=sys.stderr)
            sys.exit(1)
        if key != current:
            updates.append((key, ms_id))

    cursor.executemany("UPDATE manuscripts SET sort_key = ? WHERE id = ?", updates)
    conn.commit()
    return len(updates)


def main():
    if not DB_PATH.exists():
        print(f"[!] Database not found: {DB_PATH}", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    try:
        updated = backfill(conn)
    finally:
        conn.close()
    print(f"[✓] sort_key backfill complete: {updated} rows updated")


if __name__ == '__main__':
    main()
