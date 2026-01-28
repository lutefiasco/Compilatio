#!/usr/bin/env python3
"""
Fix British Library manuscript thumbnails in Compilatio database.

Fetches thumbnail URLs from IIIF manifests and updates the database.

Usage:
    python scripts/fix_bl_thumbnails.py          # Dry-run
    python scripts/fix_bl_thumbnails.py --execute
"""

import argparse
import sqlite3
import sys
import time
from pathlib import Path
from urllib.request import urlopen, Request
import json

PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = PROJECT_ROOT / "database" / "compilatio.db"

REQUEST_DELAY = 0.5  # seconds between requests


def fetch_thumbnail_from_manifest(manifest_url: str) -> str | None:
    """
    Fetch the thumbnail URL from a IIIF manifest.
    """
    try:
        req = Request(
            manifest_url,
            headers={"User-Agent": "Compilatio/1.0 (thumbnail update script)"}
        )
        with urlopen(req, timeout=30) as response:
            manifest = json.loads(response.read().decode('utf-8'))

        # IIIF Presentation 3.0 format
        thumbnails = manifest.get("thumbnail", [])
        if thumbnails and isinstance(thumbnails, list) and len(thumbnails) > 0:
            thumb = thumbnails[0]
            if isinstance(thumb, dict) and "id" in thumb:
                return thumb["id"]

        return None
    except Exception as e:
        print(f"  Error fetching {manifest_url}: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(
        description="Fix British Library thumbnail URLs"
    )
    parser.add_argument(
        '--execute',
        action='store_true',
        help='Actually update the database (default is dry-run)'
    )
    parser.add_argument(
        '--db',
        type=Path,
        default=DB_PATH,
        help=f'Path to database (default: {DB_PATH})'
    )
    args = parser.parse_args()

    if not args.db.exists():
        print(f"Database not found: {args.db}")
        sys.exit(1)

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Find BL manuscripts with manifest but no thumbnail
    cursor.execute("""
        SELECT m.id, m.shelfmark, m.iiif_manifest_url
        FROM manuscripts m
        JOIN repositories r ON m.repository_id = r.id
        WHERE r.short_name = 'BL'
          AND m.iiif_manifest_url IS NOT NULL
          AND (m.thumbnail_url IS NULL OR m.thumbnail_url = '')
    """)

    manuscripts = cursor.fetchall()
    print(f"Found {len(manuscripts)} BL manuscripts needing thumbnails")

    if not manuscripts:
        print("Nothing to do!")
        conn.close()
        return

    updated = 0
    failed = 0

    for ms in manuscripts:
        print(f"[{updated + failed + 1}/{len(manuscripts)}] {ms['shelfmark']}")

        thumbnail_url = fetch_thumbnail_from_manifest(ms['iiif_manifest_url'])

        if thumbnail_url:
            print(f"  -> {thumbnail_url[:60]}...")
            if args.execute:
                cursor.execute(
                    "UPDATE manuscripts SET thumbnail_url = ? WHERE id = ?",
                    (thumbnail_url, ms['id'])
                )
            updated += 1
        else:
            print("  -> No thumbnail found")
            failed += 1

        time.sleep(REQUEST_DELAY)

    if args.execute:
        conn.commit()
        print(f"\nUpdated {updated} manuscripts, {failed} failed")
    else:
        print(f"\nDRY RUN: Would update {updated} manuscripts, {failed} would fail")
        print("Run with --execute to apply changes")

    conn.close()


if __name__ == '__main__':
    main()
