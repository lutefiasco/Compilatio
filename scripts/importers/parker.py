#!/usr/bin/env python3
"""
Parker Library (Corpus Christi College, Cambridge) Import Script for Compilatio.

Imports digitized medieval manuscripts from Parker Library on the Web,
hosted by Stanford University Libraries.

The Parker catalogue has aggressive bot protection that blocks automated access.
This script supports two discovery modes:
  1. --from-html: Parse manually-saved HTML files (recommended)
  2. crawl4ai: Attempt browser-based crawling (usually blocked)

Two-phase process:
  Phase 1 (Discovery): Extract druid/shelfmark mappings from HTML
  Phase 2 (Import): Fetch IIIF manifests and parse metadata

Dependencies:
    pip install beautifulsoup4
    # crawl4ai only needed if not using --from-html

Usage:
    # Recommended: Use manually-saved HTML files
    python scripts/importers/parker.py --from-html data/parker_html/ --discover-only
    python scripts/importers/parker.py --skip-discovery --execute

    # Alternative: Try crawl4ai (usually blocked by bot detection)
    python scripts/importers/parker.py --discover-only
    python scripts/importers/parker.py --skip-discovery --execute

    # Other options
    python scripts/importers/parker.py --test             # First 5 only
    python scripts/importers/parker.py --verbose          # Detailed logging

Source:
    https://parker.stanford.edu/parker/browse/browse-by-manuscript-number
    Scoped to Archive/Manuscript items only (~560 manuscripts)

Manual HTML Download Instructions:
    Save page source from browser for each of 6 pages:
    - https://parker.stanford.edu/parker/browse/browse-by-manuscript-number?per_page=96
    - ...&page=2 through &page=6
    Save to: data/parker_html/page1.html ... page6.html
"""

import argparse
import asyncio
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
DISCOVERY_CACHE = PROJECT_ROOT / "data" / "parker_discovery.json"
PROGRESS_FILE = PROJECT_ROOT / "data" / "parker_progress.json"

# Parker Library URLs
PARKER_BASE = "https://parker.stanford.edu/parker"
# Scoped to Archive/Manuscript format only - URL decoded for readability
CATALOG_BASE_URL = (
    f"{PARKER_BASE}/catalog?"
    "f[format_main_ssim][]=Archive/Manuscript&"
    "per_page=96&"
    "search_field=manuscript_number&"
    "sort=title_sort+asc,+pub_year_isi+desc"
)

# Stanford IIIF endpoints
PURL_BASE = "https://purl.stanford.edu"
MANIFEST_TEMPLATE = f"{PURL_BASE}/{{druid}}/iiif/manifest"

# Rate limiting
CRAWL_DELAY = 5.0  # seconds between page crawls
MANIFEST_DELAY = 0.3  # seconds between manifest fetches

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
# Phase 1a: Discovery from Local HTML Files
# =============================================================================


