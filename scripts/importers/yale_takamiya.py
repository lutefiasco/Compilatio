#!/usr/bin/env python3
"""
Yale Beinecke Takamiya Collection Import Script for Compilatio.

Imports digitized medieval manuscripts from the Takamiya Collection at
Yale's Beinecke Rare Book and Manuscript Library via their JSON API
and IIIF manifests.

The Takamiya Collection comprises 139 medieval manuscripts (primarily English)
acquired from Professor Toshiyuki Takamiya in 2017.

No browser needed — pure HTTP/JSON.

Source:
    Catalog: https://collections.library.yale.edu/catalog?q=takamiya
    API: https://collections.library.yale.edu/catalog.json?q=takamiya
    Manifests: https://collections.library.yale.edu/manifests/{id}

Usage:
    python scripts/importers/yale_takamiya.py                    # Dry-run mode
    python scripts/importers/yale_takamiya.py --execute          # Actually import
    python scripts/importers/yale_takamiya.py --test             # First 5 only
    python scripts/importers/yale_takamiya.py --verbose          # Detailed logging
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

# Yale endpoints
CATALOG_API = "https://collections.library.yale.edu/catalog.json"
MANIFEST_BASE = "https://collections.library.yale.edu/manifests"
CATALOG_BASE = "https://collections.library.yale.edu/catalog"

# Rate limiting
REQUEST_DELAY = 0.3  # seconds between manifest fetches

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

def fetch_json(url: str, retries: int = 3) -> Optional[dict]:
    """Fetch a URL and parse as JSON with retry logic."""
    for attempt in range(retries):
        try:
            req = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (HTTPError, URLError, json.JSONDecodeError, TimeoutError) as e:
            if attempt < retries - 1:
                logger.debug(f"Retry {attempt + 1}/{retries} for {url}: {e}")
                time.sleep(1)
            else:
                logger.warning(f"Failed to fetch {url}: {e}")
                return None
    return None


# =============================================================================
# Discovery via JSON API
# =============================================================================

def discover_manuscripts(
    test_mode: bool = False,
    limit: int = None,
) -> list[dict]:
    """
    Discover Takamiya manuscripts via Yale's JSON catalog API.

    Returns list of dicts with: id, title, shelfmark, date, image_count
    """
    manuscripts = []
    page = 1
    per_page = 100

    while True:
        url = f"{CATALOG_API}?q=takamiya&per_page={per_page}&page={page}"
        logger.info(f"Fetching catalog page {page}...")

        data = fetch_json(url)
        if not data:
            logger.error(f"Failed to fetch catalog page {page}")
            break

        items = data.get("data", [])
        if not items:
            break

        for item in items:
            item_id = item.get("id")
            if not item_id:
                continue

            attrs = item.get("attributes", {})

            # Extract shelfmark from callNumber_tesim
            call_number_obj = attrs.get("callNumber_tesim", {})
            if isinstance(call_number_obj, dict):
                call_number_attrs = call_number_obj.get("attributes", {})
                raw_shelfmark = call_number_attrs.get("value", "")
            else:
                raw_shelfmark = str(call_number_obj) if call_number_obj else ""

            # Clean HTML tags from shelfmark
            shelfmark = re.sub(r"<[^>]+>", "", raw_shelfmark).strip()
            if not shelfmark:
                continue

            # Extract other fields
            title = attrs.get("title", "")

            date_obj = attrs.get("date_ssim", {})
            if isinstance(date_obj, dict):
                date_attrs = date_obj.get("attributes", {})
                date_display = date_attrs.get("value", "")
            else:
                date_display = str(date_obj) if date_obj else ""

            image_count_obj = attrs.get("imageCount_isi", {})
            if isinstance(image_count_obj, dict):
                ic_attrs = image_count_obj.get("attributes", {})
                image_count = ic_attrs.get("value", 0)
            else:
                image_count = image_count_obj if image_count_obj else 0

            try:
                image_count = int(image_count)
            except (ValueError, TypeError):
                image_count = 0

            manuscripts.append({
                "id": item_id,
                "shelfmark": shelfmark,
                "title": title,
                "date_display": date_display,
                "image_count": image_count,
            })

        # Check pagination
        meta = data.get("meta", {}).get("pages", {})
        total_pages = meta.get("total_pages", 1)
        current_page = meta.get("current_page", 1)

        logger.info(f"  Found {len(items)} items (total so far: {len(manuscripts)})")

        if current_page >= total_pages:
            break

        # Apply limits
        if test_mode and len(manuscripts) >= 5:
            break
        if limit and len(manuscripts) >= limit:
            break

        page += 1
        time.sleep(0.5)

    logger.info(f"Discovery complete: {len(manuscripts)} manuscripts found")

    # Apply final limits
    if test_mode:
        manuscripts = manuscripts[:5]
    elif limit:
        manuscripts = manuscripts[:limit]

    return manuscripts


# =============================================================================
# IIIF v3 Manifest Parsing
# =============================================================================

def get_label_value(label_obj) -> str:
    """Extract string value from IIIF v3 label object."""
    if not label_obj:
        return ""
    if isinstance(label_obj, str):
        return label_obj
    if isinstance(label_obj, dict):
        # v3 format: {"none": ["value"]} or {"en": ["value"]}
        for lang in ["none", "en", "@value"]:
            if lang in label_obj:
                val = label_obj[lang]
                if isinstance(val, list):
                    return val[0] if val else ""
                return str(val)
        # Fallback: first value found
        for val in label_obj.values():
            if isinstance(val, list):
                return val[0] if val else ""
            return str(val)
    if isinstance(label_obj, list):
        return label_obj[0] if label_obj else ""
    return str(label_obj)


def extract_v3_metadata_value(metadata: list, label: str) -> Optional[str]:
    """Extract a value from IIIF v3 metadata array by label."""
    if not metadata:
        return None

    for entry in metadata:
        entry_label = get_label_value(entry.get("label", {}))
        if entry_label.lower().strip() == label.lower().strip():
            value = get_label_value(entry.get("value", {}))
            if value:
                # Strip HTML tags
                value = re.sub(r"<[^>]+>", " ", value)
                value = re.sub(r"\s+", " ", value).strip()
                return value if value else None
    return None


def extract_v3_thumbnail_url(manifest: dict) -> Optional[str]:
    """Extract thumbnail URL from IIIF v3 manifest."""
    # Try manifest-level thumbnail
    thumbnails = manifest.get("thumbnail", [])
    if thumbnails:
        if isinstance(thumbnails, list) and thumbnails:
            thumb = thumbnails[0]
            if isinstance(thumb, dict):
                return thumb.get("id")
        elif isinstance(thumbnails, dict):
            return thumbnails.get("id")

    # Fall back to first canvas image
    items = manifest.get("items", [])  # v3 uses 'items' not 'sequences'
    if items:
        canvas = items[0]
        canvas_items = canvas.get("items", [])
        if canvas_items:
            anno_page = canvas_items[0]
            annotations = anno_page.get("items", [])
            if annotations:
                annotation = annotations[0]
                body = annotation.get("body", {})
                if isinstance(body, dict):
                    service = body.get("service", [])
                    if service:
                        svc = service[0] if isinstance(service, list) else service
                        svc_id = svc.get("id") or svc.get("@id")
                        if svc_id:
                            return f"{svc_id}/full/200,/0/default.jpg"
                    # Fallback to body id with size modification
                    body_id = body.get("id")
                    if body_id:
                        # Try to modify IIIF image URL for thumbnail size
                        return re.sub(r"/full/[^/]+/", "/full/200,/", body_id)

    return None


def count_v3_canvases(manifest: dict) -> int:
    """Count the number of canvases in a IIIF v3 manifest."""
    items = manifest.get("items", [])
    return len(items)


def parse_date(date_str: str) -> tuple[Optional[int], Optional[int]]:
    """Parse date string into (start_year, end_year)."""
    if not date_str:
        return None, None

    # Clean brackets
    date_str = re.sub(r"[\[\]]", "", date_str)

    # Try explicit years: "1300-1400", "ca. 1350", "between 1400 and 1450"
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


def parse_manifest(manifest_data: dict, manifest_url: str, discovery_item: dict) -> Optional[dict]:
    """
    Parse a Yale IIIF v3 manifest into a Compilatio record.

    Uses discovery data as fallback for missing manifest metadata.
    """
    metadata = manifest_data.get("metadata", [])

    # Shelfmark from discovery (preferred)
    shelfmark = discovery_item.get("shelfmark")
    if not shelfmark:
        logger.warning(f"No shelfmark for {manifest_url}")
        return None

    record = {
        "shelfmark": shelfmark,
        "collection": "Takamiya",
        "iiif_manifest_url": manifest_url,
    }

    # Title / contents
    title = get_label_value(manifest_data.get("label", {}))
    if not title:
        title = discovery_item.get("title")
    if title:
        # Truncate if very long
        if len(title) > 1000:
            title = title[:997] + "..."
        record["contents"] = title

    # Date
    date_display = extract_v3_metadata_value(metadata, "Published/Created Date")
    if not date_display:
        date_display = extract_v3_metadata_value(metadata, "Date")
    if not date_display:
        date_display = discovery_item.get("date_display")
    if date_display:
        record["date_display"] = date_display
        start, end = parse_date(date_display)
        if start:
            record["date_start"] = start
        if end:
            record["date_end"] = end

    # Language
    language = extract_v3_metadata_value(metadata, "Language")
    if language:
        record["language"] = language

    # Physical description / extent
    extent = extract_v3_metadata_value(metadata, "Extent")
    if extent:
        record["folios"] = extent

    # Provenance
    provenance = extract_v3_metadata_value(metadata, "Provenance")
    if provenance:
        record["provenance"] = provenance

    # Thumbnail
    thumb = extract_v3_thumbnail_url(manifest_data)
    if thumb:
        record["thumbnail_url"] = thumb

    # Image count
    image_count = count_v3_canvases(manifest_data)
    if image_count > 0:
        record["image_count"] = image_count
    elif discovery_item.get("image_count"):
        record["image_count"] = discovery_item["image_count"]

    # Source URL (catalog page)
    catalog_id = discovery_item.get("id")
    record["source_url"] = f"{CATALOG_BASE}/{catalog_id}"

    return record


# =============================================================================
# Database Operations
# =============================================================================

def ensure_repository(cursor) -> int:
    """Ensure Yale Beinecke repository exists and return its ID."""
    cursor.execute(
        "SELECT id FROM repositories WHERE short_name = ?",
        ("Yale",)
    )
    row = cursor.fetchone()
    if row:
        return row[0]

    cursor.execute("""
        INSERT INTO repositories (name, short_name, logo_url, catalogue_url)
        VALUES (?, ?, ?, ?)
    """, (
        "Beinecke Rare Book and Manuscript Library, Yale University",
        "Yale",
        None,
        "https://beinecke.library.yale.edu/collections/curatorial-areas/early-books-and-manuscripts/takamiya-deposit"
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

def import_yale_takamiya(
    db_path: Path,
    dry_run: bool = True,
    test_mode: bool = False,
    verbose: bool = False,
    limit: int = None,
):
    """Import Yale Beinecke Takamiya Collection manuscripts."""
    if verbose:
        logger.setLevel(logging.DEBUG)

    if not db_path.exists():
        logger.error(f"Database not found: {db_path}")
        logger.info("Initialize the database first:")
        logger.info("  sqlite3 database/compilatio.db < database/schema.sql")
        return False

    # Step 1: Discover manuscripts via JSON API
    items = discover_manuscripts(test_mode=test_mode, limit=limit)
    if not items:
        logger.error("No manuscripts discovered")
        return False

    # Step 2: Fetch and parse each manifest
    records = []
    errors = 0

    for i, item in enumerate(items):
        catalog_id = item["id"]
        manifest_url = f"{MANIFEST_BASE}/{catalog_id}"

        logger.info(f"[{i+1}/{len(items)}] Fetching manifest for {item['shelfmark']}")

        manifest_data = fetch_json(manifest_url)
        if not manifest_data:
            errors += 1
            continue

        record = parse_manifest(manifest_data, manifest_url, item)
        if record:
            records.append(record)
            logger.debug(f"  -> {record['shelfmark']}")
        else:
            logger.warning(f"  -> Could not parse manifest for {catalog_id}")
            errors += 1

        # Rate limit
        if i < len(items) - 1:
            time.sleep(REQUEST_DELAY)

        # Progress logging
        if (i + 1) % 25 == 0:
            logger.info(f"Progress: {i+1}/{len(items)} manifests, {len(records)} parsed")

    logger.info(f"Fetched {len(items)} manifests, parsed {len(records)} records, {errors} errors")

    # Step 3: Database operations
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    repo_id = ensure_repository(cursor) if not dry_run else 1

    stats = {
        "discovered": len(items),
        "manifests_fetched": len(items),
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
                            source_url = ?,
                            image_count = ?
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
                        record.get("image_count"),
                        existing_id,
                    ))
                    stats["updated"] += 1
                else:
                    cursor.execute("""
                        INSERT INTO manuscripts (
                            repository_id, shelfmark, collection, date_display,
                            date_start, date_end, contents, provenance, language,
                            folios, iiif_manifest_url, thumbnail_url, source_url,
                            image_count
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        record.get("image_count"),
                    ))
                    stats["inserted"] += 1

            except Exception as e:
                stats["db_errors"] += 1
                logger.error(f"Error importing {shelfmark}: {e}")

    if not dry_run:
        conn.commit()
    conn.close()

    # Print summary
    print_summary(stats, results, dry_run)
    return True


