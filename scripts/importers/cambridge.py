#!/usr/bin/env python3
"""
Cambridge University Library Manuscript Import Script for Compilatio.

Imports digitized medieval manuscripts from the Cambridge Digital Library (CUDL)
via their IIIF Presentation API. Crawls the Western Medieval Manuscripts
collection endpoint and fetches individual manifests for metadata.

No browser needed — pure HTTP/JSON.

Source:
    IIIF collection: https://cudl.lib.cam.ac.uk/iiif/collection/medieval
    Viewer: https://cudl.lib.cam.ac.uk/view/{ID}

Usage:
    python scripts/importers/cambridge.py                    # Dry-run mode
    python scripts/importers/cambridge.py --execute          # Actually import
    python scripts/importers/cambridge.py --test             # First 5 only
    python scripts/importers/cambridge.py --verbose          # Detailed logging
"""

import argparse
import json
import logging
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Optional
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
DB_PATH = PROJECT_ROOT / "database" / "compilatio.db"

# CUDL IIIF endpoints
COLLECTION_URL = "https://cudl.lib.cam.ac.uk/iiif/collection/medieval"
MANIFEST_BASE = "https://cudl.lib.cam.ac.uk/iiif"
VIEWER_BASE = "https://cudl.lib.cam.ac.uk/view"
IMAGE_BASE = "https://images.lib.cam.ac.uk/iiif"

# Rate limiting
REQUEST_DELAY = 0.5  # seconds between manifest fetches

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)

# User-Agent header
USER_AGENT = "Compilatio/1.0 (Academic manuscript research; IIIF aggregator)"


# =============================================================================
# HTTP Helpers
# =============================================================================

def fetch_json(url: str) -> Optional[dict]:
    """Fetch a URL and parse as JSON."""
    try:
        req = Request(url, headers={"User-Agent": USER_AGENT})
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (HTTPError, URLError, json.JSONDecodeError) as e:
        logger.warning(f"Failed to fetch {url}: {e}")
        return None


# =============================================================================
# Collection Crawling
# =============================================================================

def fetch_collection_manifests() -> list[dict]:
    """
    Fetch the IIIF collection and return list of manifest stubs.

    Each stub has: @id, label
    """
    logger.info(f"Fetching IIIF collection: {COLLECTION_URL}")
    data = fetch_json(COLLECTION_URL)

    if not data:
        logger.error("Failed to fetch IIIF collection")
        return []

    manifests = []
    for member in data.get("manifests", []):
        if member.get("@type") == "sc:Manifest":
            manifests.append({
                "@id": member["@id"],
                "label": member.get("label", ""),
            })

    logger.info(f"Found {len(manifests)} manifests in collection")
    return manifests


# =============================================================================
# Manifest Parsing
# =============================================================================

def extract_metadata_value(metadata: list[dict], label: str) -> Optional[str]:
    """Extract a value from the IIIF metadata array by label."""
    for entry in metadata:
        entry_label = entry.get("label", "")
        # Handle both string and dict labels (IIIF v2 quirks)
        if isinstance(entry_label, dict):
            entry_label = entry_label.get("@value", "")
        if entry_label == label:
            value = entry.get("value", "")
            if isinstance(value, list):
                value = "; ".join(str(v) for v in value)
            if isinstance(value, dict):
                value = value.get("@value", str(value))
            # Strip HTML tags
            value = re.sub(r'<[^>]+>', ' ', str(value))
            value = re.sub(r'\s+', ' ', value).strip()
            return value if value else None
    return None


def extract_classmark(metadata: list[dict], label: str) -> Optional[str]:
    """
    Extract shelfmark from classmark metadata field.

    CUDL classmarks look like:
        "Cambridge, University Library, MS Add. 451"
        "Cambridge, University Library, MS Ff.1.23"

    We strip the "Cambridge, University Library, " prefix.
    """
    raw = extract_metadata_value(metadata, "Classmark")
    if not raw:
        # Fallback: try the manifest label
        raw = label
    if not raw:
        return None

    # Strip institution prefix (CUL and deposited collections)
    prefixes = [
        "Cambridge, University Library, ",
        "Cambridge University Library, ",
        "Peterborough Cathedral, ",
    ]
    for prefix in prefixes:
        if raw.startswith(prefix):
            raw = raw[len(prefix):]
            break

    return raw.strip() if raw.strip() else None