def discover_from_html(html_dir: Path, verbose: bool = False) -> list[dict]:
    """
    Parse manually-saved HTML files to discover manuscripts.

    Expects files named page1.html, page2.html, etc. in html_dir.
    Looks for druid links and shelfmarks in document-thumbnail divs.

    Returns list of dicts with: druid, shelfmark, title
    """
    from bs4 import BeautifulSoup

    manuscripts = []
    html_files = sorted(html_dir.glob("page*.html"))

    if not html_files:
        # Also try without 'page' prefix
        html_files = sorted(html_dir.glob("*.html"))

    if not html_files:
        logger.error(f"No HTML files found in {html_dir}")
        return []

    logger.info(f"Found {len(html_files)} HTML files in {html_dir}")

    for html_file in html_files:
        logger.info(f"Parsing {html_file.name}...")

        with open(html_file, "r", encoding="utf-8") as f:
            soup = BeautifulSoup(f.read(), "html.parser")

        # Look for document-thumbnail divs with manifest links
        thumbnails = soup.select("div.document-thumbnail")
        if verbose:
            logger.debug(f"  Found {len(thumbnails)} document-thumbnail divs")

        # Also look for catalog links as fallback
        catalog_links = soup.select('a[href*="/catalog/"]')

        items_found = 0
        for link in catalog_links:
            href = link.get("href", "")
            # Extract druid from URL like /parker/catalog/wz026zp2442
            match = re.search(r"/catalog/([a-z]{2}\d{3}[a-z]{2}\d{4})", href)
            if not match:
                continue

            druid = match.group(1)

            # Skip if already found
            if any(m["druid"] == druid for m in manuscripts):
                continue

            # Get link text for title/shelfmark
            link_text = link.get_text(strip=True)

            # Extract shelfmark: "MS ###" pattern
            shelfmark = None
            shelfmark_match = re.search(r"MS\.?\s*(\d+[A-Za-z]?)", link_text)
            if shelfmark_match:
                shelfmark = f"MS {shelfmark_match.group(1)}"
            else:
                # Try parent element
                parent = link.find_parent(["div", "article", "li"])
                if parent:
                    parent_text = parent.get_text(" ", strip=True)
                    shelfmark_match = re.search(r"MS\.?\s*(\d+[A-Za-z]?)", parent_text)
                    if shelfmark_match:
                        shelfmark = f"MS {shelfmark_match.group(1)}"

            if not shelfmark:
                shelfmark = f"MS {druid}"

            # Get title - clean up
            title = link_text
            title = re.sub(r"^Cambridge,?\s*Corpus Christi College,?\s*", "", title)
            title = re.sub(r"^MS\.?\s*\d+[A-Za-z]?\s*[:\-–]?\s*", "", title).strip()

            manuscripts.append({
                "druid": druid,
                "shelfmark": shelfmark,
                "title": title if title else None,
            })
            items_found += 1

        logger.info(f"  Found {items_found} new manuscripts (total: {len(manuscripts)})")

    logger.info(f"Discovery complete: {len(manuscripts)} manuscripts from HTML files")
    return manuscripts


# =============================================================================
# Phase 1b: Discovery via crawl4ai (usually blocked)
# =============================================================================


async def discover_manuscripts(
    test_mode: bool = False,
    limit: int = None,
) -> list[dict]:
    """
    Crawl Parker catalog pages to discover all manuscripts.

    Returns list of dicts with: druid, shelfmark, title
    """
    from bs4 import BeautifulSoup
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig

    browser_config = BrowserConfig(
        headless=True,
        verbose=False,
    )
    crawl_config = CrawlerRunConfig(
        wait_until="domcontentloaded",
        page_timeout=60000,
        delay_before_return_html=8.0,  # Wait for JS to render
    )

    manuscripts = []
    page_num = 1
    max_pages = 10 if not test_mode else 1

    async with AsyncWebCrawler(config=browser_config) as crawler:
        while page_num <= max_pages:
            # Build URL with page number
            url = CATALOG_BASE_URL
            if page_num > 1:
                url += f"&page={page_num}"

            logger.info(f"Crawling catalog page {page_num}...")

            try:
                result = await crawler.arun(url=url, config=crawl_config)
                soup = BeautifulSoup(result.html, "html.parser")
            except Exception as e:
                logger.error(f"Failed to crawl page {page_num}: {e}")
                break

            # Check for error/blocked page
            title = soup.title.string if soup.title else ""
            if "rejected" in title.lower() or "error" in title.lower():
                logger.warning(f"Page {page_num} returned error: {title}")
                break

            # Find manuscript entries
            # Parker uses Spotlight/Blacklight - look for document containers
            items_found = 0

            # Try multiple selector patterns
            # Pattern 1: Direct catalog links
            catalog_links = soup.select('a[href*="/catalog/"]')
            for link in catalog_links:
                href = link.get("href", "")
                # Extract druid from URL like /parker/catalog/wz026zp2442
                match = re.search(r"/catalog/([a-z]{2}\d{3}[a-z]{2}\d{4})", href)
                if not match:
                    continue

                druid = match.group(1)

                # Skip if already found
                if any(m["druid"] == druid for m in manuscripts):
                    continue

                # Get link text for title/shelfmark
                link_text = link.get_text(strip=True)

                # Extract shelfmark: "MS ###" pattern
                shelfmark_match = re.search(r"MS\.?\s*(\d+[A-Za-z]?)", link_text)
                if shelfmark_match:
                    shelfmark = f"MS {shelfmark_match.group(1)}"
                else:
                    # Try parent element
                    parent = link.find_parent(["article", "div", "li"])
                    if parent:
                        parent_text = parent.get_text(" ", strip=True)
                        shelfmark_match = re.search(r"MS\.?\s*(\d+[A-Za-z]?)", parent_text)
                        if shelfmark_match:
                            shelfmark = f"MS {shelfmark_match.group(1)}"
                        else:
                            shelfmark = f"MS {druid}"
                    else:
                        shelfmark = f"MS {druid}"

                # Get title - clean up
                title = link_text
                title = re.sub(r"^Cambridge,?\s*Corpus Christi College,?\s*", "", title)
                title = re.sub(r"^MS\.?\s*\d+[A-Za-z]?\s*[:\-–]?\s*", "", title).strip()

                manuscripts.append({
                    "druid": druid,
                    "shelfmark": shelfmark,
                    "title": title if title else None,
                })
                items_found += 1

            logger.info(f"  Found {items_found} new manuscripts (total: {len(manuscripts)})")

            # Check for next page
            next_link = soup.select_one('a.next_page, a[rel="next"], .pagination .next a')
            if not next_link or items_found == 0:
                logger.info("  No more pages.")
                break

            # Stop if we have enough for limit/test mode
            if test_mode and len(manuscripts) >= 5:
                break
            if limit and len(manuscripts) >= limit:
                break

            page_num += 1
            await asyncio.sleep(CRAWL_DELAY)

    logger.info(f"Discovery complete: {len(manuscripts)} manuscripts found")

    # Apply final limits
    if test_mode:
        manuscripts = manuscripts[:5]
        logger.info("Test mode: limiting to 5 manuscripts")
    elif limit:
        manuscripts = manuscripts[:limit]
        logger.info(f"Limiting to {limit} manuscripts")

    return manuscripts


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
# Phase 2: IIIF Manifest Parsing
# =============================================================================


