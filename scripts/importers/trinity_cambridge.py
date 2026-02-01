#!/usr/bin/env python3
"""
Trinity College Cambridge (Wren Library) Manuscript Import Script for Compilatio.

Imports digitized medieval manuscripts from the James Catalogue of Western Manuscripts
(mss-cat.trin.cam.ac.uk). Uses shelfmark enumeration from known ranges, then fetches
IIIF manifests for each valid shelfmark.

Two-phase process with checkpoint resumability:
  Phase 1 (Enumeration): Generate candidate shelfmarks from known ranges
  Phase 2 (Import): Test each shelfmark, fetch IIIF manifests, insert to database

Collection: ~850 digitized medieval manuscripts from Trinity College Cambridge
Source: James Catalogue online (M.R. James catalog, 1900-1904)
IIIF: Presentation API v2 manifests

No special requirements - uses standard library only.

Usage:
    python scripts/importers/trinity_cambridge.py                  # Dry-run
    python scripts/importers/trinity_cambridge.py --execute        # Import
    python scripts/importers/trinity_cambridge.py --resume --execute # Resume interrupted
    python scripts/importers/trinity_cambridge.py --test           # First 10 only
    python scripts/importers/trinity_cambridge.py --verbose        # Detailed logging

Note: Full import takes ~30 minutes. Use --resume to continue if interrupted.
"""

import argparse
import json
import logging
import re
import sqlite3
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
DB_PATH = PROJECT_ROOT / "database" / "compilatio.db"
CACHE_DIR = PROJECT_ROOT / "scripts" / "importers" / "cache"
PROGRESS_FILE = CACHE_DIR / "trinity_progress.json"

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================

TRINITY_BASE_URL = "https://mss-cat.trin.cam.ac.uk"
MANIFEST_BASE = f"{TRINITY_BASE_URL}/manuscripts"
VIEWER_BASE = f"{TRINITY_BASE_URL}/manuscripts/uv/view.php"

# Repository metadata
REPO_NAME = "Trinity College Cambridge"
REPO_SHORT = "TCC"
REPO_LOGO_URL = "https://www.trin.cam.ac.uk/assets/images/logo.png"
CATALOGUE_URL = TRINITY_BASE_URL

# Rate limiting
REQUEST_DELAY = 0.5  # seconds between manifest requests

# Shelfmark pattern: B.x.y, O.x.y, R.x.y, etc. (with optional suffix like 'A')
SHELFMARK_PATTERN = re.compile(r'\b([A-Z]\.\d+\.\d+[A-Z]?)\b')

# =============================================================================
# Known Shelfmark Ranges
# =============================================================================
# Format: (prefix, start, end, extras)
# - prefix: e.g., "B.1" for B.1.x shelfmarks
# - start: first number in range
# - end: last number in range
# - extras: list of additional shelfmarks with suffixes (e.g., ["30A"])

SHELFMARK_RANGES = [
    # B series
    ("B.1", 1, 46, ["30A"]),
    ("B.2", 1, 36, []),
    ("B.3", 1, 35, []),
    ("B.4", 1, 32, []),
    ("B.5", 1, 28, []),
    # Note: B.6 not listed
    ("B.7", 1, 7, []),
    ("B.8", 1, 12, []),
    ("B.9", 1, 15, []),
    ("B.10", 1, 27, []),
    ("B.11", 1, 34, []),
    # Note: B.12 not listed
    ("B.13", 1, 30, []),
    ("B.14", 1, 55, []),
    ("B.15", 1, 42, []),
    ("B.16", 1, 47, []),
    ("B.17", 1, 42, []),
    # F series
    ("F.12", 40, 44, []),
    # O series
    ("O.1", 1, 79, []),
    ("O.2", 1, 68, []),
    ("O.3", 1, 63, []),
    ("O.4", 1, 52, []),
    ("O.5", 2, 54, []),  # starts at 2
    # Note: O.6 not listed
    ("O.7", 1, 47, []),
    ("O.8", 1, 37, []),
    ("O.9", 1, 40, []),
    ("O.10", 2, 34, []),  # starts at 2
    ("O.11", 2, 19, []),  # starts at 2
    # R series
    ("R.1", 2, 92, []),   # starts at 2
    ("R.2", 4, 98, []),   # starts at 4
    ("R.3", 1, 68, []),
    ("R.4", 1, 52, []),
    ("R.5", 3, 46, []),   # starts at 3
    # Note: R.6 not listed
    ("R.7", 1, 51, []),
    ("R.8", 3, 35, []),   # starts at 3
    ("R.9", 8, 39, []),   # starts at 8
    ("R.10", 5, 15, []),  # starts at 5
    ("R.11", 1, 2, []),
    # Note: R.12 not listed
    ("R.13", 8, 74, []),  # starts at 8
    ("R.14", 1, 16, []),
    ("R.15", 1, 55, []),
    ("R.16", 2, 40, []),  # starts at 2
    ("R.17", 1, 23, []),
]


