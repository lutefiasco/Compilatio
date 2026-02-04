#!/usr/bin/env python3
"""
Trinity College Dublin Manuscript Import Script for Compilatio.

Imports digitized medieval manuscripts from TCD Digital Collections.
Uses Internet Archive's Wayback Machine to bypass Cloudflare/reCAPTCHA
protection by fetching archived Dublin Core XML metadata.

Two-phase process with checkpoint resumability:
  Phase 1 (Discovery): Query Internet Archive CDX API for archived Dublin Core
    exports, collecting work IDs and timestamps
  Phase 2 (Import): Fetch archived Dublin Core XML for each work, parse metadata,
    filter to medieval manuscripts, insert to database

IMPORTANT: Book of Kells (MS 58) is EXCLUDED from import.

No special dependencies required - uses standard library only.

Source:
    Internet Archive: web.archive.org/cdx/search
    Dublin Core: digitalcollections.tcd.ie/export/dublinCore.xml?id={work_id}

Usage:
    python scripts/importers/trinity_dublin.py                    # Dry-run
    python scripts/importers/trinity_dublin.py --execute          # Import
    python scripts/importers/trinity_dublin.py --resume --execute # Resume
    python scripts/importers/trinity_dublin.py --discover-only    # Discovery only
    python scripts/importers/trinity_dublin.py --skip-discovery   # Use cache
    python scripts/importers/trinity_dublin.py --test             # First 5 only
    python scripts/importers/trinity_dublin.py --verbose          # Detailed logging
"""

import argparse
import json
import logging
import re
import sqlite3
import sys
import time
import xml.etree.ElementTree as ET
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
DISCOVERY_CACHE = CACHE_DIR / "trinity_dublin_discovery.json"
PROGRESS_FILE = CACHE_DIR / "trinity_dublin_progress.json"
HTML_CURATED_CACHE = CACHE_DIR / "tcd_html_manuscripts.json"

# TCD Digital Collections URLs
TCD_BASE = "https://digitalcollections.tcd.ie"
WAYBACK_CDX = "https://web.archive.org/cdx/search/cdx"
WAYBACK_WEB = "https://web.archive.org/web"

# Repository metadata
REPO_NAME = "Trinity College Dublin"
REPO_SHORT = "TCD"
CATALOGUE_URL = "https://www.tcd.ie/library/manuscripts/"

# Rate limiting
REQUEST_DELAY = 0.5  # seconds between archive requests

# Medieval manuscript MS number ranges (approximate)
# TCD medieval manuscripts are generally MS 1-700 and some special collections
MEDIEVAL_MS_RANGES = [
    (1, 700),      # Core medieval collection
    (10000, 11000), # Some medieval in this range
]

# EXCLUSIONS - manuscripts to skip
EXCLUDED_MS_NUMBERS = {
    "58",  # Book of Kells - excluded per project requirements
}

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

USER_AGENT = "Compilatio/1.0 (Academic manuscript research; IIIF aggregator)"


# =============================================================================
# Curated Whitelist Support
# =============================================================================


def load_curated_whitelist(cache_path: Path = HTML_CURATED_CACHE) -> dict:
    """
    Load curated manuscripts from HTML export cache.
    Returns dict mapping work_id -> {shelfmark, collection}.
    """
    if not cache_path.exists():
        logger.warning(f"Curated cache not found: {cache_path}")
        return {}

    with open(cache_path) as f:
        items = json.load(f)

    whitelist = {}
    for item in items:
        work_id = item.get("work_id")
        if work_id:
            whitelist[work_id] = {
                "shelfmark": item.get("shelfmark"),
                "collection": item.get("collection"),
            }

    logger.info(f"Loaded {len(whitelist)} curated manuscripts from {cache_path}")
    return whitelist


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


def mark_completed(progress: dict, work_id: str, progress_path: Path):
    """Mark a work as completed and save checkpoint."""
    if work_id not in progress["completed_ids"]:
        progress["completed_ids"].append(work_id)
    if work_id in progress["failed_ids"]:
        progress["failed_ids"].remove(work_id)
    save_progress(progress, progress_path)


