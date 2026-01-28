#!/usr/bin/env python3
"""
National Library of Scotland Manuscript Import Script for Compilatio.

Imports digitized medieval manuscripts from the NLS IIIF collections.
Crawls three manuscript collections from the NLS IIIF endpoint.

No browser needed — pure HTTP/JSON (IIIF Presentation API 2.0).

Source collections:
    Early Scottish manuscripts:     https://view.nls.uk/collections/1875/4854/187548545.json
    Gaelic manuscripts of Scotland: https://view.nls.uk/collections/1881/5593/188155936.json
    Middle English manuscripts:     https://view.nls.uk/collections/1334/7486/133474867.json

Usage:
    python scripts/importers/nls.py                    # Dry-run mode
    python scripts/importers/nls.py --execute          # Actually import
    python scripts/importers/nls.py --test             # First 5 only
    python scripts/importers/nls.py --verbose          # Detailed logging
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

# NLS IIIF collection URLs
COLLECTIONS = {
    "early_scottish": {
        "url": "https://view.nls.uk/collections/1875/4854/187548545.json",
        "label": "Early Scottish Manuscripts",
        "collection_name": "Early Scottish",
    },
    "gaelic": {
        "url": "https://view.nls.uk/collections/1881/5593/188155936.json",
        "label": "Gaelic Manuscripts of Scotland",
        "collection_name": "Gaelic",
    },
    "middle_english": {
        "url": "https://view.nls.uk/collections/1334/7486/133474867.json",
        "label": "Manuscripts containing Middle English texts",
        "collection_name": "Middle English",
    },
}

VIEWER_BASE = "https://digital.nls.uk"

# Rate limiting
REQUEST_DELAY = 0.5  # seconds between manifest fetches

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)

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
# Collection Fetching
# =============================================================================

def fetch_all_manifests() -> list[tuple[dict, str]]:
    """
    Fetch all manifest stubs from NLS collections.

    Returns list of (stub, collection_name) tuples.
    """
    all_manifests = []
    seen_ids = set()

    for key, config in COLLECTIONS.items():
        logger.info(f"Fetching collection: {config['label']}")
        data = fetch_json(config["url"])

        if not data:
            logger.error(f"Failed to fetch {config['label']}")
            continue

        manifests = data.get("manifests", [])
        logger.info(f"  Found {len(manifests)} manifests")

        for m in manifests:
            mid = m.get("@id", "")
            if mid and mid not in seen_ids:
                seen_ids.add(mid)
                all_manifests.append((
                    {"@id": mid, "label": m.get("label", "")},
                    config["collection_name"]
                ))

        time.sleep(REQUEST_DELAY)

    return all_manifests


# =============================================================================
# Manifest Parsing
# =============================================================================

def extract_metadata_value(metadata: list[dict], label: str) -> Optional[str]:
    """Extract a value from the IIIF metadata array by label."""
    for entry in metadata:
        entry_label = entry.get("label", "")
        if isinstance(entry_label, dict):
            entry_label = entry_label.get("@value", "")
        if isinstance(entry_label, list):
            entry_label = entry_label[0] if entry_label else ""
            if isinstance(entry_label, dict):
                entry_label = entry_label.get("@value", "")

        if entry_label.lower().strip() == label.lower().strip():
            value = entry.get("value", "")
            if isinstance(value, list):
                # Handle multi-language values
                for v in value:
                    if isinstance(v, dict):
                        return v.get("@value", str(v))
                value = "; ".join(str(v) for v in value)
            if isinstance(value, dict):
                value = value.get("@value", str(value))
            # Strip HTML tags
            value = re.sub(r'<[^>]+>', ' ', str(value))
            value = re.sub(r'\s+', ' ', value).strip()
            return value if value else None
    return None


def extract_shelfmark(manifest_data: dict) -> Optional[str]:
    """
    Extract shelfmark from NLS manifest.

    Tries metadata fields first, then falls back to label parsing.
    """
    metadata = manifest_data.get("metadata", [])

    # Try metadata fields
    for field in ["Shelfmark", "Shelf Mark", "Reference", "Classmark"]:
        value = extract_metadata_value(metadata, field)
        if value:
            return value

    # Extract from label: typically "Title - Shelfmark" or just includes shelfmark
    label = manifest_data.get("label", "")
    if not label:
        return None

    # Common NLS shelfmark patterns in labels
    # e.g. "Adv.MS.1.1.6", "MS.10270", "MS.16500"
    shelfmark_match = re.search(r'((?:Adv\.)?MS\.?\s*[\d.]+(?:\s*,\s*v\.\s*\d+)?)', label)
    if shelfmark_match:
        return shelfmark_match.group(1).strip()

    # If label ends with a shelfmark pattern after " - "
    if " - " in label:
        candidate = label.rsplit(" - ", 1)[-1].strip()
        if re.match(r'(?:Adv\.)?MS', candidate):
            return candidate

    return label.strip()


def extract_collection_from_shelfmark(shelfmark: str, default_collection: str) -> str:
    """
    Extract collection from NLS shelfmark.

    Examples:
        "Adv.MS.18.2.11"  -> "Advocates"
        "Adv.MS.72.1.2"   -> "Advocates"
        "MS.10270"         -> "NLS"
        "MS.16500"         -> "NLS"
    """
    if re.match(r'Adv\.', shelfmark):
        return "Advocates"

    if re.match(r'MS\.\d', shelfmark):
        return "NLS"

    return default_collection


def extract_thumbnail_url(manifest: dict) -> Optional[str]:
    """Extract thumbnail URL from manifest."""
    # Try manifest-level thumbnail
    thumb = manifest.get("thumbnail")
    if thumb:
        if isinstance(thumb, dict):
            return thumb.get("@id") or thumb.get("id")
        elif isinstance(thumb, list) and thumb:
            return thumb[0].get("@id") or thumb[0].get("id")

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


def parse_manifest(manifest_data: dict, manifest_url: str,
                   default_collection: str) -> Optional[dict]:
    """Parse an NLS IIIF manifest into a Compilatio record."""
    metadata = manifest_data.get("metadata", [])

    shelfmark = extract_shelfmark(manifest_data)
    if not shelfmark:
        return None

    record = {
        "shelfmark": shelfmark,
        "collection": extract_collection_from_shelfmark(shelfmark, default_collection),
        "iiif_manifest_url": manifest_url,
    }

    # Title / contents
    label = manifest_data.get("label", "")
    description = manifest_data.get("description", "")

    # Try metadata Title field first
    title = extract_metadata_value(metadata, "Title")
    if title:
        record["contents"] = title
    elif label:
        # Remove shelfmark from label to get title
        contents = re.sub(r'\s*-\s*(?:Adv\.)?MS\.?\s*[\d.,\s]+(?:v\.\s*\d+)?$', '', label).strip()
        if contents:
            record["contents"] = contents
        elif description:
            desc = re.sub(r'<[^>]+>', ' ', description)
            desc = re.sub(r'\s+', ' ', desc).strip()
            record["contents"] = desc[:500] if len(desc) > 500 else desc

    # Date
    for date_field in ["Date", "Date Range", "Published", "Date of Creation"]:
        date_str = extract_metadata_value(metadata, date_field)
        if date_str:
            record["date_display"] = date_str

            years = re.findall(r'\b(\d{4})\b', date_str)
            if len(years) >= 2:
                record["date_start"] = int(years[0])
                record["date_end"] = int(years[-1])
            elif len(years) == 1:
                record["date_start"] = int(years[0])
                record["date_end"] = int(years[0])
            else:
                century_matches = re.findall(
                    r'(\d{1,2})(?:st|nd|rd|th)\s*century',
                    date_str, re.IGNORECASE
                )
                if century_matches:
                    first = (int(century_matches[0]) - 1) * 100
                    last = (int(century_matches[-1]) - 1) * 100 + 99
                    record["date_start"] = first
                    record["date_end"] = last
            break

    # Language
    for lang_field in ["Language", "Language(s)", "Text Language"]:
        language = extract_metadata_value(metadata, lang_field)
        if language:
            record["language"] = language
            break

    # Provenance
    for prov_field in ["Provenance", "Origin", "Origin Place"]:
        prov = extract_metadata_value(metadata, prov_field)
        if prov:
            record["provenance"] = prov
            break

    # Extent
    for extent_field in ["Extent", "Folios", "Physical Description"]:
        extent = extract_metadata_value(metadata, extent_field)
        if extent:
            record["folios"] = extent
            break

    # Thumbnail
    record["thumbnail_url"] = extract_thumbnail_url(manifest_data)

    # Source URL
    record["source_url"] = manifest_url.replace("/manifest.json", "").replace("view.nls.uk/manifest", "digital.nls.uk/view")

    return record


# =============================================================================
# Database Operations
# =============================================================================

def ensure_repository(cursor) -> int:
    """Ensure NLS repository exists and return its ID."""
    cursor.execute(
        "SELECT id FROM repositories WHERE short_name = ?",
        ("NLS",)
    )
    row = cursor.fetchone()
    if row:
        return row[0]

    cursor.execute("""
        INSERT INTO repositories (name, short_name, logo_url, catalogue_url)
        VALUES (?, ?, ?, ?)
    """, (
        "National Library of Scotland",
        "NLS",
        None,
        "https://digital.nls.uk/early-manuscripts/"
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

def import_nls(
    db_path: Path,
    dry_run: bool = True,
    test_mode: bool = False,
    verbose: bool = False,
    limit: int = None,
):
    """Import NLS medieval manuscripts from IIIF collections."""
    if verbose:
        logger.setLevel(logging.DEBUG)

    if not db_path.exists():
        logger.error(f"Database not found: {db_path}")
        logger.info("Initialize the database first:")
        logger.info("  sqlite3 database/compilatio.db < database/schema.sql")
        return False

    # Step 1: Fetch collection manifest lists
    stubs_with_collections = fetch_all_manifests()
    logger.info(f"Found {len(stubs_with_collections)} unique manifests across all collections")

    if not stubs_with_collections:
        logger.error("No manifests found")
        return False

    # Apply limits
    if test_mode:
        stubs_with_collections = stubs_with_collections[:5]
        logger.info(f"Test mode: limiting to {len(stubs_with_collections)} manifests")
    elif limit:
        stubs_with_collections = stubs_with_collections[:limit]
        logger.info(f"Limiting to {limit} manifests")

    # Step 2: Fetch and parse each manifest
    records = []
    errors = 0

    for i, (stub, collection_name) in enumerate(stubs_with_collections):
        manifest_url = stub["@id"]

        logger.info(f"[{i+1}/{len(stubs_with_collections)}] Fetching {stub.get('label', manifest_url)}")

        manifest_data = fetch_json(manifest_url)
        if not manifest_data:
            errors += 1
            continue

        record = parse_manifest(manifest_data, manifest_url, collection_name)
        if record:
            records.append(record)
            logger.debug(f"  -> {record['shelfmark']} [{record['collection']}]")
        else:
            logger.warning(f"  -> Could not parse manifest")
            errors += 1

        if i < len(stubs_with_collections) - 1:
            time.sleep(REQUEST_DELAY)

        if (i + 1) % 25 == 0:
            logger.info(f"Progress: {i+1}/{len(stubs_with_collections)} manifests fetched, {len(records)} parsed")

    logger.info(f"Fetched {len(stubs_with_collections)} manifests, parsed {len(records)} records, {errors} errors")

    # Step 3: Database operations
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    repo_id = ensure_repository(cursor) if not dry_run else 1

    stats = {
        "manifests_fetched": len(stubs_with_collections),
        "records_parsed": len(records),
        "fetch_errors": errors,
        "inserted": 0,
        "updated": 0,
        "db_errors": 0,
    }

    results = {"inserted": [], "updated": []}

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
                        record.get("source_url"), existing_id,
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
                stats["db_errors"] += 1
                logger.error(f"Error importing {shelfmark}: {e}")

    if not dry_run:
        conn.commit()
    conn.close()

    # Print summary
    print("\n" + "=" * 70)
    print(f"{'DRY RUN - ' if dry_run else ''}NATIONAL LIBRARY OF SCOTLAND IMPORT SUMMARY")
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
        by_collection = {}
        for rec in results["inserted"]:
            col = rec.get("collection", "Unknown")
            by_collection.setdefault(col, []).append(rec)
        for col in sorted(by_collection.keys()):
            recs = by_collection[col]
            print(f"\n  {col} ({len(recs)}):")
            for rec in recs[:3]:
                date = f" ({rec.get('date_display', '')})" if rec.get('date_display') else ""
                print(f"    {rec['shelfmark']}{date}")
                if rec.get("contents"):
                    contents = rec["contents"][:60] + "..." if len(rec.get("contents", "")) > 60 else rec.get("contents", "")
                    print(f"      {contents}")
            if len(recs) > 3:
                print(f"    ... and {len(recs) - 3} more")

    if dry_run:
        print("\n" + "=" * 70)
        print("This was a DRY RUN. No changes were made to the database.")
        print("Run with --execute to apply changes.")
        print("=" * 70)

    return True


def main():
    parser = argparse.ArgumentParser(
        description="Import NLS medieval manuscripts from IIIF collections"
    )
    parser.add_argument('--execute', action='store_true',
                        help='Actually execute the import (default is dry-run)')
    parser.add_argument('--test', action='store_true',
                        help='Test mode: limit to first 5 manifests')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Show detailed logging')
    parser.add_argument('--db', type=Path, default=DB_PATH,
                        help=f'Path to database (default: {DB_PATH})')
    parser.add_argument('--limit', type=int, default=None,
                        help='Limit number of manifests to fetch')

    args = parser.parse_args()

    print("Compilatio National Library of Scotland Import Tool")
    print(f"Source: NLS IIIF Manuscript Collections")
    print(f"DB:   {args.db}")
    print(f"Mode: {'TEST' if args.test else 'EXECUTE' if args.execute else 'DRY-RUN'}")
    if args.limit:
        print(f"Limit: {args.limit}")
    print()

    success = import_nls(
        db_path=args.db, dry_run=not args.execute,
        test_mode=args.test, verbose=args.verbose, limit=args.limit,
    )
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
