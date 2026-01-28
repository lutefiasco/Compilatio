#!/usr/bin/env python3
"""
British Library Manuscript Import Script for Compilatio.

Imports digitized medieval manuscripts from the British Library catalogue
(searcharchives.bl.uk). Filters to items with digital surrogates only.

The BL catalogue uses JavaScript to render search results, so this script
uses Playwright for browser-based scraping.

Supported collections:
- Cotton Collection
- Harley Collection
- Royal Collection

Requirements:
- playwright
- beautifulsoup4

First-time setup:
    pip install playwright beautifulsoup4
    playwright install chromium

Usage:
    python scripts/importers/british_library.py --collection cotton          # Dry-run
    python scripts/importers/british_library.py --collection cotton --execute
    python scripts/importers/british_library.py --collection harley --execute
    python scripts/importers/british_library.py --collection royal --execute
    python scripts/importers/british_library.py --collection cotton --test   # First page only
"""

import argparse
import asyncio
import logging
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus, urljoin

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, Page, Browser

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
DB_PATH = PROJECT_ROOT / "database" / "compilatio.db"

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================

BL_BASE_URL = "https://searcharchives.bl.uk"
BL_CATALOG_BASE = f"{BL_BASE_URL}/catalog"
IIIF_BASE_URL = "https://bl.digirati.io/iiif"

# Collection configurations
COLLECTIONS = {
    "cotton": {
        "name": "Cotton Collection",
        "search_param": "Cotton Collection",
        "shelfmark_prefix": "Cotton MS",
    },
    "harley": {
        "name": "Harley Collection",
        "search_param": "Harley Collection",
        "shelfmark_prefix": "Harley MS",
    },
    "royal": {
        "name": "Royal Collection",
        "search_param": "Royal Collection",
        "shelfmark_prefix": "Royal MS",
    },
}

# Rate limiting
REQUEST_DELAY = 2.5  # seconds between requests

# Field mapping from BL catalogue to Compilatio schema
FIELD_MAPPING = {
    "Reference (shelfmark)": "shelfmark",
    "Title": "title",
    "Date Range": "date_display",
    "Start Date": "date_start",
    "End Date": "date_end",
    "Languages": "language",
    "Extent": "folios",
    "Scope & Content": "contents",
    "Custodial History": "provenance",
    "Provenance": "provenance",
}


# =============================================================================
# URL Building
# =============================================================================

def build_search_url(collection_key: str, page: int = 1, per_page: int = 100) -> str:
    """
    Build search URL for a collection with digitized-only filter.

    Uses Rails-style array parameters for Blacklight.
    """
    collection = COLLECTIONS[collection_key]

    params = [
        f"f[collection_area_ssi][]={quote_plus('Western Manuscripts')}",
        f"f[project_collections_ssim][]={quote_plus(collection['search_param'])}",
        # Digitized-only filter: url_non_blank_si = Yes (available)
        f"f[url_non_blank_si][]={quote_plus('Yes (available)')}",
        f"per_page={per_page}",
    ]

    if page > 1:
        params.append(f"page={page}")

    return f"{BL_BASE_URL}/?{'&'.join(params)}"


def build_detail_url(catalog_id: str) -> str:
    """Build URL for a manuscript detail page."""
    return f"{BL_CATALOG_BASE}/{catalog_id}"


# =============================================================================
# Browser-based Scraping
# =============================================================================

class BLScraper:
    """Browser-based scraper for British Library catalogue."""

    def __init__(self, headless: bool = True, delay: float = REQUEST_DELAY):
        self.headless = headless
        self.delay = delay
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
        self._last_request = 0.0

    async def __aenter__(self):
        playwright = await async_playwright().start()
        self.browser = await playwright.chromium.launch(headless=self.headless)
        self.page = await self.browser.new_page()
        await self.page.set_extra_http_headers({
            "User-Agent": "Compilatio/1.0 (Academic manuscript research; IIIF aggregator)"
        })
        return self

    async def __aexit__(self, *args):
        if self.browser:
            await self.browser.close()

    async def _rate_limit(self):
        """Enforce delay between requests."""
        elapsed = time.time() - self._last_request
        if elapsed < self.delay:
            await asyncio.sleep(self.delay - elapsed)
        self._last_request = time.time()

    async def get_page(self, url: str, wait_for: str = "#documents") -> Optional[str]:
        """
        Navigate to URL and return rendered HTML.

        Args:
            url: URL to fetch
            wait_for: CSS selector to wait for (indicates page loaded)

        Returns:
            HTML content or None on error
        """
        await self._rate_limit()

        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=60000)

            # Wait for content to load
            try:
                await self.page.wait_for_selector(wait_for, timeout=30000)
            except Exception:
                # Selector not found, but page may still have content
                pass

            return await self.page.content()

        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
            return None