def generate_shelfmarks() -> list[str]:
    """
    Generate all candidate shelfmarks from known ranges.

    Returns:
        List of shelfmarks to test (e.g., ["B.1.1", "B.1.2", ..., "B.1.30A", ...])
    """
    shelfmarks = []

    for prefix, start, end, extras in SHELFMARK_RANGES:
        # Generate numeric range
        for i in range(start, end + 1):
            shelfmarks.append(f"{prefix}.{i}")

        # Add any extras with suffixes
        for extra in extras:
            shelfmarks.append(f"{prefix}.{extra}")

    # Sort naturally (B.1.1, B.1.2, ... B.1.10, B.1.11, ...)
    def sort_key(s):
        parts = re.split(r'[.]', s)
        result = []
        for p in parts:
            # Extract numeric part and suffix
            match = re.match(r'(\d+)([A-Z]?)', p)
            if match:
                result.append((int(match.group(1)), match.group(2)))
            else:
                result.append((0, p))
        return result

    shelfmarks.sort(key=sort_key)
    return shelfmarks



# =============================================================================
# Progress/Checkpoint Management
# =============================================================================

def load_progress(progress_path: Path) -> dict:
    """Load progress from checkpoint file."""
    if not progress_path.exists():
        return {
            "last_updated": None,
            "total_discovered": 0,
            "completed_shelfmarks": [],
            "failed_shelfmarks": [],
            "phase": "discovery",
        }
    with open(progress_path) as f:
        return json.load(f)


def save_progress(progress: dict, progress_path: Path):
    """Save progress to checkpoint file."""
    progress["last_updated"] = datetime.now(timezone.utc).isoformat()
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    with open(progress_path, "w") as f:
        json.dump(progress, f, indent=2)


def mark_completed(progress: dict, shelfmark: str, progress_path: Path):
    """Mark a shelfmark as completed and save checkpoint."""
    if shelfmark not in progress["completed_shelfmarks"]:
        progress["completed_shelfmarks"].append(shelfmark)
    if shelfmark in progress["failed_shelfmarks"]:
        progress["failed_shelfmarks"].remove(shelfmark)
    save_progress(progress, progress_path)


def mark_failed(progress: dict, shelfmark: str, progress_path: Path):
    """Mark a shelfmark as failed and save checkpoint."""
    if shelfmark not in progress["failed_shelfmarks"]:
        progress["failed_shelfmarks"].append(shelfmark)
    save_progress(progress, progress_path)


# =============================================================================
# IIIF Manifest Fetching
# =============================================================================

USER_AGENT = "Compilatio/1.0 (Academic manuscript research; IIIF aggregator)"


