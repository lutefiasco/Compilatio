#!/usr/bin/env python3
"""
Harvard Houghton Library Manuscript Import Script for Compilatio.

Imports digitized manuscripts from Harvard Digital Collections via
Biblissima IIIF Collections discovery.

Two-phase process with checkpoint resumability:
  Phase 1 (Discovery): Scrape Biblissima search results (server-rendered HTML)
  Phase 2 (Import): Fetch IIIF manifests from Harvard DRS, parse metadata,
    insert to database

Dependencies:
    pip install beautifulsoup4

Source:
    https://iiif.biblissima.fr/collections/search?q=houghton+harvard

Usage:
    python scripts/importers/harvard.py                    # Dry-run mode
    python scripts/importers/harvard.py --execute          # Actually import
    python scripts/importers/harvard.py --resume --execute # Resume interrupted
    python scripts/importers/harvard.py --discover-only    # Only run discovery
    python scripts/importers/harvard.py --skip-discovery   # Use cached discovery
    python scripts/importers/harvard.py --test             # First 5 only
    python scripts/importers/harvard.py --verbose          # Detailed logging
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
CACHE_DIR = Path(__file__).parent / "cache"
DISCOVERY_CACHE = CACHE_DIR / "harvard_discovery.json"
PROGRESS_FILE = CACHE_DIR / "harvard_progress.json"

# Biblissima discovery
BIBLISSIMA_BASE = "https://iiif.biblissima.fr"
BIBLISSIMA_SEARCH = BIBLISSIMA_BASE + "/collections/search?q=houghton+harvard"
RESULTS_PER_PAGE = 20
TOTAL_EXPECTED = 249

# Harvard Digital Collections
HARVARD_IIIF_BASE = "https://iiif.lib.harvard.edu/manifests"
HARVARD_VIEWER_BASE = "https://iiif.lib.harvard.edu/manifests/view"

# Rate limiting
BIBLISSIMA_DELAY = 1.0  # seconds between page requests
MANIFEST_DELAY = 0.5    # seconds between manifest fetches

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

USER_AGENT = "Compilatio/1.0 (Academic manuscript research; IIIF aggregator)"

# Collection mapping based on shelfmark prefix
COLLECTION_MAPPING = {
    r'^MS Lat': "Latin",
    r'^MS Typ': "Typographic",
    r'^MS Gr': "Greek",
    r'^MS Richardson': "Richardson",
    r'^MS Ital': "Italian",
    r'^MS Span': "Spanish",
    r'^MS Eng': "English",
    r'^MS Fr': "French",
    r'^MS Ger': "German",
    r'^MS Hebrew': "Hebrew",
    r'^MS Arab': "Arabic",
    r'^MS Riant': "Riant",
}


# =============================================================================
# HTTP Helpers
# =============================================================================


def fetch_url(url: str, retries: int = 3) -> Optional[str]:
    """Fetch a URL and return the content as string with retry logic."""
    for attempt in range(retries):
        try:
            req = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(req, timeout=60) as resp:
                return resp.read().decode("utf-8")
        except (HTTPError, URLError, TimeoutError, OSError) as e:
            if attempt < retries - 1:
                logger.debug(f"Retry {attempt + 1}/{retries} for {url}: {e}")
                time.sleep(2)
            else:
                logger.warning(f"Failed to fetch {url}: {e}")
                return None
    return None


def fetch_json(url: str, retries: int = 3) -> Optional[dict]:
    """Fetch a URL and parse as JSON with retry logic."""
    content = fetch_url(url, retries)
    if content:
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            logger.warning(f"JSON parse error for {url}: {e}")
    return None


# =============================================================================
# Shelfmark Extraction and Collection Mapping
# =============================================================================


def extract_shelfmark_from_label(label: str) -> Optional[str]:
    """
    Extract shelfmark from Harvard manifest label.

    Harvard labels contain the shelfmark embedded in the full title, e.g.:
    "Catholic Church. Book of hours : use of Rome : manuscript, [ca. 1485]. MS Lat 249. Houghton Library..."

    We need to extract "MS Lat 249" from this.
    """
    # Common shelfmark patterns
    patterns = [
        r'(MS Lat \d+[A-Za-z]*)',
        r'(MS Typ \d+[A-Za-z]*(?:\.\d+)?)',
        r'(MS Gr \d+[A-Za-z]*)',
        r'(MS Richardson \d+[A-Za-z]*)',
        r'(MS Ital \d+[A-Za-z]*)',
        r'(MS Span \d+[A-Za-z]*)',
        r'(MS Eng \d+[A-Za-z]*)',
        r'(MS Fr \d+[A-Za-z]*)',
        r'(MS Ger \d+[A-Za-z]*)',
        r'(MS Hebrew \d+[A-Za-z]*)',
        r'(MS Arab \d+[A-Za-z]*)',
        r'(MS Riant \d+[A-Za-z]*)',
        r'(Typ \d+[A-Za-z]*(?:\.\d+)?)',  # Some use "Typ" without "MS"
    ]

    for pattern in patterns:
        match = re.search(pattern, label, re.IGNORECASE)
        if match:
            return match.group(1)

    return None


def get_collection_from_shelfmark(shelfmark: str) -> str:
    """Determine collection based on shelfmark prefix."""
    for pattern, collection in COLLECTION_MAPPING.items():
        if re.match(pattern, shelfmark, re.IGNORECASE):
            return collection
    return "Manuscripts"


def extract_drs_id_from_url(url: str) -> Optional[str]:
    """Extract DRS ID from Harvard IIIF URL."""
    # Pattern: https://iiif.lib.harvard.edu/manifests/drs:12345678
    match = re.search(r'drs:(\d+)', url)
    if match:
        return match.group(1)
    return None


def extract_title_from_label(label: str, shelfmark: str) -> str:
    """
    Extract the title portion from a Harvard manifest label.

    The label typically has format:
    "Author. Title : subtitle : manuscript, [date]. MS Lat 249. Houghton Library..."

    We want to extract the title before the shelfmark.
    """
    if not label:
        return ""

    # Remove the shelfmark and everything after it
    if shelfmark:
        idx = label.find(shelfmark)
        if idx > 0:
            label = label[:idx].strip()

    # Remove trailing punctuation
    label = label.rstrip('.,;: ')

    # Remove "Houghton Library" suffix if present
    label = re.sub(r'\s*Houghton Library.*$', '', label, flags=re.IGNORECASE)

    # Truncate if too long
    if len(label) > 1000:
        label = label[:997] + "..."

    return label


def extract_date_from_label(label: str) -> Optional[str]:
    """
    Extract date from Harvard manifest label.

    Dates are typically in brackets: [ca. 1485], [15th century], [1400-1450]
    """
    # Look for bracketed date patterns
    match = re.search(r'\[([^\]]*\d[^\]]*)\]', label)
    if match:
        return match.group(1)
    return None


# =============================================================================
# Phase 1: Discovery (Biblissima Scraping)
# =============================================================================


def discover_from_biblissima(
    test_mode: bool = False,
    limit: Optional[int] = None,
) -> list[dict]:
    """
    Scrape Biblissima search results to discover Harvard Houghton manuscripts.

    Returns list of dicts with: drs_id, manifest_url, title, date
    """
    from bs4 import BeautifulSoup

    all_items = []
    page_offset = 0
    page_num = 1
    max_pages = 15  # 249 results / 20 per page = ~13 pages + buffer

    if test_mode:
        max_pages = 2
    elif limit:
        max_pages = (limit // RESULTS_PER_PAGE) + 2

    logger.info("Phase 1: Discovering manuscripts from Biblissima...")
    logger.info(f"Search URL: {BIBLISSIMA_SEARCH}")

    while page_num <= max_pages:
        url = BIBLISSIMA_SEARCH if page_offset == 0 else f"{BIBLISSIMA_SEARCH}&from={page_offset}"

        logger.info(f"  Page {page_num}/{max_pages} (offset {page_offset})...")

        html = fetch_url(url)
        if not html:
            logger.error(f"  Failed to fetch page {page_num}")
            break

        soup = BeautifulSoup(html, "html.parser")

        # Extract all Harvard IIIF manifest URLs from the page
        items_on_page = 0
        seen_on_page = set()

        # Find all links to Harvard IIIF manifests
        for link in soup.find_all("a", href=re.compile(r"iiif\.lib\.harvard\.edu/manifests/drs:\d+")):
            href = link.get("href", "")
            drs_id = extract_drs_id_from_url(href)

            if not drs_id or drs_id in seen_on_page:
                continue

            seen_on_page.add(drs_id)

            # Clean up manifest URL
            manifest_url = f"{HARVARD_IIIF_BASE}/drs:{drs_id}"

            item = {
                "drs_id": drs_id,
                "manifest_url": manifest_url,
            }

            # Try to find the parent card/result element for more metadata
            parent = link.find_parent(["div", "article", "section", "li"])
            if parent:
                # Look for title in nearby elements
                title_el = parent.select_one("h3, h4, h5, .title, .card-title")
                if title_el:
                    item["title"] = title_el.get_text(strip=True)

                # Look for thumbnail
                img = parent.select_one("img")
                if img and img.get("src"):
                    item["thumbnail_url"] = img.get("src")

                # Extract metadata from text
                text_content = parent.get_text(" ", strip=True)

                # Look for date patterns
                date_match = re.search(
                    r"(\d{1,2}(?:st|nd|rd|th)?\s*(?:century|cent\.?)|"
                    r"\d{4}\s*[-–]\s*\d{4}|\d{4})",
                    text_content, re.IGNORECASE
                )
                if date_match:
                    item["date"] = date_match.group(0)

            all_items.append(item)
            items_on_page += 1
            logger.debug(f"    Found: drs:{drs_id}")

        logger.info(f"    Found {items_on_page} manuscripts (total: {len(all_items)})")

        # Check for next page
        if items_on_page == 0:
            logger.info("  No more results, stopping discovery.")
            break

        # Stop conditions
        if test_mode and len(all_items) >= 10:
            logger.info("  Test mode: stopping early")
            break

        if limit and len(all_items) >= limit:
            logger.info(f"  Reached limit of {limit}")
            break

        # Move to next page
        page_offset += RESULTS_PER_PAGE
        page_num += 1

        # Rate limiting between pages
        if page_num <= max_pages:
            time.sleep(BIBLISSIMA_DELAY)

    # Deduplicate by drs_id
    seen_ids = set()
    unique_items = []
    for item in all_items:
        if item["drs_id"] not in seen_ids:
            seen_ids.add(item["drs_id"])
            unique_items.append(item)

    logger.info(f"Discovery complete: {len(unique_items)} unique manuscripts found")
    return unique_items


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


def mark_completed(progress: dict, drs_id: str, progress_path: Path):
    """Mark an item as completed and save checkpoint."""
    if drs_id not in progress["completed_ids"]:
        progress["completed_ids"].append(drs_id)
    if drs_id in progress["failed_ids"]:
        progress["failed_ids"].remove(drs_id)
    save_progress(progress, progress_path)


def mark_failed(progress: dict, drs_id: str, progress_path: Path):
    """Mark an item as failed and save checkpoint."""
    if drs_id not in progress["failed_ids"]:
        progress["failed_ids"].append(drs_id)
    save_progress(progress, progress_path)


# =============================================================================
# Phase 2: IIIF Manifest Parsing
# =============================================================================


def extract_metadata_value(metadata: list[dict], label: str) -> Optional[str]:
    """Extract a value from the IIIF metadata array by label."""
    for entry in metadata:
        entry_label = entry.get("label", "")

        # Handle various label formats
        if isinstance(entry_label, dict):
            entry_label = entry_label.get("@value", str(entry_label))
        if isinstance(entry_label, list):
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

    # Remove "ca." and "circa" prefixes
    date_str_clean = re.sub(r'\b(ca\.?|circa)\s*', '', date_str, flags=re.IGNORECASE)

    # Try explicit years: "1300-1400", "1350", "ca. 1410"
    years = re.findall(r"\b(\d{4})\b", date_str_clean)
    if len(years) >= 2:
        return int(years[0]), int(years[-1])
    if len(years) == 1:
        year = int(years[0])
        # For approximate dates, give a range
        if 'ca' in date_str.lower() or 'circa' in date_str.lower():
            return year - 25, year + 25
        return year, year

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
) -> Optional[dict]:
    """
    Parse a Harvard IIIF manifest into a Compilatio record.

    Harvard manifests have most metadata in the label field, not in metadata array.
    """
    metadata = manifest_data.get("metadata", [])
    drs_id = discovery_item.get("drs_id", "")

    # Get the manifest label - this contains most metadata for Harvard
    label = manifest_data.get("label", "")
    if isinstance(label, dict):
        label = label.get("@value", str(label))
    if isinstance(label, list):
        label = label[0] if label else ""
        if isinstance(label, dict):
            label = label.get("@value", "")

    # Extract shelfmark from label
    shelfmark = extract_shelfmark_from_label(label)
    if not shelfmark:
        # Try metadata array
        shelfmark = extract_metadata_value(metadata, "Call Number")
    if not shelfmark:
        shelfmark = extract_metadata_value(metadata, "Shelfmark")
    if not shelfmark:
        logger.warning(f"No shelfmark found for drs:{drs_id}")
        # Use DRS ID as fallback shelfmark
        shelfmark = f"DRS {drs_id}"

    # Determine collection from shelfmark
    collection = get_collection_from_shelfmark(shelfmark)

    record = {
        "shelfmark": shelfmark,
        "collection": collection,
        "iiif_manifest_url": manifest_url,
    }

    # Title / contents - extract from label
    title = extract_title_from_label(label, shelfmark)
    if not title:
        title = extract_metadata_value(metadata, "Title")
    if not title:
        title = discovery_item.get("title", "")
    if title:
        record["contents"] = title

    # Date - extract from label first
    date_str = extract_date_from_label(label)
    if not date_str:
        date_str = extract_metadata_value(metadata, "Date")
    if not date_str:
        date_str = extract_metadata_value(metadata, "Date of creation")
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
    extent = extract_metadata_value(metadata, "Physical Description")
    if not extent:
        extent = extract_metadata_value(metadata, "Extent")
    if extent:
        record["folios"] = extent

    # Language
    language = extract_metadata_value(metadata, "Language")
    if language:
        record["language"] = language

    # Provenance
    provenance = extract_metadata_value(metadata, "Provenance")
    if not provenance:
        provenance = extract_metadata_value(metadata, "Origin")
    if provenance:
        record["provenance"] = provenance

    # Thumbnail
    thumb = extract_thumbnail_url(manifest_data)
    if not thumb:
        thumb = discovery_item.get("thumbnail_url")
    if thumb:
        record["thumbnail_url"] = thumb

    # Image count
    image_count = count_canvases(manifest_data)
    if image_count > 0:
        record["image_count"] = image_count

    # Source URL (Harvard viewer link)
    record["source_url"] = f"{HARVARD_VIEWER_BASE}/drs:{drs_id}"

    return record


# =============================================================================
# Database Operations
# =============================================================================


def ensure_repository(cursor) -> int:
    """Ensure Harvard Houghton Library repository exists and return its ID."""
    cursor.execute(
        "SELECT id FROM repositories WHERE short_name = ?", ("Harvard",)
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
            "Houghton Library, Harvard University",
            "Harvard",
            None,
            "https://library.harvard.edu/collections/medieval-and-renaissance-manuscripts",
        ),
    )
    logger.info("Created repository: Houghton Library, Harvard University")
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


def import_harvard(
    db_path: Path,
    dry_run: bool = True,
    test_mode: bool = False,
    verbose: bool = False,
    limit: Optional[int] = None,
    discover_only: bool = False,
    skip_discovery: bool = False,
    resume: bool = False,
):
    """Import Harvard Houghton Library manuscripts."""
    if verbose:
        logger.setLevel(logging.DEBUG)

    # Load or initialize progress
    progress = load_progress(PROGRESS_FILE) if resume else {
        "last_updated": None,
        "total_discovered": 0,
        "completed_ids": [],
        "failed_ids": [],
        "phase": "discovery",
    }

    # Phase 1: Discovery
    items = None
    if skip_discovery:
        items = load_discovery_cache(DISCOVERY_CACHE)
        if items is None:
            logger.error("No discovery cache found. Run without --skip-discovery first.")
            return False
    else:
        # Try cache first if resuming
        if resume:
            items = load_discovery_cache(DISCOVERY_CACHE)

        if items is None:
            logger.info("Running Biblissima discovery...")
            items = discover_from_biblissima(test_mode=test_mode, limit=limit)
            if items:
                save_discovery_cache(items, DISCOVERY_CACHE)
                progress["total_discovered"] = len(items)
                progress["phase"] = "import"
                save_progress(progress, PROGRESS_FILE)

    if not items:
        logger.error("No items discovered")
        return False

    # Apply limits
    if test_mode:
        items = items[:5]
        logger.info("Test mode: limiting to 5 items")
    elif limit:
        items = items[:limit]
        logger.info(f"Limiting to {limit} items")

    logger.info(f"Processing {len(items)} Harvard manuscripts")

    if discover_only:
        print(f"\nDiscovery complete. {len(items)} manuscripts found.")
        print(f"Cache saved to: {DISCOVERY_CACHE}")
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
            if item["drs_id"] not in progress["completed_ids"]
        ]
        logger.info(
            f"Resuming: {len(progress['completed_ids'])} already completed, "
            f"{len(items_to_process)} remaining"
        )
    else:
        items_to_process = items

    logger.info(f"Phase 2: Fetching {len(items_to_process)} IIIF manifests...")

    for i, item in enumerate(items_to_process):
        drs_id = item["drs_id"]
        manifest_url = item.get("manifest_url", f"{HARVARD_IIIF_BASE}/drs:{drs_id}")

        logger.info(f"[{i+1}/{len(items_to_process)}] Fetching drs:{drs_id}...")

        manifest_data = fetch_json(manifest_url)
        if not manifest_data:
            fetch_errors += 1
            mark_failed(progress, drs_id, PROGRESS_FILE)
            logger.warning(f"  -> Failed to fetch manifest")
            continue

        record = parse_manifest(manifest_data, manifest_url, item)
        if record:
            records.append(record)
            mark_completed(progress, drs_id, PROGRESS_FILE)
            logger.debug(f"  -> {record['shelfmark']}")
        else:
            logger.warning(f"  -> Could not parse manifest for drs:{drs_id}")
            fetch_errors += 1
            mark_failed(progress, drs_id, PROGRESS_FILE)

        # Rate limit
        if i < len(items_to_process) - 1:
            time.sleep(MANIFEST_DELAY)

        # Progress logging
        if (i + 1) % 10 == 0:
            logger.info(
                f"Progress: {i+1}/{len(items_to_process)} manifests, "
                f"{len(records)} parsed, {fetch_errors} errors"
            )

    logger.info(
        f"Fetched {len(items_to_process)} manifests, "
        f"parsed {len(records)} records, {fetch_errors} errors"
    )

    # Phase 3: Database operations
    logger.info("Phase 3: Database operations...")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    repo_id = ensure_repository(cursor) if not dry_run else 1

    stats = {
        "total_discovered": progress.get("total_discovered", len(items)),
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
                    logger.debug(f"  Updated: {shelfmark}")
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
                    logger.debug(f"  Inserted: {shelfmark}")

            except Exception as e:
                stats["db_errors"] += 1
                logger.error(f"Error importing {shelfmark}: {e}")

    if not dry_run:
        conn.commit()
        logger.info(f"Committed {stats['inserted']} inserts, {stats['updated']} updates")
    conn.close()

    # Print summary
    print("\n" + "=" * 70)
    print(
        f"{'DRY RUN - ' if dry_run else ''}"
        f"HARVARD HOUGHTON LIBRARY IMPORT SUMMARY"
    )
    print("=" * 70)
    print(f"\nDiscovery (Biblissima):")
    print(f"  Total discovered:     {stats['total_discovered']}")
    print(f"\nIIIF Manifest Fetch (Harvard DRS):")
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
        description="Import Harvard Houghton Library manuscripts into Compilatio"
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

    args = parser.parse_args()

    print("=" * 70)
    print("Compilatio Harvard Houghton Library Import Tool")
    print("=" * 70)
    print(f"Source: Harvard Digital Collections via Biblissima")
    print(f"DB:     {args.db}")
    print(f"Cache:  {DISCOVERY_CACHE}")

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
    if args.skip_discovery:
        mode_parts.append("SKIP-DISCOVERY")

    print(f"Mode:   {' + '.join(mode_parts)}")
    if args.limit:
        print(f"Limit:  {args.limit}")
    print()

    success = import_harvard(
        db_path=args.db,
        dry_run=not args.execute,
        test_mode=args.test,
        verbose=args.verbose,
        limit=args.limit,
        discover_only=args.discover_only,
        skip_discovery=args.skip_discovery,
        resume=args.resume,
    )
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
