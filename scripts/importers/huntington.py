#!/usr/bin/env python3
"""
Huntington Library Ellesmere Manuscript Import Script for Compilatio.

Imports digitized Ellesmere manuscripts from the Huntington Digital Library
via CONTENTdm API and IIIF manifests.

Two-phase process with checkpoint resumability:
  Phase 1 (Discovery): Query CONTENTdm API for mssEL items
  Phase 2 (Import): Fetch IIIF manifests, parse metadata, insert to database

Dependencies:
    Standard library only (no external packages required)

Source:
    https://hdl.huntington.org/digital/collection/p15150coll7

Usage:
    python scripts/importers/huntington.py                    # Dry-run mode
    python scripts/importers/huntington.py --execute          # Actually import
    python scripts/importers/huntington.py --resume --execute # Resume interrupted
    python scripts/importers/huntington.py --discover-only    # Only run discovery
    python scripts/importers/huntington.py --skip-discovery   # Use cached discovery
    python scripts/importers/huntington.py --test             # First 5 only
    python scripts/importers/huntington.py --verbose          # Detailed logging
"""

import argparse
import json
import logging
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

# =============================================================================
# Constants and Paths
# =============================================================================

PROJECT_ROOT = Path(__file__).parent.parent.parent
DB_PATH = PROJECT_ROOT / "database" / "compilatio.db"

# CONTENTdm API
COLLECTION_ID = "p15150coll7"
CONTENTDM_BASE = "https://hdl.huntington.org"

# Collection configurations
COLLECTIONS = {
    "EL": {
        "name": "Ellesmere",
        "search_term": "mssEL",
        "cache_file": "huntington_el_discovery.json",
        "progress_file": "huntington_el_progress.json",
    },
    "HM": {
        "name": "Huntington Manuscripts",
        "search_term": "mssHM",
        "cache_file": "huntington_hm_discovery.json",
        "progress_file": "huntington_hm_progress.json",
    },
}


def extract_shelfmark_number(shelfmark: str) -> Optional[int]:
    """
    Extract the primary numeric identifier from a shelfmark.

    Examples:
        "mssHM 1" -> 1
        "mssHM 946" -> 946
        "mssHM 719 vol. 01" -> 719
        "mssHM 80611 (13)" -> 80611
    """
    # Match pattern: mssHM followed by number
    match = re.search(r"mssHM\s+(\d+)", shelfmark)
    if match:
        return int(match.group(1))
    return None


def filter_by_shelfmark_range(
    items: list[dict],
    min_num: int,
    max_num: int,
) -> list[dict]:
    """Filter items to those with shelfmark numbers in the given range."""
    filtered = []
    for item in items:
        num = extract_shelfmark_number(item.get("shelfmark", ""))
        if num is not None and min_num <= num <= max_num:
            filtered.append(item)
    return filtered

def get_search_api(search_term: str) -> str:
    """Build CONTENTdm search API URL for a given search term."""
    return (
        f"{CONTENTDM_BASE}/digital/api/search/collection/{COLLECTION_ID}"
        f"/searchterm/{search_term}/field/callid/mode/exact/conn/and/maxRecords/1000"
    )

# IIIF endpoints
IIIF_MANIFEST_TEMPLATE = f"{CONTENTDM_BASE}/iiif/2/{COLLECTION_ID}:{{item_id}}/manifest.json"
VIEWER_URL_TEMPLATE = f"{CONTENTDM_BASE}/digital/collection/{COLLECTION_ID}/id/{{item_id}}"

# Rate limiting
REQUEST_DELAY = 0.5  # seconds between manifest fetches

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

USER_AGENT = "Compilatio/1.0 (Academic manuscript research; IIIF aggregator)"


# =============================================================================
# HTTP Helpers
# =============================================================================


def fetch_json(url: str, retries: int = 3) -> Optional[dict]:
    """Fetch a URL and parse as JSON with retry logic."""
    for attempt in range(retries):
        try:
            req = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (HTTPError, URLError, json.JSONDecodeError, TimeoutError, OSError) as e:
            if attempt < retries - 1:
                logger.debug(f"Retry {attempt + 1}/{retries} for {url}: {e}")
                time.sleep(2)
            else:
                logger.warning(f"Failed to fetch {url}: {e}")
                return None
        except Exception as e:
            logger.warning(f"Unexpected error fetching {url}: {e}")
            return None
    return None


# =============================================================================
# Phase 1: Discovery (CONTENTdm API)
# =============================================================================