def extract_collection_from_classmark(shelfmark: str) -> str:
    """
    Extract collection name from a CUL classmark.

    Examples:
        "MS Add. 451"       -> "Additional"
        "MS Ff.1.23"        -> "Ff"
        "MS Dd.1.27"        -> "Dd"
        "MS Peterborough 1" -> "Peterborough"
        "MS Gg.1.1"         -> "Gg"
    """
    # Strip "MS " prefix
    s = re.sub(r'^MS\.?\s*', '', shelfmark)

    patterns = [
        (r'^Add\.?\s', "Additional"),
        (r'^Dd\.', "Dd"),
        (r'^Ee\.', "Ee"),
        (r'^Ff\.', "Ff"),
        (r'^Gg\.', "Gg"),
        (r'^Hh\.', "Hh"),
        (r'^Ii\.', "Ii"),
        (r'^Kk\.', "Kk"),
        (r'^Ll\.', "Ll"),
        (r'^Mm\.', "Mm"),
        (r'^Nn\.', "Nn"),
        (r'^Oo\.', "Oo"),
        (r'^Peterborough', "Peterborough"),
    ]

    for pattern, collection in patterns:
        if re.match(pattern, s, re.IGNORECASE):
            return collection

    # Fallback: first word
    parts = s.split()
    if parts:
        return parts[0].rstrip('.')

    return "Unknown"


def extract_thumbnail_url(manifest: dict) -> Optional[str]:
    """
    Extract thumbnail URL from manifest.

    Tries manifest-level thumbnail first, then falls back to
    deriving from first canvas image service.
    """
    # Try manifest-level thumbnail
    thumb = manifest.get("thumbnail")
    if thumb:
        if isinstance(thumb, dict):
            thumb_id = thumb.get("@id") or thumb.get("id")
            if thumb_id:
                return thumb_id
        elif isinstance(thumb, list) and thumb:
            thumb_id = thumb[0].get("@id") or thumb[0].get("id")
            if thumb_id:
                return thumb_id

    # Fall back to first canvas image service
    sequences = manifest.get("sequences", [])
    if sequences:
        canvases = sequences[0].get("canvases", [])
        if canvases:
            images = canvases[0].get("images", [])
            if images:
                resource = images[0].get("resource", {})
                service = resource.get("service", {})
                service_id = service.get("@id") or service.get("id")
                if service_id:
                    return f"{service_id}/full/200,/0/default.jpg"

    return None


def parse_date_year(date_str: str) -> Optional[int]:
    """Extract a 4-digit year from a date string."""
    if not date_str:
        return None
    match = re.search(r'\b(\d{4})\b', date_str)
    if match:
        return int(match.group(1))

    # Try century patterns like "14th century" -> 1300
    century_match = re.search(r'(\d{1,2})(?:st|nd|rd|th)\s*century', date_str, re.IGNORECASE)
    if century_match:
        century = int(century_match.group(1))
        return (century - 1) * 100

    return None