def fetch_manifest(shelfmark: str) -> Optional[dict]:
    """
    Fetch IIIF manifest for a shelfmark.

    Args:
        shelfmark: Manuscript shelfmark (e.g., "B.1.1")

    Returns:
        Parsed manifest dict or None on error (including 404)
    """
    url = f"{MANIFEST_BASE}/{shelfmark}.json"

    try:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status != 200:
                logger.debug(f"HTTP {response.status} for {shelfmark}")
                return None

            data = response.read().decode('utf-8')
            return json.loads(data)

    except urllib.error.HTTPError as e:
        if e.code == 404:
            logger.debug(f"Not found: {shelfmark}")
        else:
            logger.warning(f"HTTP {e.code} for {shelfmark}")
        return None

    except urllib.error.URLError as e:
        logger.error(f"URL error for {shelfmark}: {e}")
        return None

    except json.JSONDecodeError:
        logger.error(f"Invalid JSON for {shelfmark}")
        return None

    except Exception as e:
        logger.error(f"Error fetching manifest for {shelfmark}: {e}")
        return None


# =============================================================================
# Manifest Parsing
# =============================================================================

def parse_manifest(manifest: dict, shelfmark: str) -> Optional[dict]:
    """
    Parse IIIF manifest into Compilatio database record.

    Args:
        manifest: IIIF manifest dict
        shelfmark: Manuscript shelfmark

    Returns:
        Database record dict or None on error
    """
    try:
        record = {
            "shelfmark": shelfmark,
            "iiif_manifest_url": f"{MANIFEST_BASE}/{shelfmark}.json",
            "source_url": f"{VIEWER_BASE}?n={shelfmark}",
        }

        # Extract label
        label = manifest.get("label", "")
        if label and label != shelfmark:
            record["contents"] = label

        # Get thumbnail from first canvas
        sequences = manifest.get("sequences", [])
        if sequences and sequences[0].get("canvases"):
            canvases = sequences[0]["canvases"]
            record["image_count"] = len(canvases)

            # Get thumbnail from first canvas
            first_canvas = canvases[0]
            if "thumbnail" in first_canvas:
                thumb = first_canvas["thumbnail"]
                if isinstance(thumb, dict):
                    record["thumbnail_url"] = thumb.get("@id", "")
                else:
                    record["thumbnail_url"] = thumb

        # Extract metadata fields
        metadata_fields = manifest.get("metadata", [])
        for field in metadata_fields:
            label = field.get("label", "").lower()
            value = field.get("value", "")

            if not value:
                continue

            # Map metadata fields to database columns
            if "title" in label:
                record["contents"] = value
            elif "language" in label:
                record["language"] = value
            elif "date" in label:
                record["date_display"] = value
                # Try to extract year range
                years = re.findall(r'\b(1?\d{3})\b', value)
                if years:
                    record["date_start"] = int(years[0])
                    if len(years) > 1:
                        record["date_end"] = int(years[-1])
                    else:
                        record["date_end"] = int(years[0])
            elif "extent" in label or "folio" in label:
                record["folios"] = value

        return record

    except Exception as e:
        logger.error(f"Error parsing manifest for {shelfmark}: {e}")
        return None


# =============================================================================
# Database Operations
# =============================================================================

def ensure_repository(cursor) -> int:
    """Create or get Trinity College Cambridge repository ID."""
    cursor.execute(
        "SELECT id FROM repositories WHERE short_name = ?",
        (REPO_SHORT,)
    )
    row = cursor.fetchone()
    if row:
        return row[0]

    logger.info(f"Creating repository record for {REPO_NAME}...")
    cursor.execute("""
        INSERT INTO repositories (name, short_name, logo_url, catalogue_url)
        VALUES (?, ?, ?, ?)
    """, (REPO_NAME, REPO_SHORT, REPO_LOGO_URL, CATALOGUE_URL))

    return cursor.lastrowid


def manuscript_exists(cursor, shelfmark: str, repo_id: int) -> Optional[int]:
    """Check if manuscript already exists in database."""
    cursor.execute(
        "SELECT id FROM manuscripts WHERE shelfmark = ? AND repository_id = ?",
        (shelfmark, repo_id)
    )
    row = cursor.fetchone()
    return row[0] if row else None