def discover_manuscripts(search_term: str, collection_name: str) -> list[dict]:
    """
    Query CONTENTdm API for manuscripts matching the search term.

    Returns list of dicts with: item_id, shelfmark, title, date, thumbnail_url
    """
    search_api = get_search_api(search_term)
    logger.info(f"Querying CONTENTdm API: {search_api}")
    data = fetch_json(search_api)

    if not data:
        logger.error("Failed to fetch from CONTENTdm API")
        return []

    total = data.get("totalResults", 0)
    logger.info(f"Found {total} items in API response")

    items = []
    for record in data.get("items", []):
        item_id = record.get("itemId")
        if not item_id:
            continue

        # Extract metadata fields
        metadata = {}
        for field in record.get("metadataFields", []):
            key = field.get("field", "")
            value = field.get("value", "")
            if key and value:
                metadata[key] = value

        # Build item record
        item = {
            "item_id": item_id,
            "shelfmark": metadata.get("callid", f"mssEL {item_id}"),
            "title": metadata.get("title", ""),
            "date": metadata.get("date", ""),
            "thumbnail_url": record.get("thumbnailUri", ""),
        }

        # Normalize thumbnail URL
        if item["thumbnail_url"] and not item["thumbnail_url"].startswith("http"):
            item["thumbnail_url"] = CONTENTDM_BASE + item["thumbnail_url"]

        items.append(item)

    logger.info(f"Discovered {len(items)} {collection_name} manuscripts")
    return items


def save_discovery_cache(items: list[dict], cache_path: Path):
    """Save discovery results to JSON cache."""
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "w") as f:
        json.dump(items, f, indent=2)
    logger.info(f"Saved {len(items)} items to {cache_path}")


def load_discovery_cache(cache_path: Path) -> Optional[list[dict]]:
    """Load discovery results from JSON cache."""
    if not cache_path.exists():
        return None
    with open(cache_path) as f:
        items = json.load(f)
    logger.info(f"Loaded {len(items)} items from cache: {cache_path}")
    return items


# =============================================================================
# Progress/Checkpoint Management
# =============================================================================