def mark_failed(progress: dict, work_id: str, progress_path: Path):
    """Mark a work as failed and save checkpoint."""
    if work_id not in progress["failed_ids"]:
        progress["failed_ids"].append(work_id)
    save_progress(progress, progress_path)


# =============================================================================
# HTTP Helpers
# =============================================================================


def fetch_url(url: str, retries: int = 3) -> Optional[str]:
    """Fetch a URL and return content as string. Handles gzip compression."""
    import gzip

    for attempt in range(retries):
        try:
            req = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(req, timeout=60) as resp:
                raw = resp.read()
                # Handle gzip compression (common with Archive.org)
                if raw[:2] == b'\x1f\x8b':
                    return gzip.decompress(raw).decode("utf-8")
                return raw.decode("utf-8")
        except (HTTPError, URLError) as e:
            if attempt < retries - 1:
                logger.debug(f"Retry {attempt + 1}/{retries} for {url}: {e}")
                time.sleep(2)
            else:
                logger.debug(f"Failed to fetch {url}: {e}")
                return None
    return None


def fetch_json(url: str, retries: int = 3) -> Optional[list]:
    """Fetch a URL and parse as JSON."""
    content = fetch_url(url, retries)
    if content:
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            logger.warning(f"JSON parse error for {url}: {e}")
    return None


# =============================================================================
# Filtering Functions
# =============================================================================


def extract_ms_number(shelfmark: str) -> Optional[str]:
    """Extract MS number from shelfmark like 'IE TCD MS 94' -> '94'."""
    if not shelfmark:
        return None
    match = re.search(r'MS\s*(\d+)', shelfmark, re.IGNORECASE)
    return match.group(1) if match else None


def is_excluded(shelfmark: str) -> bool:
    """Check if a manuscript should be excluded."""
    ms_num = extract_ms_number(shelfmark)
    if ms_num and ms_num in EXCLUDED_MS_NUMBERS:
        return True
    return False


def is_medieval_candidate(shelfmark: str, whitelist: dict = None, work_id: str = None) -> bool:
    """
    Check if shelfmark might be a medieval manuscript.

    If whitelist is provided and work_id is in it, returns True (trusted curated list).
    Otherwise falls back to MS number range check.
    """
    # Check whitelist first (curated list is authoritative)
    if whitelist and work_id and work_id in whitelist:
        return True

    ms_num = extract_ms_number(shelfmark)
    if not ms_num:
        return False

    try:
        num = int(ms_num)
        for start, end in MEDIEVAL_MS_RANGES:
            if start <= num <= end:
                return True
    except ValueError:
        pass

    return False


# =============================================================================
# Phase 1: Discovery via Internet Archive
# =============================================================================


def discover_via_archive(
    test_mode: bool = False,
    limit: Optional[int] = None,
) -> list[dict]:
    """
    Query Internet Archive CDX API to discover TCD Dublin Core exports.

    Returns list of dicts with: work_id, timestamp, archived_url
    """
    logger.info("Phase 1: Querying Internet Archive CDX API...")

    # Query for Dublin Core exports
    cdx_url = (
        f"{WAYBACK_CDX}?url=digitalcollections.tcd.ie/export/dublinCore*"
        f"&output=json&limit=5000"
    )

    logger.info(f"  CDX query: {cdx_url}")

    data = fetch_json(cdx_url)
    if not data or len(data) < 2:
        logger.error("No results from CDX API")
        return []

    # Parse CDX results (first row is header)
    work_ids = {}
    for row in data[1:]:
        timestamp = row[1]
        url = row[2]
        status = row[4]

        # Only use successful fetches
        if status != "200":
            continue

        # Extract work ID from URL
        match = re.search(r'id=([a-z0-9]+)', url)
        if not match:
            continue

        work_id = match.group(1)

        # Keep the most recent timestamp for each work
        if work_id not in work_ids or timestamp > work_ids[work_id]:
            work_ids[work_id] = timestamp

    logger.info(f"  Found {len(work_ids)} unique work IDs with archived Dublin Core")

    # Convert to list
    # Use id_ suffix to get raw content instead of Archive wrapper HTML
    items = [
        {
            "work_id": wid,
            "timestamp": ts,
            "archived_url": f"{WAYBACK_WEB}/{ts}id_/https://digitalcollections.tcd.ie/export/dublinCore.xml?id={wid}",
        }
        for wid, ts in work_ids.items()
    ]

    # Apply limits
    if test_mode:
        items = items[:5]
        logger.info("  Test mode: limiting to 5 items")
    elif limit:
        items = items[:limit]
        logger.info(f"  Limiting to {limit} items")

    return items