# =============================================================================
# Search Results Parsing
# =============================================================================

def parse_search_results(html: str, collection_key: str) -> tuple[list[dict], bool]:
    """
    Parse search results page.

    Returns (list of entries, has_next_page).
    Each entry has: shelfmark, catalog_id, detail_url
    """
    soup = BeautifulSoup(html, "html.parser")
    entries = []

    collection = COLLECTIONS[collection_key]
    prefix = collection["shelfmark_prefix"]

    # Find results container
    results = soup.select_one("#documents")
    if not results:
        logger.warning("Results container (#documents) not found")
        return [], False

    # Parse each document entry
    for doc in results.select(".document"):
        # Find the title link (h3 > a or similar)
        link = doc.select_one("h3 a")
        if not link:
            link = doc.select_one(".index_title a")
        if not link:
            continue

        shelfmark = link.get_text(strip=True)

        # Filter to manuscripts only (exclude Charters, Rolls, etc.)
        if not shelfmark.startswith(prefix):
            logger.debug(f"Skipping non-MS item: {shelfmark}")
            continue

        href = link.get("href", "")
        catalog_id = href.split("/")[-1] if href else ""

        entries.append({
            "shelfmark": shelfmark,
            "catalog_id": catalog_id,
            "detail_url": urljoin(BL_BASE_URL, href),
        })

    # Check if there's a next page link
    has_next = soup.select_one(".pagination .next_page:not(.disabled)") is not None

    return entries, has_next


# =============================================================================
# Detail Page Parsing
# =============================================================================

# Regex for IIIF manifest URL in page content
MANIFEST_PATTERN = re.compile(r"https://bl\.digirati\.io/iiif/ark:/81055/[\w.]+")
ARK_PATTERN = re.compile(r"ark:/81055/[\w.]+")


def parse_detail_page(html: str, entry: dict) -> dict:
    """
    Parse manuscript detail page and extract metadata.

    Returns dict with Compilatio-compatible fields.
    """
    soup = BeautifulSoup(html, "html.parser")

    record = {
        "shelfmark": entry["shelfmark"],
        "catalog_id": entry["catalog_id"],
        "source_url": entry["detail_url"],
    }

    # Extract all dt/dd pairs from the metadata section
    raw_fields = {}
    for dt in soup.select("dt"):
        field_name = dt.get_text(strip=True).rstrip(":")
        dd = dt.find_next_sibling("dd")
        if dd:
            raw_fields[field_name] = dd.get_text(strip=True)

    # Map to Compilatio fields
    for bl_field, db_field in FIELD_MAPPING.items():
        if bl_field in raw_fields:
            value = raw_fields[bl_field]
            # Handle multiple mappings to same field (e.g., provenance)
            if db_field in record and record[db_field]:
                record[db_field] += f"\n\n{value}"
            else:
                record[db_field] = value

    # Parse date fields to integers
    if "date_start" in record:
        try:
            # Extract year from date string
            year_match = re.search(r'\d{4}', str(record["date_start"]))
            if year_match:
                record["date_start"] = int(year_match.group())
            else:
                del record["date_start"]
        except (ValueError, TypeError):
            del record["date_start"]

    if "date_end" in record:
        try:
            year_match = re.search(r'\d{4}', str(record["date_end"]))
            if year_match:
                record["date_end"] = int(year_match.group())
            else:
                del record["date_end"]
        except (ValueError, TypeError):
            del record["date_end"]

    # Use title as contents if no scope/content
    if "title" in record and "contents" not in record:
        record["contents"] = record.pop("title")
    elif "title" in record:
        del record["title"]

    # Truncate contents if too long
    if "contents" in record and len(record["contents"]) > 1000:
        record["contents"] = record["contents"][:997] + "..."

    # Extract IIIF manifest URL
    manifest_match = MANIFEST_PATTERN.search(html)
    if manifest_match:
        record["iiif_manifest_url"] = manifest_match.group()
    else:
        # Try to construct from ARK identifier
        ark_match = ARK_PATTERN.search(html)
        if ark_match:
            record["iiif_manifest_url"] = f"{IIIF_BASE_URL}/{ark_match.group()}"

    # Build thumbnail URL from manifest
    if "iiif_manifest_url" in record:
        record["thumbnail_url"] = build_thumbnail_url(record["iiif_manifest_url"])

    return record


def build_thumbnail_url(manifest_url: str) -> Optional[str]:
    """
    Build thumbnail URL from IIIF manifest URL.

    Note: This returns None because we can't derive the thumbnail URL
    from just the manifest URL - the thumbnail uses a different ARK ID
    (the first canvas/image). We fetch it from the manifest in
    fetch_thumbnail_from_manifest() instead.
    """
    return None