def parse_manifest(manifest_data: dict, manifest_url: str) -> Optional[dict]:
    """
    Parse a CUDL IIIF manifest into a Compilatio record.

    Returns dict with database fields, or None if not importable.
    """
    metadata = manifest_data.get("metadata", [])
    label = manifest_data.get("label", "")

    # Extract shelfmark from classmark field
    shelfmark = extract_classmark(metadata, label)
    if not shelfmark:
        logger.debug(f"No classmark found in {manifest_url}")
        return None

    record = {
        "shelfmark": shelfmark,
        "collection": extract_collection_from_classmark(shelfmark),
        "iiif_manifest_url": manifest_url,
    }

    # Title / contents
    title = extract_metadata_value(metadata, "Title")
    if title:
        record["contents"] = title
    elif label:
        # Strip classmark from label if present
        contents = re.sub(r'\s*\([^)]*University Library[^)]*\)\s*$', '', label).strip()
        if contents:
            record["contents"] = contents

    # Truncate contents if very long
    if "contents" in record and len(record["contents"]) > 1000:
        record["contents"] = record["contents"][:997] + "..."

    # Date
    date_display = extract_metadata_value(metadata, "Date of Creation")
    if date_display:
        record["date_display"] = date_display

        # Try to extract start/end years
        # Look for ranges like "13th-14th century" or "1300-1400"
        years = re.findall(r'\b(\d{4})\b', date_display)
        if len(years) >= 2:
            record["date_start"] = int(years[0])
            record["date_end"] = int(years[-1])
        elif len(years) == 1:
            record["date_start"] = int(years[0])
            record["date_end"] = int(years[0])
        else:
            # Try century patterns
            century_matches = re.findall(
                r'(\d{1,2})(?:st|nd|rd|th)\s*century',
                date_display, re.IGNORECASE
            )
            if century_matches:
                first = (int(century_matches[0]) - 1) * 100
                last = (int(century_matches[-1]) - 1) * 100 + 99
                record["date_start"] = first
                record["date_end"] = last

            # Try quarter/half patterns
            quarter_match = re.search(
                r'(first|second|third|fourth|last)\s+(quarter|half).*?(\d{1,2})(?:st|nd|rd|th)\s*century',
                date_display, re.IGNORECASE
            )
            if quarter_match:
                pos = quarter_match.group(1).lower()
                unit = quarter_match.group(2).lower()
                century = int(quarter_match.group(3))
                base = (century - 1) * 100

                if unit == "quarter":
                    offsets = {"first": (0, 24), "second": (25, 49),
                               "third": (50, 74), "fourth": (75, 99), "last": (75, 99)}
                else:  # half
                    offsets = {"first": (0, 49), "second": (50, 99), "last": (50, 99)}

                start_off, end_off = offsets.get(pos, (0, 99))
                record["date_start"] = base + start_off
                record["date_end"] = base + end_off

    # Language
    language = extract_metadata_value(metadata, "Language(s)")
    if language:
        record["language"] = language

    # Provenance / origin
    provenance = extract_metadata_value(metadata, "Provenance")
    origin = extract_metadata_value(metadata, "Origin Place")
    if provenance:
        record["provenance"] = provenance
    elif origin:
        record["provenance"] = origin

    # Extent / folios
    extent = extract_metadata_value(metadata, "Extent")
    if extent:
        record["folios"] = extent

    # Thumbnail
    record["thumbnail_url"] = extract_thumbnail_url(manifest_data)

    # Source URL (viewer link)
    # Extract ID from manifest URL: http://cudl.lib.cam.ac.uk/iiif/MS-ADD-00451 -> MS-ADD-00451
    manifest_id = manifest_url.rstrip("/").split("/")[-1]
    record["source_url"] = f"{VIEWER_BASE}/{manifest_id}"

    return record


# =============================================================================
# Database Operations
# =============================================================================

def ensure_repository(cursor) -> int:
    """Ensure Cambridge University Library repository exists and return its ID."""
    cursor.execute(
        "SELECT id FROM repositories WHERE short_name = ?",
        ("CUL",)
    )
    row = cursor.fetchone()
    if row:
        return row[0]

    cursor.execute("""
        INSERT INTO repositories (name, short_name, logo_url, catalogue_url)
        VALUES (?, ?, ?, ?)
    """, (
        "Cambridge University Library",
        "CUL",
        "https://cudl.lib.cam.ac.uk/themeui/theme/images/logo.svg",
        "https://cudl.lib.cam.ac.uk/collections/medieval"
    ))
    return cursor.lastrowid


def manuscript_exists(cursor, shelfmark: str, repo_id: int) -> Optional[int]:
    """Check if manuscript exists. Returns ID if found, None otherwise."""
    cursor.execute(
        "SELECT id FROM manuscripts WHERE shelfmark = ? AND repository_id = ?",
        (shelfmark, repo_id)
    )
    row = cursor.fetchone()
    return row[0] if row else None