def extract_metadata_value(metadata: list, label: str) -> Optional[str]:
    """Extract a value from IIIF metadata array by label."""
    for entry in metadata:
        entry_label = entry.get("label", "")
        # Handle both string and dict labels (IIIF v2/v3 variants)
        if isinstance(entry_label, dict):
            entry_label = entry_label.get("@value", "") or entry_label.get("en", [""])[0]
        if isinstance(entry_label, list):
            entry_label = entry_label[0] if entry_label else ""
            if isinstance(entry_label, dict):
                entry_label = entry_label.get("@value", "")

        if not isinstance(entry_label, str):
            continue

        if entry_label.lower().strip() == label.lower().strip():
            value = entry.get("value", "")
            if isinstance(value, list):
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
            t = thumb[0]
            if isinstance(t, dict):
                return t.get("@id") or t.get("id")
            return str(t)

    # Fall back to first canvas image
    sequences = manifest.get("sequences", [])
    if sequences:
        canvases = sequences[0].get("canvases", [])
        if canvases:
            images = canvases[0].get("images", [])
            if images:
                resource = images[0].get("resource", {})
                service = resource.get("service", {})
                if isinstance(service, list):
                    service = service[0] if service else {}
                service_id = service.get("@id") or service.get("id")
                if service_id:
                    return f"{service_id}/full/200,/0/default.jpg"

    return None


def parse_date(date_str: str) -> tuple[Optional[int], Optional[int]]:
    """Parse date string into (start_year, end_year)."""
    if not date_str:
        return None, None

    # Try explicit years: "1300-1400", "c. 1350", "ca. 1410"
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
    """Count the number of canvases (pages) in a manifest."""
    sequences = manifest.get("sequences", [])
    if sequences:
        canvases = sequences[0].get("canvases", [])
        return len(canvases)
    return 0