def discover_specific_work_ids(work_ids: list[str]) -> list[dict]:
    """
    Query Archive CDX API for specific work IDs to find their archived timestamps.

    Returns list of dicts with: work_id, timestamp, archived_url
    """
    logger.info(f"Discovering Archive timestamps for {len(work_ids)} specific work IDs...")

    items = []
    for i, work_id in enumerate(work_ids):
        if (i + 1) % 10 == 0:
            logger.info(f"  Checking {i+1}/{len(work_ids)}...")

        # Query CDX for this specific work
        cdx_url = (
            f"{WAYBACK_CDX}?url=digitalcollections.tcd.ie/export/dublinCore.xml?id={work_id}"
            f"&output=json&limit=5"
        )

        data = fetch_json(cdx_url)
        if not data or len(data) < 2:
            # Try direct fetch with "id_" for most recent capture
            items.append({
                "work_id": work_id,
                "timestamp": None,
                "archived_url": f"{WAYBACK_WEB}/id_/{TCD_BASE}/export/dublinCore.xml?id={work_id}",
            })
            time.sleep(0.3)
            continue

        # Get most recent successful capture
        for row in reversed(data[1:]):
            timestamp = row[1]
            status = row[4]
            if status == "200":
                items.append({
                    "work_id": work_id,
                    "timestamp": timestamp,
                    "archived_url": f"{WAYBACK_WEB}/{timestamp}id_/{TCD_BASE}/export/dublinCore.xml?id={work_id}",
                })
                break
        else:
            # No successful capture found, try latest
            items.append({
                "work_id": work_id,
                "timestamp": None,
                "archived_url": f"{WAYBACK_WEB}/id_/{TCD_BASE}/export/dublinCore.xml?id={work_id}",
            })

        time.sleep(0.3)

    logger.info(f"  Found/created {len(items)} Archive URLs")
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
# Phase 2: Dublin Core XML Parsing
# =============================================================================


def parse_dublin_core_xml(xml_content: str, work_id: str) -> Optional[dict]:
    """
    Parse Dublin Core XML into a manuscript record.

    Example fields:
    - dc:title -> contents
    - dc:identifier -> shelfmark, DOI
    - dcterms:created -> date
    - dc:language -> language
    - dc:description -> description (for contents if no title)
    - dcterms:provenance -> provenance
    """
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as e:
        logger.warning(f"XML parse error for {work_id}: {e}")
        return None

    # Namespace mapping
    ns = {
        "dc": "http://purl.org/dc/elements/1.1/",
        "dcterms": "http://purl.org/dc/terms/",
    }

    def get_text(tag: str, namespace: str = "dc") -> Optional[str]:
        elem = root.find(f"{namespace}:{tag}", ns)
        return elem.text.strip() if elem is not None and elem.text else None

    def get_all_text(tag: str, namespace: str = "dc") -> list[str]:
        elems = root.findall(f"{namespace}:{tag}", ns)
        return [e.text.strip() for e in elems if e.text]

    # Extract identifiers
    identifiers = get_all_text("identifier")
    shelfmark = None
    doi = None

    for ident in identifiers:
        if "IE TCD MS" in ident or "TCD MS" in ident:
            shelfmark = ident
        elif "doi.org" in ident.lower() or ident.startswith("DOI:"):
            doi = ident

    if not shelfmark:
        # Try to construct from work_id
        shelfmark = f"TCD {work_id}"

    # Check exclusions
    if is_excluded(shelfmark):
        logger.info(f"  Excluding {shelfmark} (in exclusion list)")
        return None

    record = {
        "work_id": work_id,
        "shelfmark": shelfmark,
        "iiif_manifest_url": f"{TCD_BASE}/concern/works/{work_id}/manifest",
        "source_url": f"{TCD_BASE}/concern/works/{work_id}",
    }

    # Title / contents
    title = get_text("title")
    if title:
        record["contents"] = title[:1000]
    else:
        # Fall back to description
        desc = get_text("description")
        if desc:
            record["contents"] = desc[:1000]

    # Date
    date_created = get_text("created", "dcterms")
    if date_created:
        record["date_display"] = date_created
        # Try to parse years
        years = re.findall(r"\b(\d{4})\b", date_created)
        if years:
            record["date_start"] = int(years[0])
            record["date_end"] = int(years[-1])
        else:
            # Try century pattern
            century_match = re.search(r"(\d{1,2})(?:st|nd|rd|th)?\s*century", date_created, re.I)
            if century_match:
                c = int(century_match.group(1))
                record["date_start"] = (c - 1) * 100
                record["date_end"] = c * 100 - 1

    # Language
    language = get_text("language")
    if language:
        record["language"] = language

    # Provenance
    provenance = get_text("provenance", "dcterms")
    if provenance:
        record["provenance"] = provenance[:1000]

    # Collection - determine from shelfmark or subject
    subjects = get_all_text("subject")
    if any("medieval" in s.lower() for s in subjects):
        record["collection"] = "Medieval Manuscripts"
    elif any("latin" in s.lower() for s in subjects):
        record["collection"] = "Medieval Latin Manuscripts"
    elif any("greek" in s.lower() for s in subjects):
        record["collection"] = "Medieval Greek Manuscripts"
    else:
        record["collection"] = "Manuscripts"

    return record