async def fetch_thumbnail_from_manifest(scraper: BLScraper, manifest_url: str) -> Optional[str]:
    """
    Fetch the thumbnail URL from a IIIF manifest.

    BL manifests include a thumbnail array with direct URLs.
    """
    import json
    try:
        html = await scraper.get_page(manifest_url, wait_for="body")
        if not html:
            return None

        # The page content is JSON
        soup = BeautifulSoup(html, "html.parser")
        # Extract text content (the JSON)
        text = soup.get_text()

        try:
            manifest = json.loads(text)
        except json.JSONDecodeError:
            return None

        # IIIF Presentation 3.0 format
        thumbnails = manifest.get("thumbnail", [])
        if thumbnails and isinstance(thumbnails, list) and len(thumbnails) > 0:
            thumb = thumbnails[0]
            if isinstance(thumb, dict) and "id" in thumb:
                return thumb["id"]

        return None
    except Exception as e:
        logger.debug(f"Error fetching thumbnail from {manifest_url}: {e}")
        return None


# =============================================================================
# Collection Extraction
# =============================================================================

def extract_collection_name(shelfmark: str) -> str:
    """
    Extract collection name from BL shelfmark.

    Examples:
        "Cotton MS Tiberius B V/1" -> "Cotton"
        "Harley MS 603" -> "Harley"
        "Royal MS 2 B VII" -> "Royal"
    """
    if shelfmark.startswith("Cotton MS"):
        return "Cotton"
    elif shelfmark.startswith("Harley MS"):
        return "Harley"
    elif shelfmark.startswith("Royal MS"):
        return "Royal"
    elif shelfmark.startswith("Add MS"):
        return "Additional"
    elif shelfmark.startswith("Stowe MS"):
        return "Stowe"
    elif shelfmark.startswith("Lansdowne MS"):
        return "Lansdowne"
    elif shelfmark.startswith("Arundel MS"):
        return "Arundel"
    elif shelfmark.startswith("Egerton MS"):
        return "Egerton"
    else:
        # Fallback: first word before "MS"
        parts = shelfmark.split()
        if "MS" in parts:
            idx = parts.index("MS")
            if idx > 0:
                return parts[idx - 1]
        return "Unknown"


# =============================================================================
# Database Operations
# =============================================================================