def print_summary(stats: dict, results: dict, dry_run: bool):
    """Print import summary report."""
    print("\n" + "=" * 70)
    print(f"{'DRY RUN - ' if dry_run else ''}YALE BEINECKE TAKAMIYA IMPORT SUMMARY")
    print("=" * 70)

    print(f"\nDiscovery:")
    print(f"  Manuscripts found:    {stats['discovered']}")

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
            date = f" ({rec.get('date_display', '')})" if rec.get('date_display') else ""
            print(f"  {rec['shelfmark']}{date}")
            if rec.get("contents"):
                contents = rec["contents"]
                if len(contents) > 65:
                    contents = contents[:62] + "..."
                print(f"    {contents}")
        remaining = len(results["inserted"]) - 10
        if remaining > 0:
            print(f"  ... and {remaining} more")

    if results.get("updated"):
        print("\n" + "-" * 70)
        print(f"RECORDS TO {'UPDATE' if dry_run else 'UPDATED'}:")
        print("-" * 70)
        for rec in results["updated"][:5]:
            print(f"  {rec['shelfmark']}")
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
        description="Import Yale Beinecke Takamiya Collection manuscripts"
    )
    parser.add_argument(
        '--execute',
        action='store_true',
        help='Actually execute the import (default is dry-run)'
    )
    parser.add_argument(
        '--test',
        action='store_true',
        help='Test mode: limit to first 5 manuscripts'
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
        help='Limit number of manuscripts to import'
    )

    args = parser.parse_args()

    print("Compilatio Yale Beinecke Takamiya Import Tool")
    print(f"Source: Yale Digital Collections (Takamiya Collection)")
    print(f"DB:     {args.db}")
    print(f"Mode:   {'TEST' if args.test else 'EXECUTE' if args.execute else 'DRY-RUN'}")
    if args.limit:
        print(f"Limit:  {args.limit}")
    print()

    success = import_yale_takamiya(
        db_path=args.db,
        dry_run=not args.execute,
        test_mode=args.test,
        verbose=args.verbose,
        limit=args.limit,
    )

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