# =============================================================================
# Database Operations
# =============================================================================


def ensure_repository(cursor) -> int:
    """Ensure TCD repository exists and return its ID."""
    cursor.execute(
        "SELECT id FROM repositories WHERE short_name = ?", (REPO_SHORT,)
    )
    row = cursor.fetchone()
    if row:
        return row[0]

    cursor.execute(
        """
        INSERT INTO repositories (name, short_name, logo_url, catalogue_url)
        VALUES (?, ?, ?, ?)
    """,
        (REPO_NAME, REPO_SHORT, None, CATALOGUE_URL),
    )
    logger.info(f"Created repository: {REPO_NAME}")
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


def import_tcd(
    db_path: Path,
    dry_run: bool = True,
    test_mode: bool = False,
    verbose: bool = False,
    limit: Optional[int] = None,
    discover_only: bool = False,
    skip_discovery: bool = False,
    resume: bool = False,
    medieval_only: bool = True,
    curated_only: bool = False,
):
    """Main import function."""
    if verbose:
        logger.setLevel(logging.DEBUG)

    # Ensure cache directory exists
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Load curated whitelist if using curated mode
    whitelist = {}
    if curated_only or medieval_only:
        whitelist = load_curated_whitelist()
        if curated_only and not whitelist:
            logger.error("Curated mode requires tcd_html_manuscripts.json cache")
            return False

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
        if resume:
            items = load_discovery_cache(DISCOVERY_CACHE)

        if items is None:
            items = discover_via_archive(test_mode=test_mode, limit=limit)
            if items:
                save_discovery_cache(items, DISCOVERY_CACHE)
                progress["total_discovered"] = len(items)
                progress["phase"] = "import"
                if not dry_run:
                    save_progress(progress, PROGRESS_FILE)

    if not items:
        logger.error("No items discovered")
        return False

    # Filter to curated items only if requested
    if curated_only and whitelist:
        curated_ids = set(whitelist.keys())
        original_count = len(items)
        items = [item for item in items if item["work_id"] in curated_ids]
        logger.info(f"Curated filter: {len(items)}/{original_count} items match whitelist")

        # Check for curated items not in archive discovery
        discovered_ids = {item["work_id"] for item in items}
        missing_ids = curated_ids - discovered_ids
        if missing_ids:
            # Exclude Book of Kells (MS 58 = hm50tr726)
            kells_id = "hm50tr726"
            if kells_id in missing_ids:
                missing_ids.discard(kells_id)
                logger.info(f"  Excluding Book of Kells from missing list")

            if missing_ids:
                logger.warning(f"  {len(missing_ids)} curated items not in Archive discovery")
                logger.info(f"  (Use --discover-missing to query Archive for these items)")
                # Print sample of missing items
                sample = list(missing_ids)[:5]
                for wid in sample:
                    info = whitelist.get(wid, {})
                    logger.debug(f"    Missing: {wid} -> {info.get('shelfmark', '?')}")

    # Apply limits if not already applied
    if test_mode and len(items) > 5:
        items = items[:5]
    elif limit and len(items) > limit:
        items = items[:limit]

    logger.info(f"\nProcessing {len(items)} TCD items")

    if discover_only:
        print(f"\nDiscovery complete. {len(items)} items found.")
        print(f"Cache saved to: {DISCOVERY_CACHE}")
        return True

    # Phase 2: Fetch Dublin Core XML and parse
    if not db_path.exists():
        logger.error(f"Database not found: {db_path}")
        return False

    # Filter to items not yet completed
    if resume and progress["completed_ids"]:
        items_to_process = [
            item for item in items
            if item["work_id"] not in progress["completed_ids"]
        ]
        logger.info(
            f"Resuming: {len(progress['completed_ids'])} completed, "
            f"{len(items_to_process)} remaining"
        )
    else:
        items_to_process = items

    records = []
    fetch_errors = 0
    skipped_non_medieval = 0

    logger.info(f"\nPhase 2: Fetching {len(items_to_process)} Dublin Core XMLs from Archive...")

    for i, item in enumerate(items_to_process):
        work_id = item["work_id"]
        archived_url = item["archived_url"]

        logger.info(f"[{i+1}/{len(items_to_process)}] Fetching {work_id}...")

        xml_content = fetch_url(archived_url)

        if not xml_content:
            fetch_errors += 1
            if not dry_run:
                mark_failed(progress, work_id, PROGRESS_FILE)
            logger.warning(f"  -> Failed to fetch")
            time.sleep(REQUEST_DELAY)
            continue

        # Check if we got HTML (error page) instead of XML
        if xml_content.strip().startswith("<!DOCTYPE") or "<html" in xml_content[:500].lower():
            fetch_errors += 1
            if not dry_run:
                mark_failed(progress, work_id, PROGRESS_FILE)
            logger.warning(f"  -> Got HTML instead of XML (archive error)")
            time.sleep(REQUEST_DELAY)
            continue

        record = parse_dublin_core_xml(xml_content, work_id)

        if record:
            # Filter to medieval if requested
            # Pass whitelist so curated items bypass MS range check
            if medieval_only and not is_medieval_candidate(
                record.get("shelfmark", ""), whitelist=whitelist, work_id=work_id
            ):
                skipped_non_medieval += 1
                logger.debug(f"  -> Skipped (not medieval): {record.get('shelfmark')}")
                if not dry_run:
                    mark_completed(progress, work_id, PROGRESS_FILE)
                time.sleep(REQUEST_DELAY)
                continue

            records.append(record)
            if not dry_run:
                mark_completed(progress, work_id, PROGRESS_FILE)
            logger.info(f"  -> {record['shelfmark']}: {record.get('contents', '')[:50]}")
        else:
            if not dry_run:
                mark_completed(progress, work_id, PROGRESS_FILE)  # Mark as done even if excluded

        # Progress logging
        if (i + 1) % 25 == 0:
            logger.info(
                f"Progress: {i+1}/{len(items_to_process)}, "
                f"{len(records)} parsed, {fetch_errors} errors, {skipped_non_medieval} non-medieval"
            )

        time.sleep(REQUEST_DELAY)

    logger.info(
        f"\nFetched {len(items_to_process)} items, "
        f"parsed {len(records)} medieval records, "
        f"{fetch_errors} errors, {skipped_non_medieval} non-medieval skipped"
    )

    # Phase 3: Database operations
    logger.info("\nPhase 3: Database operations...")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    repo_id = ensure_repository(cursor) if not dry_run else 1
    if not dry_run:
        conn.commit()

    stats = {
        "total_discovered": progress.get("total_discovered", len(items)),
        "items_processed": len(items_to_process),
        "records_parsed": len(records),
        "fetch_errors": fetch_errors,
        "skipped_non_medieval": skipped_non_medieval,
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
                            date_end = ?, contents = ?, language = ?,
                            provenance = ?, iiif_manifest_url = ?, source_url = ?
                        WHERE id = ?
                    """,
                        (
                            record.get("collection"),
                            record.get("date_display"),
                            record.get("date_start"),
                            record.get("date_end"),
                            record.get("contents"),
                            record.get("language"),
                            record.get("provenance"),
                            record["iiif_manifest_url"],
                            record.get("source_url"),
                            existing_id,
                        ),
                    )
                    stats["updated"] += 1
                else:
                    cursor.execute(
                        """
                        INSERT INTO manuscripts (
                            repository_id, shelfmark, collection, date_display,
                            date_start, date_end, contents, language, provenance,
                            iiif_manifest_url, source_url
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                        (
                            repo_id,
                            shelfmark,
                            record.get("collection"),
                            record.get("date_display"),
                            record.get("date_start"),
                            record.get("date_end"),
                            record.get("contents"),
                            record.get("language"),
                            record.get("provenance"),
                            record["iiif_manifest_url"],
                            record.get("source_url"),
                        ),
                    )
                    stats["inserted"] += 1

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
        "TRINITY COLLEGE DUBLIN IMPORT SUMMARY"
    )
    print("=" * 70)
    print(f"\nDiscovery (Internet Archive):")
    print(f"  Total discovered:     {stats['total_discovered']}")
    print(f"\nDublin Core XML Fetch:")
    print(f"  Items processed:      {stats['items_processed']}")
    print(f"  Medieval records:     {stats['records_parsed']}")
    print(f"  Fetch errors:         {stats['fetch_errors']}")
    print(f"  Non-medieval skipped: {stats['skipped_non_medieval']}")
    print(f"\nDatabase Operations {'(would be)' if dry_run else ''}:")
    print(f"  {'Would insert' if dry_run else 'Inserted'}:  {stats['inserted']}")
    print(f"  {'Would update' if dry_run else 'Updated'}:   {stats['updated']}")
    print(f"  Errors:               {stats['db_errors']}")

    if results.get("inserted"):
        print("\n" + "-" * 70)
        print(f"RECORDS TO {'INSERT' if dry_run else 'INSERTED'} (sample):")
        print("-" * 70)
        for rec in results["inserted"][:15]:
            date = f" ({rec.get('date_display', '')})" if rec.get("date_display") else ""
            print(f"  {rec['shelfmark']}{date}")
            if rec.get("contents"):
                contents = rec["contents"]
                if len(contents) > 60:
                    contents = contents[:60] + "..."
                print(f"    {contents}")
        remaining = len(results["inserted"]) - 15
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
        description="Import Trinity College Dublin manuscripts into Compilatio"
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
        help="Test mode: limit to first 5 items",
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
        help="Limit number of items to process",
    )
    parser.add_argument(
        "--all-manuscripts",
        action="store_true",
        help="Include all manuscripts, not just medieval (MS 1-700)",
    )
    parser.add_argument(
        "--curated",
        action="store_true",
        help="Only import manuscripts from curated HTML list (99 items)",
    )

    args = parser.parse_args()

    print("=" * 70)
    print("Compilatio Trinity College Dublin Import Tool")
    print("=" * 70)
    print(f"Source: Internet Archive (Dublin Core XML)")
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
    if args.curated:
        print(f"Source: Curated HTML list ({HTML_CURATED_CACHE.name})")
    else:
        print(f"Filter: {'All manuscripts' if args.all_manuscripts else 'Medieval only (MS 1-700)'}")
    print(f"\nNote: Book of Kells (MS 58) is EXCLUDED from import.")
    print()

    try:
        success = import_tcd(
            db_path=args.db,
            dry_run=not args.execute,
            test_mode=args.test,
            verbose=args.verbose,
            limit=args.limit,
            discover_only=args.discover_only,
            skip_discovery=args.skip_discovery,
            resume=args.resume,
            medieval_only=not args.all_manuscripts,
            curated_only=args.curated,
        )
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        logger.info("\nInterrupted by user. Progress saved to checkpoint.")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Import failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