# =============================================================================
# Main Import Logic
# =============================================================================

def import_cambridge(
    db_path: Path,
    dry_run: bool = True,
    test_mode: bool = False,
    verbose: bool = False,
    limit: int = None,
):
    """
    Import CUL medieval manuscripts from CUDL IIIF collection.
    """
    if verbose:
        logger.setLevel(logging.DEBUG)

    if not db_path.exists():
        logger.error(f"Database not found: {db_path}")
        logger.info("Initialize the database first:")
        logger.info("  sqlite3 database/compilatio.db < database/schema.sql")
        return False

    # Step 1: Fetch collection manifest list
    stubs = fetch_collection_manifests()
    if not stubs:
        logger.error("No manifests found in collection")
        return False

    # Apply limits
    if test_mode:
        stubs = stubs[:5]
        logger.info(f"Test mode: limiting to {len(stubs)} manifests")
    elif limit:
        stubs = stubs[:limit]
        logger.info(f"Limiting to {limit} manifests")

    # Step 2: Fetch and parse each manifest
    records = []
    errors = 0

    for i, stub in enumerate(stubs):
        manifest_url = stub["@id"]
        # Ensure HTTPS
        manifest_url = manifest_url.replace("http://", "https://")

        logger.info(f"[{i+1}/{len(stubs)}] Fetching {manifest_url}")

        manifest_data = fetch_json(manifest_url)
        if not manifest_data:
            errors += 1
            continue

        record = parse_manifest(manifest_data, manifest_url)
        if record:
            records.append(record)
            logger.debug(f"  -> {record['shelfmark']} [{record['collection']}]")
        else:
            logger.warning(f"  -> Could not parse manifest")
            errors += 1

        # Rate limit
        if i < len(stubs) - 1:
            time.sleep(REQUEST_DELAY)

        # Progress logging
        if (i + 1) % 25 == 0:
            logger.info(f"Progress: {i+1}/{len(stubs)} manifests fetched, {len(records)} parsed")

    logger.info(f"Fetched {len(stubs)} manifests, parsed {len(records)} records, {errors} errors")

    # Step 3: Database operations
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    repo_id = ensure_repository(cursor) if not dry_run else 1

    stats = {
        "manifests_fetched": len(stubs),
        "records_parsed": len(records),
        "fetch_errors": errors,
        "inserted": 0,
        "updated": 0,
        "db_errors": 0,
    }

    results = {
        "inserted": [],
        "updated": [],
    }

    for record in records:
        shelfmark = record["shelfmark"]

        if dry_run:
            cursor.execute(
                "SELECT id FROM manuscripts WHERE shelfmark = ?",
                (shelfmark,)
            )
            if cursor.fetchone():
                stats["updated"] += 1
                results["updated"].append(record)
            else:
                stats["inserted"] += 1
                results["inserted"].append(record)
        else:
            try:
                existing_id = manuscript_exists(cursor, shelfmark, repo_id)

                if existing_id:
                    cursor.execute("""
                        UPDATE manuscripts SET
                            collection = ?,
                            date_display = ?,
                            date_start = ?,
                            date_end = ?,
                            contents = ?,
                            provenance = ?,
                            language = ?,
                            folios = ?,
                            iiif_manifest_url = ?,
                            thumbnail_url = ?,
                            source_url = ?
                        WHERE id = ?
                    """, (
                        record.get("collection"),
                        record.get("date_display"),
                        record.get("date_start"),
                        record.get("date_end"),
                        record.get("contents"),
                        record.get("provenance"),
                        record.get("language"),
                        record.get("folios"),
                        record["iiif_manifest_url"],
                        record.get("thumbnail_url"),
                        record.get("source_url"),
                        existing_id,
                    ))
                    stats["updated"] += 1
                else:
                    cursor.execute("""
                        INSERT INTO manuscripts (
                            repository_id, shelfmark, collection, date_display,
                            date_start, date_end, contents, provenance, language,
                            folios, iiif_manifest_url, thumbnail_url, source_url
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        repo_id,
                        shelfmark,
                        record.get("collection"),
                        record.get("date_display"),
                        record.get("date_start"),
                        record.get("date_end"),
                        record.get("contents"),
                        record.get("provenance"),
                        record.get("language"),
                        record.get("folios"),
                        record["iiif_manifest_url"],
                        record.get("thumbnail_url"),
                        record.get("source_url"),
                    ))
                    stats["inserted"] += 1

            except Exception as e:
                stats["db_errors"] += 1
                logger.error(f"Error importing {shelfmark}: {e}")

    if not dry_run:
        conn.commit()
    conn.close()

    # Print summary
    print_summary(stats, results, dry_run, verbose)
    return True


def print_summary(stats: dict, results: dict, dry_run: bool, verbose: bool):
    """Print import summary report."""
    print("\n" + "=" * 70)
    print(f"{'DRY RUN - ' if dry_run else ''}CAMBRIDGE UNIVERSITY LIBRARY IMPORT SUMMARY")
    print("=" * 70)

    print(f"\nIIIF Collection Crawl:")
    print(f"  Manifests fetched:    {stats['manifests_fetched']}")
    print(f"  Records parsed:       {stats['records_parsed']}")
    print(f"  Fetch errors:         {stats['fetch_errors']}")

    print(f"\nDatabase Operations {'(would be)' if dry_run else ''}:")
    print(f"  {'Would insert' if dry_run else 'Inserted'}:  {stats['inserted']}")
    print(f"  {'Would update' if dry_run else 'Updated'}:   {stats['updated']}")
    print(f"  Errors:               {stats['db_errors']}")

    if results.get("inserted"):
        print("\n" + "-" * 70)
        print(f"RECORDS TO {'INSERT' if dry_run else 'INSERTED'} (sample):")
        print("-" * 70)

        # Group by collection for display
        by_collection = {}
        for rec in results["inserted"]:
            col = rec.get("collection", "Unknown")
            by_collection.setdefault(col, []).append(rec)

        for col in sorted(by_collection.keys()):
            recs = by_collection[col]
            print(f"\n  {col} ({len(recs)}):")
            for rec in recs[:3]:
                date = f" ({rec.get('date_display', '')})" if rec.get('date_display') else ""
                contents = rec.get('contents', '')
                if contents and len(contents) > 60:
                    contents = contents[:57] + "..."
                print(f"    {rec['shelfmark']}{date}")
                if contents:
                    print(f"      {contents}")
            if len(recs) > 3:
                print(f"    ... and {len(recs) - 3} more")

    if results.get("updated"):
        print("\n" + "-" * 70)
        print(f"RECORDS TO {'UPDATE' if dry_run else 'UPDATED'}:")
        print("-" * 70)
        for rec in results["updated"][:5]:
            print(f"  {rec['shelfmark']} [{rec.get('collection', '?')}]")
        if len(results["updated"]) > 5:
            print(f"  ... and {len(results['updated']) - 5} more")

    if dry_run:
        print("\n" + "=" * 70)
        print("This was a DRY RUN. No changes were made to the database.")
        print("Run with --execute to apply changes.")
        print("=" * 70)


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Import CUL medieval manuscripts from CUDL IIIF collection"
    )
    parser.add_argument(
        '--execute',
        action='store_true',
        help='Actually execute the import (default is dry-run)'
    )
    parser.add_argument(
        '--test',
        action='store_true',
        help='Test mode: limit to first 5 manifests'
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
        help=f'Path to database (default: {DB_PATH})'
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=None,
        help='Limit number of manifests to fetch'
    )

    args = parser.parse_args()

    print("Compilatio Cambridge University Library Import Tool")
    print(f"Source: CUDL Western Medieval Manuscripts (IIIF collection)")
    print(f"DB:   {args.db}")
    print(f"Mode: {'TEST' if args.test else 'EXECUTE' if args.execute else 'DRY-RUN'}")
    if args.limit:
        print(f"Limit: {args.limit}")
    print()

    success = import_cambridge(
        db_path=args.db,
        dry_run=not args.execute,
        test_mode=args.test,
        verbose=args.verbose,
        limit=args.limit,
    )

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
