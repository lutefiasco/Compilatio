#!/usr/bin/env python3
"""
Durham University Library Manuscript Import Script for Compilatio.

Imports digitized medieval manuscripts from Durham's IIIF collection tree.
Recursively crawls sub-collections to find individual manifests,
then fetches each manifest for metadata.

No browser needed — pure HTTP/JSON (IIIF Presentation API 2.0).

Source:
    IIIF root: https://iiif.durham.ac.uk/manifests/trifle/collection/index
    Viewer: https://iiif.durham.ac.uk/index.html?manifest={URL}

Usage:
    python scripts/importers/durham.py                    # Dry-run mode
    python scripts/importers/durham.py --execute          # Actually import
    python scripts/importers/durham.py --test             # First 5 only
    python scripts/importers/durham.py --verbose          # Detailed logging
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

# Durham IIIF endpoints
COLLECTION_ROOT = "https://iiif.durham.ac.uk/manifests/trifle/collection/index"
VIEWER_BASE = "https://iiif.durham.ac.uk/index.html"

# Target collections containing medieval manuscripts
# (collection URL suffix -> collection label for filtering)
TARGET_COLLECTIONS = [
    "https://iiif.durham.ac.uk/manifests/trifle/collection/32150/t2c7m01bk68j",  # Cathedral Library MS books
    "https://iiif.durham.ac.uk/manifests/trifle/collection/32150/t2c8623hx722",  # Hunter MSS
    "https://iiif.durham.ac.uk/manifests/trifle/collection/32150/t2c6682x3943",  # Cathedral Add MSS
    "https://iiif.durham.ac.uk/manifests/trifle/collection/32150/t1c08612n52t",  # Cosin MSS
    "https://iiif.durham.ac.uk/manifests/trifle/collection/32150/t2cqn59q396k",  # Bamburgh Library
]

# Rate limiting
REQUEST_DELAY = 0.3  # seconds between requests

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
# Collection Crawling
# =============================================================================

def crawl_collection(url: str, depth: int = 0, max_depth: int = 5) -> list[dict]:
    """
    Recursively crawl an IIIF collection tree and return all manifest stubs.

    Each stub has: @id, label
    """
    if depth > max_depth:
        return []

    data = fetch_json(url)
    if not data:
        return []

    indent = "  " * depth
    label = data.get("label", "")
    manifests = data.get("manifests", [])
    sub_collections = data.get("collections", [])

    logger.debug(f"{indent}Collection: {label} ({len(manifests)} manifests, {len(sub_collections)} sub-collections)")

    result = []

    # Collect manifests at this level
    for m in manifests:
        if m.get("@type") == "sc:Manifest":
            result.append({
                "@id": m["@id"],
                "label": m.get("label", ""),
            })

    # Recurse into sub-collections
    for c in sub_collections:
        if c.get("@type") == "sc:Collection":
            time.sleep(REQUEST_DELAY)
            result.extend(crawl_collection(c["@id"], depth + 1, max_depth))

    return result


def fetch_all_manifests() -> list[dict]:
    """Crawl all target collections and return combined manifest list."""
    all_manifests = []
    seen_ids = set()

    for collection_url in TARGET_COLLECTIONS:
        logger.info(f"Crawling collection: {collection_url}")
        manifests = crawl_collection(collection_url)

        for m in manifests:
            mid = m["@id"]
            if mid not in seen_ids:
                seen_ids.add(mid)
                all_manifests.append(m)

        logger.info(f"  Found {len(manifests)} manifests (total unique: {len(all_manifests)})")

    return all_manifests


# =============================================================================
# Manifest Parsing
# =============================================================================

def extract_shelfmark_from_label(label: str, stub_label: str = None) -> Optional[str]:
    """
    Extract shelfmark from Durham manifest label or collection stub label.

    Durham labels come in two formats:
        Collection stub:  "Durham Cathedral Library MS A.I.3 - Title"
        Manifest label:   "Title - Cosin MS. B.i.5"  or just "Title"

    We try the stub label first (more reliable), then fall back to manifest label.
    """
    # Known shelfmark patterns
    shelfmark_re = re.compile(
        r'(Durham Cathedral Library MS\.?\s*[\w.]+(?:\s*[\w.]+)*'
        r'|DCL (?:MS\.?\s*)?[\w.]+(?:\s*[\w.]+)*'
        r'|Cosin MS\.?\s*[\w.]+(?:\s*[\w.]+)*'
        r'|DCL Hunter MS\.?\s*\d+'
        r'|CADD\s*\d+'
        r'|Bamburgh\s+[\w.]+(?:\s*[\w.]+)*)',
        re.IGNORECASE
    )

    # Try stub label first (from collection listing)
    for text in [stub_label, label]:
        if not text:
            continue

        match = shelfmark_re.search(text)
        if match:
            shelfmark = match.group(0).strip()
            # Normalize "Durham Cathedral Library" prefix
            shelfmark = shelfmark.replace("Durham Cathedral Library ", "DCL ")
            return shelfmark

    # Last resort: if label has " - ", try both sides
    if label and " - " in label:
        parts = label.split(" - ", 1)
        for part in parts:
            part = part.strip().replace("Durham Cathedral Library ", "DCL ")
            if re.match(r'^(DCL|Cosin|CADD|Bamburgh)', part, re.IGNORECASE):
                return part

    return None


def extract_collection_from_shelfmark(shelfmark: str) -> str:
    """
    Extract collection name from a Durham shelfmark.

    Examples:
        "DCL MS A.I.3"      -> "Cathedral A"
        "DCL MS B.II.1"     -> "Cathedral B"
        "DCL MS C.III.1"    -> "Cathedral C"
        "DCL Hunter MS 100" -> "Hunter"
        "Cosin MS V.i.1"    -> "Cosin"
        "Bamburgh ..."      -> "Bamburgh"
        "CADD 244"          -> "Cathedral Additional"
    """
    patterns = [
        (r'^DCL MS\.?\s*A\.', "Cathedral A"),
        (r'^DCL MS\.?\s*B\.', "Cathedral B"),
        (r'^DCL MS\.?\s*C\.', "Cathedral C"),
        (r'^DCL (?:MS\.?\s*)?Hunter', "Hunter"),
        (r'^Cosin MS', "Cosin"),
        (r'^CADD', "Cathedral Additional"),
        (r'^Bamburgh', "Bamburgh"),
    ]

    for pattern, collection in patterns:
        if re.match(pattern, shelfmark, re.IGNORECASE):
            return collection

    # Fallback
    parts = shelfmark.split()
    if parts:
        return parts[0]

    return "Unknown"


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
            # Strip HTML tags
            value = re.sub(r'<[^>]+>', ' ', str(value))
            value = re.sub(r'\s+', ' ', value).strip()
            return value if value else None
    return None


def extract_thumbnail_url(manifest: dict) -> Optional[str]:
    """Derive thumbnail URL from first canvas image service."""
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
                   stub_label: str = None) -> Optional[dict]:
    """Parse a Durham IIIF manifest into a Compilatio record."""
    label = manifest_data.get("label", "")
    metadata = manifest_data.get("metadata", [])
    description = manifest_data.get("description", "")

    # Extract shelfmark (try stub label first, then manifest label)
    shelfmark = extract_shelfmark_from_label(label, stub_label)
    if not shelfmark:
        logger.debug(f"No shelfmark found in {manifest_url}")
        return None

    record = {
        "shelfmark": shelfmark,
        "collection": extract_collection_from_shelfmark(shelfmark),
        "iiif_manifest_url": manifest_url,
    }

    # Contents: extract title (the non-shelfmark part of the label)
    title = None
    for text in [stub_label, label]:
        if text and " - " in text:
            parts = text.split(" - ", 1)
            # The part that doesn't contain the shelfmark is the title
            for part in parts:
                if shelfmark not in part.replace("Durham Cathedral Library ", "DCL "):
                    title = part.strip()
                    break
            if title:
                break

    if title:
        record["contents"] = title
    elif label and shelfmark not in label:
        record["contents"] = label.strip()
    elif description:
        # Use first 500 chars of description
        desc = re.sub(r'<[^>]+>', ' ', description)
        desc = re.sub(r'\s+', ' ', desc).strip()
        if desc:
            record["contents"] = desc[:500] if len(desc) > 500 else desc

    # Date from metadata "Published" field
    date_str = extract_metadata_value(metadata, "Published")
    if date_str:
        record["date_display"] = date_str

        # Try to extract years
        years = re.findall(r'\b(\d{4})\b', date_str)
        if len(years) >= 2:
            record["date_start"] = int(years[0])
            record["date_end"] = int(years[-1])
        elif len(years) == 1:
            record["date_start"] = int(years[0])
            record["date_end"] = int(years[0])
        else:
            # Century patterns
            century_matches = re.findall(
                r'(\d{1,2})(?:st|nd|rd|th)\s*century',
                date_str, re.IGNORECASE
            )
            if century_matches:
                first = (int(century_matches[0]) - 1) * 100
                last = (int(century_matches[-1]) - 1) * 100 + 99
                record["date_start"] = first
                record["date_end"] = last

    # Author from metadata
    author = extract_metadata_value(metadata, "Author")
    if author and "contents" in record:
        record["contents"] = f"{author}: {record['contents']}"
    elif author:
        record["contents"] = author

    # Thumbnail
    record["thumbnail_url"] = extract_thumbnail_url(manifest_data)

    # Source URL: use related field if available, else construct viewer URL
    related = manifest_data.get("related", [])
    if isinstance(related, list) and related:
        for rel in related:
            if isinstance(rel, dict):
                source = rel.get("@id", "")
                if source:
                    record["source_url"] = source
                    break
    elif isinstance(related, dict):
        record["source_url"] = related.get("@id", "")

    if "source_url" not in record:
        record["source_url"] = f"{VIEWER_BASE}?manifest={manifest_url}"

    return record


# =============================================================================
# Database Operations
# =============================================================================

def ensure_repository(cursor) -> int:
    """Ensure Durham University Library repository exists and return its ID."""
    cursor.execute(
        "SELECT id FROM repositories WHERE short_name = ?",
        ("Durham",)
    )
    row = cursor.fetchone()
    if row:
        return row[0]

    cursor.execute("""
        INSERT INTO repositories (name, short_name, logo_url, catalogue_url)
        VALUES (?, ?, ?, ?)
    """, (
        "Durham University Library",
        "Durham",
        "https://iiif.durham.ac.uk/images/logos/duruni_logo.png",
        "https://iiif.durham.ac.uk/index.html"
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

def import_durham(
    db_path: Path,
    dry_run: bool = True,
    test_mode: bool = False,
    verbose: bool = False,
    limit: int = None,
):
    """Import Durham medieval manuscripts from IIIF collection tree."""
    if verbose:
        logger.setLevel(logging.DEBUG)

    if not db_path.exists():
        logger.error(f"Database not found: {db_path}")
        logger.info("Initialize the database first:")
        logger.info("  sqlite3 database/compilatio.db < database/schema.sql")
        return False

    # Step 1: Crawl collection tree
    logger.info("Crawling Durham IIIF collection tree...")
    stubs = fetch_all_manifests()
    logger.info(f"Found {len(stubs)} unique manifests across target collections")

    if not stubs:
        logger.error("No manifests found")
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

        logger.info(f"[{i+1}/{len(stubs)}] Fetching {stub.get('label', manifest_url)}")

        manifest_data = fetch_json(manifest_url)
        if not manifest_data:
            errors += 1
            continue

        record = parse_manifest(manifest_data, manifest_url, stub_label=stub.get("label", ""))
        if record:
            records.append(record)
            logger.debug(f"  -> {record['shelfmark']} [{record['collection']}]")
        else:
            logger.warning(f"  -> Could not parse manifest")
            errors += 1

        # Rate limit
        if i < len(stubs) - 1:
            time.sleep(REQUEST_DELAY)

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
    print(f"{'DRY RUN - ' if dry_run else ''}DURHAM UNIVERSITY LIBRARY IMPORT SUMMARY")
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
        description="Import Durham medieval manuscripts from IIIF collection tree"
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

    print("Compilatio Durham University Library Import Tool")
    print(f"Source: Durham IIIF Collection Tree (medieval manuscripts)")
    print(f"DB:   {args.db}")
    print(f"Mode: {'TEST' if args.test else 'EXECUTE' if args.execute else 'DRY-RUN'}")
    if args.limit:
        print(f"Limit: {args.limit}")
    print()

    success = import_durham(
        db_path=args.db, dry_run=not args.execute,
        test_mode=args.test, verbose=args.verbose, limit=args.limit,
    )
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