def load_progress(progress_path: Path) -> dict:
    """Load progress from checkpoint file."""
    if not progress_path.exists():
        return {
            "last_updated": None,
            "total_discovered": 0,
            "completed_ids": [],
            "failed_ids": [],
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


def mark_completed(progress: dict, item_id: int, progress_path: Path):
    """Mark an item as completed and save checkpoint."""
    if item_id not in progress["completed_ids"]:
        progress["completed_ids"].append(item_id)
    if item_id in progress["failed_ids"]:
        progress["failed_ids"].remove(item_id)
    save_progress(progress, progress_path)


def mark_failed(progress: dict, item_id: int, progress_path: Path):
    """Mark an item as failed and save checkpoint."""
    if item_id not in progress["failed_ids"]:
        progress["failed_ids"].append(item_id)
    save_progress(progress, progress_path)


# =============================================================================
# Phase 2: IIIF Manifest Parsing
# =============================================================================


def extract_metadata_value(metadata: list[dict], label: str) -> Optional[str]:
    """Extract a value from the IIIF metadata array by label."""
    for entry in metadata:
        entry_label = entry.get("label", "")
        # Handle both string and dict labels
        if isinstance(entry_label, dict):
            entry_label = entry_label.get("@value", "")
        if isinstance(entry_label, list):
            # Some manifests have label as list of language variants
            for lbl in entry_label:
                if isinstance(lbl, dict):
                    entry_label = lbl.get("@value", "")
                    break
                elif isinstance(lbl, str):
                    entry_label = lbl
                    break

        if not isinstance(entry_label, str):
            continue

        if entry_label.lower().strip() == label.lower().strip():
            value = entry.get("value", "")
            if isinstance(value, list):
                # Join multiple values
                parts = []
                for v in value:
                    if isinstance(v, dict):
                        parts.append(v.get("@value", str(v)))
                    else:
                        parts.append(str(v))
                value = "; ".join(parts)
            if isinstance(value, dict):
                value = value.get("@value", str(value))
            # Strip HTML tags
            value = re.sub(r"<[^>]+>", " ", str(value))
            value = re.sub(r"\s+", " ", value).strip()
            return value if value else None

    return None


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


def parse_date(date_str: str) -> tuple[Optional[int], Optional[int]]:
    """Parse date string into (start_year, end_year)."""
    if not date_str:
        return None, None

    # Try explicit years: "1300-1400", "1350", "ca. 1410"
    years = re.findall(r"\b(\d{4})\b", date_str)
    if len(years) >= 2:
        return int(years[0]), int(years[-1])
    if len(years) == 1:
        return int(years[0]), int(years[0])

    # Century patterns: "15th century", "14th-15th century"
    century_matches = re.findall(
        r"(\d{1,2})(?:st|nd|rd|th)\s*century", date_str, re.IGNORECASE
    )
    if century_matches:
        first = (int(century_matches[0]) - 1) * 100
        last = (int(century_matches[-1]) - 1) * 100 + 99
        return first, last

    return None, None


def count_canvases(manifest: dict) -> int:
    """Count the number of canvases (pages/images) in a manifest."""
    sequences = manifest.get("sequences", [])
    if sequences:
        canvases = sequences[0].get("canvases", [])
        return len(canvases)
    return 0


def parse_manifest(
    manifest_data: dict,
    manifest_url: str,
    discovery_item: dict,
    collection_name: str,
) -> Optional[dict]:
    """
    Parse a Huntington IIIF manifest into a Compilatio record.

    Uses discovery data as fallback for missing manifest metadata.
    """
    metadata = manifest_data.get("metadata", [])

    # Shelfmark: prefer manifest "Call Number", fall back to discovery
    shelfmark = extract_metadata_value(metadata, "Call Number")
    if not shelfmark:
        shelfmark = discovery_item.get("shelfmark", "")
    if not shelfmark:
        logger.warning(f"No shelfmark found for {manifest_url}")
        return None

    record = {
        "shelfmark": shelfmark,
        "collection": collection_name,
        "iiif_manifest_url": manifest_url,
    }

    # Title / contents
    title = extract_metadata_value(metadata, "Title")
    if not title:
        title = manifest_data.get("label", "")
    if not title:
        title = discovery_item.get("title", "")
    if title:
        # Truncate if very long
        if len(title) > 1000:
            title = title[:997] + "..."
        record["contents"] = title

    # Date
    date_str = extract_metadata_value(metadata, "Date")
    if not date_str:
        date_str = discovery_item.get("date", "")
    if date_str:
        record["date_display"] = date_str
        start, end = parse_date(date_str)
        if start:
            record["date_start"] = start
        if end:
            record["date_end"] = end

    # Physical description / extent
    extent = extract_metadata_value(metadata, "Physical description")
    if extent:
        record["folios"] = extent

    # Language
    language = extract_metadata_value(metadata, "Language")
    if language:
        record["language"] = language

    # Provenance
    provenance = extract_metadata_value(metadata, "Provenance")
    if provenance:
        record["provenance"] = provenance

    # Thumbnail: prefer manifest, fall back to discovery
    thumb = extract_thumbnail_url(manifest_data)
    if not thumb:
        thumb = discovery_item.get("thumbnail_url")
    if thumb:
        record["thumbnail_url"] = thumb

    # Image count
    image_count = count_canvases(manifest_data)
    if image_count > 0:
        record["image_count"] = image_count

    # Source URL (viewer link)
    item_id = discovery_item.get("item_id")
    record["source_url"] = VIEWER_URL_TEMPLATE.format(item_id=item_id)

    return record


# =============================================================================
# Database Operations
# =============================================================================


def ensure_repository(cursor) -> int:
    """Ensure Huntington Library repository exists and return its ID."""
    cursor.execute(
        "SELECT id FROM repositories WHERE short_name = ?", ("Huntington",)
    )
    row = cursor.fetchone()
    if row:
        return row[0]

    cursor.execute(
        """
        INSERT INTO repositories (name, short_name, logo_url, catalogue_url)
        VALUES (?, ?, ?, ?)
    """,
        (
            "Huntington Library",
            "Huntington",
            None,
            "https://hdl.huntington.org/digital/collection/p15150coll7",
        ),
    )
    return cursor.lastrowid


def manuscript_exists(cursor, shelfmark: str, repo_id: int) -> Optional[int]:
    """Check if manuscript exists. Returns ID if found, None otherwise."""
    cursor.execute(
        "SELECT id FROM manuscripts WHERE shelfmark = ? AND repository_id = ?",
        (shelfmark, repo_id),
    )
    row = cursor.fetchone()
    return row[0] if row else None


# =============================================================================
# Main Import Logic
# =============================================================================


def import_huntington(
    db_path: Path,
    collection_key: str = "EL",
    dry_run: bool = True,
    test_mode: bool = False,
    verbose: bool = False,
    limit: int = None,
    discover_only: bool = False,
    skip_discovery: bool = False,
    resume: bool = False,
    min_shelfmark: int = None,
    max_shelfmark: int = None,
):
    """Import Huntington manuscripts for the specified collection."""
    if verbose:
        logger.setLevel(logging.DEBUG)

    # Get collection configuration
    if collection_key not in COLLECTIONS:
        logger.error(f"Unknown collection: {collection_key}. Valid: {list(COLLECTIONS.keys())}")
        return False

    collection_config = COLLECTIONS[collection_key]
    collection_name = collection_config["name"]
    search_term = collection_config["search_term"]
    discovery_cache_path = PROJECT_ROOT / "data" / collection_config["cache_file"]
    progress_path = PROJECT_ROOT / "data" / collection_config["progress_file"]

    logger.info(f"Importing {collection_name} collection (search: {search_term})")

    # Load or initialize progress
    progress = load_progress(progress_path) if resume else {
        "last_updated": None,
        "total_discovered": 0,
        "completed_ids": [],
        "failed_ids": [],
        "phase": "discovery",
    }

    # Phase 1: Discovery
    items = None
    if skip_discovery:
        items = load_discovery_cache(discovery_cache_path)
        if items is None:
            logger.error("No discovery cache found. Run without --skip-discovery first.")
            return False
    else:
        # Try cache first if resuming
        if resume:
            items = load_discovery_cache(discovery_cache_path)

        if items is None:
            logger.info("Running CONTENTdm API discovery...")
            items = discover_manuscripts(search_term, collection_name)
            if items:
                save_discovery_cache(items, discovery_cache_path)
                progress["total_discovered"] = len(items)
                progress["phase"] = "import"
                save_progress(progress, progress_path)

    if not items:
        logger.error("No items discovered")
        return False

    # Apply shelfmark range filter
    if min_shelfmark is not None or max_shelfmark is not None:
        min_num = min_shelfmark or 0
        max_num = max_shelfmark or 999999
        original_count = len(items)
        items = filter_by_shelfmark_range(items, min_num, max_num)
        logger.info(
            f"Filtered by shelfmark range {min_num}-{max_num}: "
            f"{original_count} -> {len(items)} items"
        )

    # Apply limits
    if test_mode:
        items = items[:5]
        logger.info("Test mode: limiting to 5 items")
    elif limit:
        items = items[:limit]
        logger.info(f"Limiting to {limit} items")

    logger.info(f"Processing {len(items)} {collection_name} manuscripts")

    if discover_only:
        print(f"\nDiscovery complete. {len(items)} manuscripts found.")
        print(f"Cache saved to: {discovery_cache_path}")
        return True

    # Phase 2: Fetch IIIF manifests and build records
    if not db_path.exists():
        logger.error(f"Database not found: {db_path}")
        logger.info("Initialize the database first:")
        logger.info("  sqlite3 database/compilatio.db < database/schema.sql")
        return False

    records = []
    fetch_errors = 0

    # Filter out already completed items if resuming
    if resume and progress["completed_ids"]:
        items_to_process = [
            item for item in items
            if item["item_id"] not in progress["completed_ids"]
        ]
        logger.info(
            f"Resuming: {len(progress['completed_ids'])} already completed, "
            f"{len(items_to_process)} remaining"
        )
    else:
        items_to_process = items

    for i, item in enumerate(items_to_process):
        item_id = item["item_id"]
        manifest_url = IIIF_MANIFEST_TEMPLATE.format(item_id=item_id)

        logger.info(
            f"[{i+1}/{len(items_to_process)}] "
            f"Fetching manifest for {item.get('shelfmark', item_id)}"
        )

        manifest_data = fetch_json(manifest_url)
        if not manifest_data:
            fetch_errors += 1
            mark_failed(progress, item_id, progress_path)
            continue

        record = parse_manifest(manifest_data, manifest_url, item, collection_name)
        if record:
            records.append(record)
            mark_completed(progress, item_id, progress_path)
            logger.debug(f"  -> {record['shelfmark']}")
        else:
            logger.warning(f"  -> Could not parse manifest for {item_id}")
            fetch_errors += 1
            mark_failed(progress, item_id, progress_path)

        # Rate limit
        if i < len(items_to_process) - 1:
            time.sleep(REQUEST_DELAY)

        # Progress logging
        if (i + 1) % 10 == 0:
            logger.info(
                f"Progress: {i+1}/{len(items_to_process)} manifests, "
                f"{len(records)} parsed"
            )

    logger.info(
        f"Fetched {len(items_to_process)} manifests, "
        f"parsed {len(records)} records, {fetch_errors} errors"
    )

    # Phase 3: Database operations
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    repo_id = ensure_repository(cursor) if not dry_run else 1

    stats = {
        "total_discovered": len(items),
        "manifests_fetched": len(items_to_process),
        "records_parsed": len(records),
        "fetch_errors": fetch_errors,
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
                (shelfmark,),
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
                    cursor.execute(
                        """
                        UPDATE manuscripts SET
                            collection = ?, date_display = ?, date_start = ?,
                            date_end = ?, contents = ?, provenance = ?,
                            language = ?, folios = ?, iiif_manifest_url = ?,
                            thumbnail_url = ?, source_url = ?, image_count = ?
                        WHERE id = ?
                    """,
                        (
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
                            record.get("image_count"),
                            existing_id,
                        ),
                    )
                    stats["updated"] += 1
                else:
                    cursor.execute(
                        """
                        INSERT INTO manuscripts (
                            repository_id, shelfmark, collection, date_display,
                            date_start, date_end, contents, provenance, language,
                            folios, iiif_manifest_url, thumbnail_url, source_url,
                            image_count
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                        (
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
                            record.get("image_count"),
                        ),
                    )
                    stats["inserted"] += 1

            except Exception as e:
                stats["db_errors"] += 1
                logger.error(f"Error importing {shelfmark}: {e}")

    if not dry_run:
        conn.commit()
    conn.close()

    # Print summary
    print("\n" + "=" * 70)
    print(
        f"{'DRY RUN - ' if dry_run else ''}"
        f"HUNTINGTON LIBRARY {collection_name.upper()} IMPORT SUMMARY"
    )
    print("=" * 70)
    print(f"\nDiscovery (CONTENTdm API):")
    print(f"  Total discovered:     {stats['total_discovered']}")
    print(f"\nIIIF Manifest Fetch:")
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
        for rec in results["inserted"][:10]:
            date = (
                f" ({rec.get('date_display', '')})"
                if rec.get("date_display")
                else ""
            )
            print(f"  {rec['shelfmark']}{date}")
            if rec.get("contents"):
                contents = rec["contents"]
                if len(contents) > 70:
                    contents = contents[:70] + "..."
                print(f"    {contents}")
        remaining = len(results["inserted"]) - 10
        if remaining > 0:
            print(f"  ... and {remaining} more")

    if dry_run:
        print("\n" + "=" * 70)
        print("This was a DRY RUN. No changes were made to the database.")
        print("Run with --execute to apply changes.")
        print("=" * 70)

    return True


# =============================================================================
# CLI
# =============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="Import Huntington Library manuscripts into Compilatio"
    )
    parser.add_argument(
        "--collection",
        "-c",
        type=str,
        default="EL",
        choices=list(COLLECTIONS.keys()),
        help="Collection to import: EL (Ellesmere) or HM (Huntington Manuscripts)",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually execute the import (default is dry-run)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from last checkpoint",
    )
    parser.add_argument(
        "--discover-only",
        action="store_true",
        help="Only run discovery phase, save to cache",
    )
    parser.add_argument(
        "--skip-discovery",
        action="store_true",
        help="Skip discovery, use cached data only",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Test mode: limit to first 5 manuscripts",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed logging",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DB_PATH,
        help=f"Path to database (default: {DB_PATH})",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of manuscripts to process",
    )
    parser.add_argument(
        "--min-shelfmark",
        type=int,
        default=None,
        help="Minimum shelfmark number to include (e.g., 1 for mssHM 1)",
    )
    parser.add_argument(
        "--max-shelfmark",
        type=int,
        default=None,
        help="Maximum shelfmark number to include (e.g., 946 for mssHM 946)",
    )

    args = parser.parse_args()

    collection_config = COLLECTIONS[args.collection]
    cache_path = PROJECT_ROOT / "data" / collection_config["cache_file"]

    print("Compilatio Huntington Library Import Tool")
    print(f"Source: Huntington Digital Library — {collection_config['name']}")
    print(f"DB:    {args.db}")
    print(f"Cache: {cache_path}")
    mode_parts = []
    if args.discover_only:
        mode_parts.append("DISCOVER-ONLY")
    elif args.test:
        mode_parts.append("TEST")
    elif args.execute:
        mode_parts.append("EXECUTE")
    else:
        mode_parts.append("DRY-RUN")
    if args.resume:
        mode_parts.append("RESUME")
    print(f"Mode:  {' + '.join(mode_parts)}")
    print(f"Collection: {args.collection} ({collection_config['name']})")
    if args.limit:
        print(f"Limit: {args.limit}")
    print()

    success = import_huntington(
        db_path=args.db,
        collection_key=args.collection,
        dry_run=not args.execute,
        test_mode=args.test,
        verbose=args.verbose,
        limit=args.limit,
        discover_only=args.discover_only,
        skip_discovery=args.skip_discovery,
        resume=args.resume,
        min_shelfmark=args.min_shelfmark,
        max_shelfmark=args.max_shelfmark,
    )
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