def parse_manifest(manifest_data: dict, manifest_url: str, discovery_item: dict) -> Optional[dict]:
    """
    Parse a Stanford IIIF manifest into a Compilatio record.

    Uses discovery data as fallback for missing manifest metadata.
    """
    metadata = manifest_data.get("metadata", [])
    label = manifest_data.get("label", "")
    if isinstance(label, dict):
        label = label.get("@value", "") or str(label)

    # Shelfmark from discovery (preferred) or manifest label
    shelfmark = discovery_item.get("shelfmark")
    if not shelfmark:
        # Try to extract from label
        match = re.search(r"MS\.?\s*(\d+[A-Za-z]?)", label)
        if match:
            shelfmark = f"MS {match.group(1)}"
        else:
            logger.warning(f"No shelfmark found for {manifest_url}")
            return None

    record = {
        "shelfmark": shelfmark,
        "collection": "Parker Library",
        "iiif_manifest_url": manifest_url,
    }

    # Title / contents
    title = extract_metadata_value(metadata, "Title")
    if not title:
        title = label
    if not title:
        title = discovery_item.get("title")
    if title:
        # Clean up shelfmark from title
        title = re.sub(r"^Cambridge,?\s*Corpus Christi College,?\s*", "", title)
        title = re.sub(r"^MS\.?\s*\d+[A-Za-z]?\s*[:\-–]?\s*", "", title).strip()
        if len(title) > 1000:
            title = title[:997] + "..."
        if title:
            record["contents"] = title

    # Date
    date_str = extract_metadata_value(metadata, "Date")
    if not date_str:
        date_str = extract_metadata_value(metadata, "Date of Creation")
    if date_str:
        record["date_display"] = date_str
        start, end = parse_date(date_str)
        if start:
            record["date_start"] = start
        if end:
            record["date_end"] = end

    # Language
    language = extract_metadata_value(metadata, "Language")
    if language:
        record["language"] = language

    # Physical description
    extent = extract_metadata_value(metadata, "Physical Description")
    if not extent:
        extent = extract_metadata_value(metadata, "Extent")
    if extent:
        record["folios"] = extent

    # Provenance
    provenance = extract_metadata_value(metadata, "Provenance")
    if provenance:
        record["provenance"] = provenance

    # Thumbnail
    thumb = extract_thumbnail_url(manifest_data)
    if thumb:
        record["thumbnail_url"] = thumb

    # Image count
    image_count = count_canvases(manifest_data)
    if image_count > 0:
        record["image_count"] = image_count

    # Source URL (Parker catalog page)
    druid = discovery_item.get("druid")
    record["source_url"] = f"{PARKER_BASE}/catalog/{druid}"

    return record


# =============================================================================
# Progress/Checkpoint Management
# =============================================================================


def load_progress(progress_path: Path) -> dict:
    """Load progress from checkpoint file."""
    if not progress_path.exists():
        return {
            "last_updated": None,
            "total_discovered": 0,
            "completed_druids": [],
            "failed_druids": [],
        }
    with open(progress_path) as f:
        return json.load(f)


def save_progress(progress: dict, progress_path: Path):
    """Save progress to checkpoint file."""
    progress["last_updated"] = datetime.now(timezone.utc).isoformat()
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    with open(progress_path, "w") as f:
        json.dump(progress, f, indent=2)


def mark_completed(progress: dict, druid: str, progress_path: Path):
    """Mark a druid as completed and save checkpoint."""
    if druid not in progress["completed_druids"]:
        progress["completed_druids"].append(druid)
    if druid in progress["failed_druids"]:
        progress["failed_druids"].remove(druid)
    save_progress(progress, progress_path)


def mark_failed(progress: dict, druid: str, progress_path: Path):
    """Mark a druid as failed and save checkpoint."""
    if druid not in progress["failed_druids"]:
        progress["failed_druids"].append(druid)
    save_progress(progress, progress_path)


# =============================================================================
# Database Operations
# =============================================================================


