#!/usr/bin/env python3
"""
Lambeth Palace Library Manuscript Import Script for Compilatio.

Imports Lambeth Palace manuscripts from the CUDL Scriptorium collection.
Only a small subset of Lambeth manuscripts are available through CUDL.

No browser needed — pure HTTP/JSON (IIIF Presentation API 2.0).

Source:
    CUDL Scriptorium: https://cudl.lib.cam.ac.uk/iiif/collection/scriptorium
    (filter to MS-LAMBETH-* entries)

Usage:
    python scripts/importers/lambeth.py                    # Dry-run mode
    python scripts/importers/lambeth.py --execute          # Actually import
    python scripts/importers/lambeth.py --verbose          # Detailed logging
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

# CUDL endpoints
COLLECTION_URL = "https://cudl.lib.cam.ac.uk/iiif/collection/scriptorium"
VIEWER_BASE = "https://cudl.lib.cam.ac.uk/view"

# Rate limiting
REQUEST_DELAY = 0.5

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)

USER_AGENT = "Compilatio/1.0 (Academic manuscript research; IIIF aggregator)"


def fetch_json(url: str) -> Optional[dict]:
    """Fetch a URL and parse as JSON."""
    try:
        req = Request(url, headers={"User-Agent": USER_AGENT})
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (HTTPError, URLError, json.JSONDecodeError) as e:
        logger.warning(f"Failed to fetch {url}: {e}")
        return None


def fetch_lambeth_manifests() -> list[dict]:
    """Fetch CUDL Scriptorium collection and filter to Lambeth manuscripts."""
    logger.info(f"Fetching Scriptorium collection: {COLLECTION_URL}")
    data = fetch_json(COLLECTION_URL)

    if not data:
        logger.error("Failed to fetch collection")
        return []

    manifests = []
    for m in data.get("manifests", []):
        mid = m.get("@id", "")
        # Only include Lambeth manuscripts
        if "LAMBETH" in mid.upper():
            manifests.append({
                "@id": mid,
                "label": m.get("label", ""),
            })

    logger.info(f"Found {len(manifests)} Lambeth manuscripts in Scriptorium collection")
    return manifests


def extract_metadata_value(metadata: list[dict], label: str) -> Optional[str]:
    """Extract a value from the IIIF metadata array by label."""
    for entry in metadata:
        entry_label = entry.get("label", "")
        if isinstance(entry_label, dict):
            entry_label = entry_label.get("@value", "")
        if entry_label == label:
            value = entry.get("value", "")
            if isinstance(value, list):
                value = "; ".join(str(v) for v in value)
            if isinstance(value, dict):
                value = value.get("@value", str(value))
            value = re.sub(r'<[^>]+>', ' ', str(value))
            value = re.sub(r'\s+', ' ', value).strip()
            return value if value else None
    return None


def extract_thumbnail_url(manifest: dict) -> Optional[str]:
    """Extract thumbnail URL from first canvas image service."""
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


def parse_manifest(manifest_data: dict, manifest_url: str) -> Optional[dict]:
    """Parse a CUDL manifest into a Compilatio record for Lambeth."""
    metadata = manifest_data.get("metadata", [])

    # Extract classmark
    classmark = extract_metadata_value(metadata, "Classmark")
    if not classmark:
        return None

    # Strip "Lambeth Palace Library " prefix for cleaner shelfmark
    shelfmark = classmark
    for prefix in ["Lambeth Palace Library ", "Lambeth Palace, "]:
        if shelfmark.startswith(prefix):
            shelfmark = shelfmark[len(prefix):]
            break

    record = {
        "shelfmark": shelfmark,
        "collection": "Lambeth Palace",
        "iiif_manifest_url": manifest_url,
    }

    # Title
    title = extract_metadata_value(metadata, "Title")
    if title:
        record["contents"] = title[:1000] if len(title) > 1000 else title

    # Date
    date_str = extract_metadata_value(metadata, "Date of Creation")
    if date_str:
        record["date_display"] = date_str
        years = re.findall(r'\b(\d{4})\b', date_str)
        if len(years) >= 2:
            record["date_start"] = int(years[0])
            record["date_end"] = int(years[-1])
        elif len(years) == 1:
            record["date_start"] = int(years[0])
            record["date_end"] = int(years[0])

    # Language
    language = extract_metadata_value(metadata, "Language(s)")
    if language:
        record["language"] = language

    # Provenance
    provenance = extract_metadata_value(metadata, "Provenance")
    origin = extract_metadata_value(metadata, "Origin Place")
    if provenance:
        record["provenance"] = provenance
    elif origin:
        record["provenance"] = origin

    # Extent
    extent = extract_metadata_value(metadata, "Extent")
    if extent:
        record["folios"] = extent

    # Thumbnail
    record["thumbnail_url"] = extract_thumbnail_url(manifest_data)

    # Source URL
    manifest_id = manifest_url.rstrip("/").split("/")[-1]
    record["source_url"] = f"{VIEWER_BASE}/{manifest_id}"

    return record


def ensure_repository(cursor) -> int:
    """Ensure Lambeth Palace Library repository exists and return its ID."""
    cursor.execute(
        "SELECT id FROM repositories WHERE short_name = ?",
        ("Lambeth",)
    )
    row = cursor.fetchone()
    if row:
        return row[0]

    cursor.execute("""
        INSERT INTO repositories (name, short_name, logo_url, catalogue_url)
        VALUES (?, ?, ?, ?)
    """, (
        "Lambeth Palace Library",
        "Lambeth",
        None,
        "https://www.lambethpalacelibrary.org/"
    ))
    return cursor.lastrowid


def import_lambeth(
    db_path: Path,
    dry_run: bool = True,
    verbose: bool = False,
):
    """Import Lambeth manuscripts from CUDL Scriptorium collection."""
    if verbose:
        logger.setLevel(logging.DEBUG)

    if not db_path.exists():
        logger.error(f"Database not found: {db_path}")
        return False

    # Step 1: Get Lambeth manifest stubs
    stubs = fetch_lambeth_manifests()
    if not stubs:
        logger.warning("No Lambeth manuscripts found in CUDL")
        return True

    # Step 2: Fetch and parse each manifest
    records = []
    errors = 0

    for i, stub in enumerate(stubs):
        manifest_url = stub["@id"].replace("http://", "https://")
        logger.info(f"[{i+1}/{len(stubs)}] Fetching {manifest_url}")

        manifest_data = fetch_json(manifest_url)
        if not manifest_data:
            errors += 1
            continue

        record = parse_manifest(manifest_data, manifest_url)
        if record:
            records.append(record)
            logger.info(f"  -> {record['shelfmark']}")
        else:
            errors += 1

        if i < len(stubs) - 1:
            time.sleep(REQUEST_DELAY)

    # Step 3: Database operations
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    repo_id = ensure_repository(cursor) if not dry_run else 1

    stats = {"inserted": 0, "updated": 0, "errors": 0}

    for record in records:
        shelfmark = record["shelfmark"]

        if dry_run:
            cursor.execute("SELECT id FROM manuscripts WHERE shelfmark = ?", (shelfmark,))
            if cursor.fetchone():
                stats["updated"] += 1
            else:
                stats["inserted"] += 1
        else:
            try:
                cursor.execute(
                    "SELECT id FROM manuscripts WHERE shelfmark = ? AND repository_id = ?",
                    (shelfmark, repo_id)
                )
                existing = cursor.fetchone()

                if existing:
                    cursor.execute("""
                        UPDATE manuscripts SET
                            collection = ?, date_display = ?, date_start = ?,
                            date_end = ?, contents = ?, provenance = ?,
                            language = ?, folios = ?, iiif_manifest_url = ?,
                            thumbnail_url = ?, source_url = ?
                        WHERE id = ?
                    """, (
                        record.get("collection"), record.get("date_display"),
                        record.get("date_start"), record.get("date_end"),
                        record.get("contents"), record.get("provenance"),
                        record.get("language"), record.get("folios"),
                        record["iiif_manifest_url"], record.get("thumbnail_url"),
                        record.get("source_url"), existing[0],
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
                        repo_id, shelfmark, record.get("collection"),
                        record.get("date_display"), record.get("date_start"),
                        record.get("date_end"), record.get("contents"),
                        record.get("provenance"), record.get("language"),
                        record.get("folios"), record["iiif_manifest_url"],
                        record.get("thumbnail_url"), record.get("source_url"),
                    ))
                    stats["inserted"] += 1
            except Exception as e:
                stats["errors"] += 1
                logger.error(f"Error importing {shelfmark}: {e}")

    if not dry_run:
        conn.commit()
    conn.close()

    # Summary
    print("\n" + "=" * 70)
    print(f"{'DRY RUN - ' if dry_run else ''}LAMBETH PALACE LIBRARY IMPORT SUMMARY")
    print("=" * 70)
    print(f"\n  Manifests fetched:  {len(stubs)}")
    print(f"  Records parsed:     {len(records)}")
    print(f"  Fetch errors:       {errors}")
    print(f"\n  {'Would insert' if dry_run else 'Inserted'}:  {stats['inserted']}")
    print(f"  {'Would update' if dry_run else 'Updated'}:   {stats['updated']}")
    print(f"  DB errors:          {stats['errors']}")

    for rec in records:
        print(f"\n  {rec['shelfmark']}")
        if rec.get("contents"):
            print(f"    {rec['contents'][:80]}")
        if rec.get("date_display"):
            print(f"    Date: {rec['date_display']}")

    if dry_run:
        print("\n" + "=" * 70)
        print("This was a DRY RUN. No changes were made to the database.")
        print("Run with --execute to apply changes.")
        print("=" * 70)

    return True


def main():
    parser = argparse.ArgumentParser(
        description="Import Lambeth Palace manuscripts from CUDL Scriptorium"
    )
    parser.add_argument('--execute', action='store_true',
                        help='Actually execute the import (default is dry-run)')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Show detailed logging')
    parser.add_argument('--db', type=Path, default=DB_PATH,
                        help=f'Path to database (default: {DB_PATH})')

    args = parser.parse_args()

    print("Compilatio Lambeth Palace Library Import Tool")
    print(f"Source: CUDL Scriptorium (Lambeth subset)")
    print(f"DB:   {args.db}")
    print(f"Mode: {'EXECUTE' if args.execute else 'DRY-RUN'}")
    print()

    success = import_lambeth(
        db_path=args.db, dry_run=not args.execute, verbose=args.verbose,
    )
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