def insert_manuscript(cursor, record: dict, repo_id: int) -> int:
    """Insert manuscript record into database."""
    cursor.execute("""
        INSERT INTO manuscripts (
            repository_id, shelfmark, collection,
            iiif_manifest_url, thumbnail_url, source_url,
            date_display, date_start, date_end,
            contents, language, provenance, folios, image_count
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        repo_id,
        record.get("shelfmark"),
        record.get("collection"),
        record.get("iiif_manifest_url"),
        record.get("thumbnail_url"),
        record.get("source_url"),
        record.get("date_display"),
        record.get("date_start"),
        record.get("date_end"),
        record.get("contents"),
        record.get("language"),
        record.get("provenance"),
        record.get("folios"),
        record.get("image_count"),
    ))

    return cursor.lastrowid


# =============================================================================
# Main Import Function
# =============================================================================

def import_trinity(
    db_path: Path,
    dry_run: bool = True,
    test_mode: bool = False,
    verbose: bool = False,
    resume: bool = False,
    limit: Optional[int] = None,
):
    """
    Main import function for Trinity College Cambridge manuscripts.

    Args:
        db_path: Path to SQLite database
        dry_run: If True, don't write to database
        test_mode: If True, only process first 10
        verbose: Enable debug logging
        resume: Resume from last checkpoint
        limit: Maximum number of manuscripts to process
    """
    if verbose:
        logger.setLevel(logging.DEBUG)

    # Ensure cache directory exists
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Load or initialize progress
    progress = load_progress(PROGRESS_FILE) if resume else {
        "last_updated": None,
        "total_enumerated": 0,
        "completed_shelfmarks": [],
        "failed_shelfmarks": [],
        "not_found_shelfmarks": [],
    }

    # Phase 1: Enumeration (generate candidates from known ranges)
    logger.info("=" * 60)
    logger.info("PHASE 1: SHELFMARK ENUMERATION")
    logger.info("=" * 60)

    shelfmarks = generate_shelfmarks()
    logger.info(f"Generated {len(shelfmarks)} candidate shelfmarks from known ranges")

    # Update progress
    progress["total_enumerated"] = len(shelfmarks)
    if not dry_run:
        save_progress(progress, PROGRESS_FILE)

    # Apply test mode limit
    if test_mode:
        shelfmarks = shelfmarks[:10]
        logger.info(f"Test mode: limiting to first 10 shelfmarks")

    # Apply explicit limit if specified
    if limit:
        shelfmarks = shelfmarks[:limit]
        logger.info(f"Limiting to {limit} manuscripts")

    # Phase 2: Manifest fetching and import
    logger.info("=" * 60)
    logger.info("PHASE 2: MANIFEST FETCHING AND IMPORT")
    logger.info("=" * 60)

    if dry_run:
        logger.info("DRY RUN MODE - No database changes will be made")
    else:
        logger.info("EXECUTE MODE - Database will be updated")

    if resume and progress["completed_shelfmarks"]:
        logger.info(f"RESUME MODE - Skipping {len(progress['completed_shelfmarks'])} already completed")
        logger.info(f"Not found in previous runs: {len(progress.get('not_found_shelfmarks', []))}")
        logger.info(f"Failed in previous runs: {len(progress['failed_shelfmarks'])}")

    # Filter out already completed and not-found shelfmarks if resuming
    if resume:
        original_count = len(shelfmarks)
        already_processed = set(progress["completed_shelfmarks"]) | set(progress.get("not_found_shelfmarks", []))
        shelfmarks = [s for s in shelfmarks if s not in already_processed]
        if len(shelfmarks) < original_count:
            logger.info(f"Resuming: {len(shelfmarks)} remaining of {original_count} total")

    # Connect to database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        repo_id = ensure_repository(cursor)
        if not dry_run:
            conn.commit()
        logger.info(f"Repository ID: {repo_id}")

        imported = 0
        skipped = 0
        not_found = 0
        errors = 0

        total_to_process = len(shelfmarks)

        for i, shelfmark in enumerate(shelfmarks, 1):
            logger.info(f"[{i}/{total_to_process}] Processing {shelfmark}...")

            # Check if already exists in database
            existing_id = manuscript_exists(cursor, shelfmark, repo_id)
            if existing_id:
                logger.info(f"  Already in database (ID {existing_id}), skipping")
                skipped += 1
                if not dry_run:
                    mark_completed(progress, shelfmark, PROGRESS_FILE)
                continue

            # Rate limit
            time.sleep(REQUEST_DELAY)

            # Fetch manifest
            manifest = fetch_manifest(shelfmark)

            if manifest is None:
                # Could be 404 (not digitized) or actual error
                # We track these separately
                not_found += 1
                if not dry_run:
                    if "not_found_shelfmarks" not in progress:
                        progress["not_found_shelfmarks"] = []
                    if shelfmark not in progress["not_found_shelfmarks"]:
                        progress["not_found_shelfmarks"].append(shelfmark)
                    save_progress(progress, PROGRESS_FILE)
                continue

            # Parse manifest
            record = parse_manifest(manifest, shelfmark)

            if not record:
                logger.warning(f"  Failed to parse manifest")
                errors += 1
                if not dry_run:
                    mark_failed(progress, shelfmark, PROGRESS_FILE)
                continue

            # Log what we found
            contents = record.get('contents', 'N/A')
            if len(contents) > 60:
                contents = contents[:57] + "..."
            logger.info(f"  Title: {contents}")
            logger.info(f"  Images: {record.get('image_count', 'N/A')}")

            if not dry_run:
                ms_id = insert_manuscript(cursor, record, repo_id)
                conn.commit()
                logger.info(f"  Inserted as ID {ms_id}")
                mark_completed(progress, shelfmark, PROGRESS_FILE)
                imported += 1
            else:
                logger.info(f"  Would insert (dry-run)")
                imported += 1

        # Summary
        logger.info("=" * 60)
        logger.info("IMPORT SUMMARY")
        logger.info("=" * 60)
        logger.info(f"Candidates tested: {total_to_process}")
        logger.info(f"Imported: {imported}")
        logger.info(f"Skipped (already in DB): {skipped}")
        logger.info(f"Not found (no manifest): {not_found}")
        logger.info(f"Errors: {errors}")

        if not dry_run:
            total_completed = len(progress['completed_shelfmarks'])
            total_not_found = len(progress.get('not_found_shelfmarks', []))
            total_enumerated = progress['total_enumerated']
            remaining = total_enumerated - total_completed - total_not_found

            logger.info(f"\nOverall progress:")
            logger.info(f"  Total enumerated: {total_enumerated}")
            logger.info(f"  Completed: {total_completed}")
            logger.info(f"  Not found: {total_not_found}")
            logger.info(f"  Remaining: {remaining}")

            if progress['failed_shelfmarks']:
                logger.info(f"\nFailed shelfmarks ({len(progress['failed_shelfmarks'])}):")
                for failed in progress['failed_shelfmarks'][:10]:
                    logger.info(f"  - {failed}")
                if len(progress['failed_shelfmarks']) > 10:
                    logger.info(f"  ... and {len(progress['failed_shelfmarks']) - 10} more")

    finally:
        conn.close()


# =============================================================================
# CLI Entry Point
# =============================================================================

def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Import Trinity College Cambridge manuscripts to Compilatio"
    )
    parser.add_argument(
        '--execute',
        action='store_true',
        help='Actually execute the import (default is dry-run)'
    )
    parser.add_argument(
        '--test',
        action='store_true',
        help='Test mode: only process first 10 shelfmarks'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Show detailed logging'
    )
    parser.add_argument(
        '--db',
        type=Path,
        default=DB_PATH,
        help='Path to database'
    )
    parser.add_argument(
        '--resume',
        action='store_true',
        help='Resume from last checkpoint (skips completed manuscripts)'
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=None,
        help='Limit number of manuscripts to process'
    )

    args = parser.parse_args()

    try:
        import_trinity(
            db_path=args.db,
            dry_run=not args.execute,
            test_mode=args.test,
            verbose=args.verbose,
            resume=args.resume,
            limit=args.limit,
        )
    except KeyboardInterrupt:
        logger.info("\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Import failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