def ensure_repository(cursor) -> int:
    """Ensure Parker Library repository exists and return its ID."""
    cursor.execute(
        "SELECT id FROM repositories WHERE short_name = ?", ("Parker",)
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
            "Parker Library, Corpus Christi College, Cambridge",
            "Parker",
            None,
            "https://parker.stanford.edu/parker/catalog",
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


def import_parker(
    db_path: Path,
    dry_run: bool = True,
    test_mode: bool = False,
    verbose: bool = False,
    limit: int = None,
    discover_only: bool = False,
    skip_discovery: bool = False,
    resume: bool = False,
    from_html: Path = None,
):
    """Import Parker Library manuscripts."""
    if verbose:
        logger.setLevel(logging.DEBUG)

    # Load or run discovery
    items = None
    if skip_discovery:
        items = load_discovery_cache(DISCOVERY_CACHE)
        if items is None:
            logger.error("No discovery cache found. Run without --skip-discovery first.")
            return False
    elif from_html:
        # Parse from local HTML files
        logger.info(f"Discovering from local HTML files in {from_html}")
        items = discover_from_html(from_html, verbose=verbose)
        if items:
            save_discovery_cache(items, DISCOVERY_CACHE)
    else:
        if resume:
            items = load_discovery_cache(DISCOVERY_CACHE)

        if items is None:
            logger.info("Running crawl4ai-based discovery (may be blocked by bot detection)...")
            items = asyncio.run(discover_manuscripts(test_mode=test_mode, limit=limit))
            if items:
                save_discovery_cache(items, DISCOVERY_CACHE)

    if not items:
        logger.error("No manuscripts discovered")
        return False

    logger.info(f"Total manuscripts discovered: {len(items)}")

    if discover_only:
        print(f"\nDiscovery complete. {len(items)} manuscripts found.")
        print(f"Cache saved to: {DISCOVERY_CACHE}")
        return True

    # Database check
    if not db_path.exists():
        logger.error(f"Database not found: {db_path}")
        logger.info("Initialize the database first:")
        logger.info("  sqlite3 database/compilatio.db < database/schema.sql")
        return False

    # Load progress for resume
    progress = load_progress(PROGRESS_FILE) if resume else {
        "last_updated": None,
        "total_discovered": len(items),
        "completed_druids": [],
        "failed_druids": [],
    }

    # Filter out completed items if resuming
    if resume and progress["completed_druids"]:
        items_to_process = [
            item for item in items
            if item["druid"] not in progress["completed_druids"]
        ]
        logger.info(
            f"Resuming: {len(progress['completed_druids'])} already completed, "
            f"{len(items_to_process)} remaining"
        )
    else:
        items_to_process = items

    # Phase 2: Fetch manifests and build records
    records = []
    fetch_errors = 0

    for i, item in enumerate(items_to_process):
        druid = item["druid"]
        manifest_url = MANIFEST_TEMPLATE.format(druid=druid)

        logger.info(f"[{i+1}/{len(items_to_process)}] Fetching manifest for {item['shelfmark']}")

        manifest_data = fetch_json(manifest_url)
        if not manifest_data:
            fetch_errors += 1
            mark_failed(progress, druid, PROGRESS_FILE)
            continue

        record = parse_manifest(manifest_data, manifest_url, item)
        if record:
            records.append(record)
            mark_completed(progress, druid, PROGRESS_FILE)
            logger.debug(f"  -> {record['shelfmark']}")
        else:
            logger.warning(f"  -> Could not parse manifest for {druid}")
            fetch_errors += 1
            mark_failed(progress, druid, PROGRESS_FILE)

        # Rate limit
        if i < len(items_to_process) - 1:
            time.sleep(MANIFEST_DELAY)

        # Progress logging
        if (i + 1) % 25 == 0:
            logger.info(f"Progress: {i+1}/{len(items_to_process)} manifests, {len(records)} parsed")

    logger.info(
        f"Fetched {len(items_to_process)} manifests, "
        f"parsed {len(records)} records, {fetch_errors} errors"
    )

    # Database operations
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
    print(f"{'DRY RUN - ' if dry_run else ''}PARKER LIBRARY IMPORT SUMMARY")
    print("=" * 70)
    print(f"\nDiscovery:")
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
            date = f" ({rec.get('date_display', '')})" if rec.get("date_display") else ""
            print(f"  {rec['shelfmark']}{date}")
            if rec.get("contents"):
                contents = rec["contents"]
                if len(contents) > 70:
                    contents = contents[:67] + "..."
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
        description="Import Parker Library manuscripts into Compilatio"
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually execute the import (default is dry-run)",
    )
    parser.add_argument(
        "--from-html",
        type=Path,
        default=None,
        help="Directory containing manually-saved HTML files (page1.html, etc.)",
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
        "--verbose", "-v",
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

    args = parser.parse_args()

    print("Compilatio Parker Library Import Tool")
    print(f"Source: Parker Library on the Web (Corpus Christi College, Cambridge)")
    print(f"DB:    {args.db}")
    print(f"Cache: {DISCOVERY_CACHE}")
    if args.from_html:
        print(f"HTML:  {args.from_html}")

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
    if args.from_html:
        mode_parts.append("FROM-HTML")

    print(f"Mode:  {' + '.join(mode_parts)}")
    if args.limit:
        print(f"Limit: {args.limit}")
    print()

    success = import_parker(
        db_path=args.db,
        dry_run=not args.execute,
        test_mode=args.test,
        verbose=args.verbose,
        limit=args.limit,
        discover_only=args.discover_only,
        skip_discovery=args.skip_discovery,
        resume=args.resume,
        from_html=args.from_html,
    )
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
