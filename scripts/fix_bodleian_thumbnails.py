#!/usr/bin/env python3
"""
Fix Bodleian manuscript thumbnails in Compilatio database.

The Bodleian importer incorrectly used the manifest UUID as the image ID,
but Bodleian's IIIF server returns a placeholder for non-existent image IDs.
This script fetches the correct thumbnail URL from each manifest's thumbnail field.

Features:
- Batch processing with commits every N manuscripts (default 25)
- Progress tracking file for resume capability
- Automatic resume from where it left off
- Retry logic for failed requests

Usage:
    python scripts/fix_bodleian_thumbnails.py              # Dry-run
    python scripts/fix_bodleian_thumbnails.py --execute    # Apply changes
    python scripts/fix_bodleian_thumbnails.py --limit 10   # Test with 10 manuscripts
    python scripts/fix_bodleian_thumbnails.py --reset      # Clear progress and start fresh
    python scripts/fix_bodleian_thumbnails.py --status     # Show current progress
"""

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = PROJECT_ROOT / "database" / "compilatio.db"
PROGRESS_FILE = PROJECT_ROOT / "scripts" / ".bodleian_thumbnail_progress.json"

REQUEST_DELAY = 0.5  # seconds between requests
BATCH_SIZE = 10  # commit and save progress every N manuscripts (lower = more frequent saves)
MAX_RETRIES = 3  # retry failed requests
REQUEST_TIMEOUT = 60  # seconds to wait for each request (Bodleian can be slow)


def load_progress() -> dict:
    """Load progress from tracking file."""
    if PROGRESS_FILE.exists():
        try:
            with open(PROGRESS_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"processed_ids": [], "updated": 0, "failed": 0, "unchanged": 0}


def save_progress(progress: dict):
    """Save progress to tracking file."""
    with open(PROGRESS_FILE, 'w') as f:
        json.dump(progress, f, indent=2)


def clear_progress():
    """Remove progress file to start fresh."""
    if PROGRESS_FILE.exists():
        PROGRESS_FILE.unlink()
        print(f"Progress file removed: {PROGRESS_FILE}")


def fetch_thumbnail_from_manifest(manifest_url: str, retries: int = MAX_RETRIES) -> str | None:
    """
    Fetch the thumbnail URL from a Bodleian IIIF manifest.

    Bodleian manifests use IIIF Presentation 2.x format with thumbnail as an object.
    Includes retry logic for transient failures.
    """
    last_error = None
    for attempt in range(retries):
        try:
            req = Request(
                manifest_url,
                headers={"User-Agent": "Compilatio/1.0 (thumbnail fix script)"}
            )
            print(f"  Fetching manifest...", end=" ", flush=True)
            with urlopen(req, timeout=REQUEST_TIMEOUT) as response:
                manifest = json.loads(response.read().decode('utf-8'))
            print("OK", flush=True)

            # IIIF Presentation 2.x format: thumbnail is an object with @id
            thumb = manifest.get("thumbnail")
            if isinstance(thumb, dict):
                return thumb.get("@id")
            # IIIF Presentation 3.x format: thumbnail is an array
            elif isinstance(thumb, list) and thumb:
                first = thumb[0]
                return first.get("@id") or first.get("id")

            return None
        except (URLError, HTTPError, TimeoutError) as e:
            last_error = e
            if attempt < retries - 1:
                wait = (attempt + 1) * 2  # exponential backoff: 2s, 4s, 6s
                print(f"  Retry {attempt + 1}/{retries - 1} after {wait}s...")
                time.sleep(wait)
        except Exception as e:
            print(f"  Error fetching {manifest_url}: {e}")
            return None

    print(f"  Failed after {retries} attempts: {last_error}")
    return None


def show_status():
    """Show current progress status."""
    progress = load_progress()
    processed = len(progress.get("processed_ids", []))
    print(f"Progress file: {PROGRESS_FILE}")
    print(f"Processed: {processed} manuscripts")
    print(f"  Updated: {progress.get('updated', 0)}")
    print(f"  Failed: {progress.get('failed', 0)}")
    print(f"  Unchanged: {progress.get('unchanged', 0)}")


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
        '--batch-size',
        type=int,
        default=BATCH_SIZE,
        help=f'Commit and save progress every N manuscripts (default: {BATCH_SIZE})'
    )
    parser.add_argument(
        '--reset',
        action='store_true',
        help='Clear progress file and start fresh'
    )
    parser.add_argument(
        '--status',
        action='store_true',
        help='Show current progress and exit'
    )
    parser.add_argument(
        '--db',
        type=Path,
        default=DB_PATH,
        help=f'Path to database (default: {DB_PATH})'
    )
    args = parser.parse_args()

    if args.status:
        show_status()
        return

    if args.reset:
        clear_progress()
        if not args.execute:
            return

    if not args.db.exists():
        print(f"Database not found: {args.db}")
        sys.exit(1)

    # Load existing progress
    progress = load_progress()
    processed_ids = set(progress.get("processed_ids", []))

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
        ORDER BY m.id
    """
    cursor.execute(query)
    all_manuscripts = cursor.fetchall()

    # Filter out already processed manuscripts
    manuscripts = [ms for ms in all_manuscripts if ms['id'] not in processed_ids]

    if args.limit:
        manuscripts = manuscripts[:args.limit]

    total = len(all_manuscripts)
    already_done = len(processed_ids)
    to_process = len(manuscripts)

    print(f"Total Bodleian manuscripts: {total}")
    print(f"Already processed: {already_done}")
    print(f"Remaining to process: {to_process}")

    if to_process == 0:
        print("\nAll manuscripts have been processed!")
        print("Use --reset to start fresh if needed.")
        conn.close()
        return

    if not args.execute:
        print("\nDRY RUN - no changes will be made")
        print("(Progress will still be tracked for resume capability)\n")

    updated = progress.get("updated", 0)
    failed = progress.get("failed", 0)
    unchanged = progress.get("unchanged", 0)
    batch_count = 0

    try:
        for i, ms in enumerate(manuscripts):
            current = already_done + i + 1
            print(f"[{current}/{total}] {ms['shelfmark']}")

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

            # Track this manuscript as processed
            processed_ids.add(ms['id'])
            batch_count += 1

            # Save progress and commit every batch_size manuscripts
            if batch_count >= args.batch_size:
                if args.execute:
                    conn.commit()

                # Save progress
                progress = {
                    "processed_ids": list(processed_ids),
                    "updated": updated,
                    "failed": failed,
                    "unchanged": unchanged
                }
                save_progress(progress)

                timestamp = time.strftime("%H:%M:%S")
                print(f"  [{timestamp}] Batch committed - {updated} updated, {failed} failed, {unchanged} unchanged")
                batch_count = 0

            time.sleep(REQUEST_DELAY)

    except KeyboardInterrupt:
        print("\n\nInterrupted! Saving progress...")
    finally:
        # Final commit and save
        if args.execute and batch_count > 0:
            conn.commit()

        progress = {
            "processed_ids": list(processed_ids),
            "updated": updated,
            "failed": failed,
            "unchanged": unchanged
        }
        save_progress(progress)

        print(f"\n{'='*60}")
        if args.execute:
            print(f"PROGRESS SAVED: Updated {updated}, failed {failed}, unchanged {unchanged}")
        else:
            print(f"DRY RUN: Would update {updated}, would fail {failed}, already correct {unchanged}")
            print("Run with --execute to apply changes")

        print(f"\nProgress saved to: {PROGRESS_FILE}")
        print(f"Run again to resume from where you left off.")

    conn.close()


if __name__ == '__main__':
    main()
