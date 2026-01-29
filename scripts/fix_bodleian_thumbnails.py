#!/usr/bin/env python3
"""
Fix Bodleian manuscript thumbnails in Compilatio database.

The Bodleian importer incorrectly used the manifest UUID as the image ID,
but Bodleian's IIIF server returns a placeholder for non-existent image IDs.
This script fetches the correct thumbnail URL from each manifest's thumbnail field.

Usage:
    python scripts/fix_bodleian_thumbnails.py              # Dry-run
    python scripts/fix_bodleian_thumbnails.py --execute    # Apply changes
    python scripts/fix_bodleian_thumbnails.py --limit 10   # Test with 10 manuscripts
"""

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path
from urllib.request import urlopen, Request

PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = PROJECT_ROOT / "database" / "compilatio.db"

REQUEST_DELAY = 0.5  # seconds between requests


def fetch_thumbnail_from_manifest(manifest_url: str) -> str | None:
    """
    Fetch the thumbnail URL from a Bodleian IIIF manifest.

    Bodleian manifests use IIIF Presentation 2.x format with thumbnail as an object.
    """
    try:
        req = Request(
            manifest_url,
            headers={"User-Agent": "Compilatio/1.0 (thumbnail fix script)"}
        )
        with urlopen(req, timeout=30) as response:
            manifest = json.loads(response.read().decode('utf-8'))

        # IIIF Presentation 2.x format: thumbnail is an object with @id
        thumb = manifest.get("thumbnail")
        if isinstance(thumb, dict):
            return thumb.get("@id")
        # IIIF Presentation 3.x format: thumbnail is an array
        elif isinstance(thumb, list) and thumb:
            first = thumb[0]
            return first.get("@id") or first.get("id")

        return None
    except Exception as e:
        print(f"  Error fetching {manifest_url}: {e}")
        return None


def main():
    parser = argparse.ArgumentParser(
        description="Fix Bodleian thumbnail URLs by fetching from IIIF manifests"
    )
    parser.add_argument(
        '--execute',
        action='store_true',
        help='Actually update the database (default is dry-run)'
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=None,
        help='Limit number of manuscripts to process (for testing)'
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

    # Get all Bodleian manuscripts with manifests
    query = """
        SELECT m.id, m.shelfmark, m.iiif_manifest_url, m.thumbnail_url
        FROM manuscripts m
        JOIN repositories r ON m.repository_id = r.id
        WHERE r.short_name = 'Bodleian'
          AND m.iiif_manifest_url IS NOT NULL
    """
    if args.limit:
        query += f" LIMIT {args.limit}"

    cursor.execute(query)
    manuscripts = cursor.fetchall()

    print(f"Found {len(manuscripts)} Bodleian manuscripts to process")
    if not args.execute:
        print("DRY RUN - no changes will be made\n")

    updated = 0
    failed = 0
    unchanged = 0

    for i, ms in enumerate(manuscripts):
        print(f"[{i+1}/{len(manuscripts)}] {ms['shelfmark']}")

        thumbnail_url = fetch_thumbnail_from_manifest(ms['iiif_manifest_url'])

        if thumbnail_url:
            if thumbnail_url == ms['thumbnail_url']:
                print(f"  -> Already correct")
                unchanged += 1
            else:
                print(f"  -> {thumbnail_url[:70]}...")
                if args.execute:
                    cursor.execute(
                        "UPDATE manuscripts SET thumbnail_url = ? WHERE id = ?",
                        (thumbnail_url, ms['id'])
                    )
                updated += 1
        else:
            print("  -> No thumbnail found in manifest")
            failed += 1

        time.sleep(REQUEST_DELAY)

    if args.execute:
        conn.commit()
        print(f"\n{'='*60}")
        print(f"COMPLETE: Updated {updated}, failed {failed}, unchanged {unchanged}")
    else:
        print(f"\n{'='*60}")
        print(f"DRY RUN: Would update {updated}, would fail {failed}, already correct {unchanged}")
        print("Run with --execute to apply changes")

    conn.close()


if __name__ == '__main__':
    main()