def ensure_repository(cursor) -> int:
    """Ensure British Library repository exists and return its ID."""
    cursor.execute(
        "SELECT id FROM repositories WHERE short_name = ?",
        ("BL",)
    )
    row = cursor.fetchone()
    if row:
        return row[0]

    cursor.execute("""
        INSERT INTO repositories (name, short_name, logo_url, catalogue_url)
        VALUES (?, ?, ?, ?)
    """, (
        "British Library",
        "BL",
        None,
        "https://searcharchives.bl.uk/"
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

async def scrape_collection(
    scraper: BLScraper,
    collection_key: str,
    test_mode: bool = False,
    max_pages: int = 100,
) -> list[dict]:
    """
    Scrape all digitized manuscripts from a collection.

    Returns list of manuscript records with metadata.
    """
    collection = COLLECTIONS[collection_key]
    logger.info(f"Scraping {collection['name']} (digitized only)")

    all_records = []
    all_entries = []

    # Paginate through search results until no more pages
    page = 1
    while page <= max_pages:
        url = build_search_url(collection_key, page=page)
        logger.info(f"Fetching search page {page}: {url}")

        html = await scraper.get_page(url)
        if not html:
            logger.error(f"Failed to fetch search page {page}")
            break

        entries, has_next = parse_search_results(html, collection_key)
        logger.info(f"Found {len(entries)} {collection['shelfmark_prefix']} items on page {page}")

        all_entries.extend(entries)

        # Stop conditions
        if test_mode:
            logger.info("Test mode: stopping after first page")
            break
        if not has_next:
            logger.info("No more pages")
            break

        page += 1

    logger.info(f"Scraped {page} pages, found {len(all_entries)} {collection['shelfmark_prefix']} entries")

    # Limit in test mode
    if test_mode:
        all_entries = all_entries[:5]
        logger.info(f"Test mode: limiting to {len(all_entries)} manuscripts")

    if not all_entries:
        logger.warning("No manuscript entries found matching filter")
        return []

    logger.info(f"Fetching detail pages for {len(all_entries)} manuscripts...")

    # Fetch detail pages
    for i, entry in enumerate(all_entries):
        logger.info(f"[{i+1}/{len(all_entries)}] Fetching {entry['shelfmark']}")

        html = await scraper.get_page(entry["detail_url"], wait_for=".show-document")
        if not html:
            logger.warning(f"Failed to fetch detail page for {entry['shelfmark']}")
            continue

        record = parse_detail_page(html, entry)
        record["collection"] = extract_collection_name(record["shelfmark"])

        # Skip if no IIIF manifest found
        if "iiif_manifest_url" not in record:
            logger.warning(f"No IIIF manifest found for {entry['shelfmark']}, skipping")
            continue

        all_records.append(record)

        # Progress logging
        if (i + 1) % 10 == 0:
            logger.info(f"Progress: {i+1}/{len(all_entries)} detail pages scraped")

    logger.info(f"Successfully scraped {len(all_records)} manuscripts with IIIF manifests")
    return all_records


async def import_collection_async(
    db_path: Path,
    collection_key: str,
    dry_run: bool = True,
    test_mode: bool = False,
    verbose: bool = False,
    headless: bool = True,
):
    """
    Import a BL collection into Compilatio database.
    """
    if verbose:
        logger.setLevel(logging.DEBUG)

    collection = COLLECTIONS[collection_key]

    if not db_path.exists():
        logger.error(f"Database not found: {db_path}")
        logger.info("Initialize the database first:")
        logger.info("  sqlite3 database/compilatio.db < database/schema.sql")
        return False

    # Scrape the collection
    async with BLScraper(headless=headless) as scraper:
        records = await scrape_collection(scraper, collection_key, test_mode=test_mode)

    if not records:
        logger.warning("No manuscripts found to import")
        return True

    # Database operations
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    repo_id = ensure_repository(cursor) if not dry_run else 1

    stats = {
        "total_scraped": len(records),
        "inserted": 0,
        "updated": 0,
        "skipped": 0,
        "errors": 0,
    }

    for record in records:
        shelfmark = record["shelfmark"]

        if dry_run:
            # Check what would happen
            cursor.execute(
                "SELECT id FROM manuscripts WHERE shelfmark = ?",
                (shelfmark,)
            )
            if cursor.fetchone():
                stats["updated"] += 1
            else:
                stats["inserted"] += 1
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
                logger.error(f"Error importing {shelfmark}: {e}")
                stats["errors"] += 1

    if not dry_run:
        conn.commit()
    conn.close()

    # Print summary
    print("\n" + "=" * 70)
    print(f"{'DRY RUN - ' if dry_run else ''}BRITISH LIBRARY IMPORT: {collection['name']}")
    print("=" * 70)
    print(f"\nScraping Results:")
    print(f"  Manuscripts scraped:  {stats['total_scraped']}")
    print(f"\nDatabase Operations {'(would be)' if dry_run else ''}:")
    print(f"  {'Would insert' if dry_run else 'Inserted'}:  {stats['inserted']}")
    print(f"  {'Would update' if dry_run else 'Updated'}:   {stats['updated']}")
    print(f"  Errors:               {stats['errors']}")

    if dry_run:
        print("\n" + "=" * 70)
        print("This was a DRY RUN. No changes were made to the database.")
        print("Run with --execute to apply changes.")
        print("=" * 70)

    return True


def import_collection(
    db_path: Path,
    collection_key: str,
    dry_run: bool = True,
    test_mode: bool = False,
    verbose: bool = False,
    headless: bool = True,
):
    """Synchronous wrapper for async import function."""
    return asyncio.run(import_collection_async(
        db_path=db_path,
        collection_key=collection_key,
        dry_run=dry_run,
        test_mode=test_mode,
        verbose=verbose,
        headless=headless,
    ))


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Import digitized British Library manuscripts"
    )
    parser.add_argument(
        '--collection', '-c',
        required=True,
        choices=list(COLLECTIONS.keys()),
        help='Collection to import (cotton, harley, or royal)'
    )
    parser.add_argument(
        '--execute',
        action='store_true',
        help='Actually execute the import (default is dry-run)'
    )
    parser.add_argument(
        '--test',
        action='store_true',
        help='Test mode: scrape first page only, limit to 5 detail pages'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Show detailed logging'
    )
    parser.add_argument(
        '--no-headless',
        action='store_true',
        help='Show browser window (useful for debugging)'
    )
    parser.add_argument(
        '--db',
        type=Path,
        default=DB_PATH,
        help=f'Path to database (default: {DB_PATH})'
    )

    args = parser.parse_args()

    collection = COLLECTIONS[args.collection]

    print("Compilatio British Library Import Tool")
    print(f"Collection: {collection['name']}")
    print(f"Filter: Digitized only (with IIIF manifests)")
    print(f"DB: {args.db}")
    print(f"Mode: {'TEST' if args.test else 'EXECUTE' if args.execute else 'DRY-RUN'}")
    print()

    success = import_collection(
        db_path=args.db,
        collection_key=args.collection,
        dry_run=not args.execute,
        test_mode=args.test,
        verbose=args.verbose,
        headless=not args.no_headless,
    )

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
