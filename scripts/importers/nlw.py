#!/usr/bin/env python3
"""
National Library of Wales (Peniarth) Manuscript Import Script for Compilatio.

Imports digitized Peniarth manuscripts from the NLW archives catalogue.
Uses crawl4ai to bypass Cloudflare protection on archives.library.wales,
then fetches IIIF manifests from damsssl.llgc.org.uk for metadata.

Two-phase process:
  Phase 1 (Discovery): Crawl archives.library.wales with crawl4ai to find
    manuscript slugs and handle PIDs. Results cached to JSON.
  Phase 2 (Import): Fetch IIIF manifests via plain HTTP, parse metadata,
    and insert into the Compilatio database.

Dependencies:
    pip install crawl4ai beautifulsoup4
    crawl4ai-setup

Source:
    https://archives.library.wales/index.php/informationobject/browse
        ?collection=2263950&onlyMedia=1&topLod=0&view=table
        &sort=identifier&sortDir=asc

Usage:
    python scripts/importers/nlw.py                    # Dry-run mode
    python scripts/importers/nlw.py --execute          # Actually import
    python scripts/importers/nlw.py --discover-only    # Only run discovery
    python scripts/importers/nlw.py --test             # First 5 only
    python scripts/importers/nlw.py --verbose          # Detailed logging
"""

import argparse
import asyncio
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
CACHE_PATH = PROJECT_ROOT / "data" / "nlw_peniarth_discovery.json"

# NLW URLs
ARCHIVES_BASE = "https://archives.library.wales"
BROWSE_URL = (
    ARCHIVES_BASE
    + "/index.php/informationobject/browse"
    + "?view=table&sort=identifier&collection=2263950"
    + "&onlyMedia=1&topLod=0&sortDir=asc"
)
IIIF_BASE = "https://damsssl.llgc.org.uk/iiif/2.0"
VIEWER_BASE = "https://viewer.library.wales"

# Rate limiting
MANIFEST_DELAY = 0.3  # seconds between IIIF manifest fetches

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
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
# Phase 1: Discovery (crawl4ai)
# =============================================================================


async def discover_manuscripts(
    test_mode: bool = False,
    limit: int = None,
) -> list[dict]:
    """
    Crawl archives.library.wales to discover Peniarth manuscripts.

    Returns list of dicts with keys: slug, title, shelfmark, date, pid
    """
    from bs4 import BeautifulSoup
    from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig

    browser_config = BrowserConfig(headless=True)
    crawl_config = CrawlerRunConfig(
        wait_until="domcontentloaded",
        page_timeout=60000,
        delay_before_return_html=8.0,
    )

    all_items = []
    max_browse_items = None
    if test_mode:
        max_browse_items = 20  # one page is enough for test mode
    elif limit:
        max_browse_items = limit

    async with AsyncWebCrawler(config=browser_config) as crawler:
        # Step 1: Crawl browse pages to collect slugs
        logger.info("Phase 1a: Crawling browse pages for manuscript slugs...")
        page_num = 1

        while True:
            url = BROWSE_URL if page_num == 1 else f"{BROWSE_URL}&page={page_num}"
            logger.info(f"  Browse page {page_num}...")

            result = await crawler.arun(url=url, config=crawl_config)
            soup = BeautifulSoup(result.html, "html.parser")

            articles = soup.select("article")
            if not articles:
                logger.info(f"  No articles on page {page_num}, stopping.")
                break

            for art in articles:
                link = art.select_one("a")
                if not link:
                    continue

                slug = link.get("href", "")
                text = art.get_text(" | ", strip=True)

                # Title is the first text segment before "Add to clipboard"
                title = ""
                parts = text.split(" | ")
                if parts:
                    title = parts[0].strip().rstrip(",")

                # Parse: "Title | Add to clipboard | Shelfmark. | File | [Date] | ..."
                shelfmark_match = re.search(
                    r"(Peniarth MS \d+[A-Za-z]*(?:\s*\([^)]+\))?)",
                    text,
                )
                # Match any bracketed date-like text (centuries, years, ranges)
                date_match = re.search(r"\[([^\]]*\d[^\]]*)\]", text)

                item = {
                    "slug": slug,
                    "title": title,
                    "shelfmark": shelfmark_match.group(1) if shelfmark_match else None,
                    "date_text": date_match.group(0) if date_match else None,
                }
                all_items.append(item)

            logger.info(
                f"  Found {len(articles)} items (total: {len(all_items)})"
            )

            # Stop if we have enough items for test/limit mode
            if max_browse_items and len(all_items) >= max_browse_items:
                logger.info(f"  Reached {max_browse_items} items, stopping browse.")
                break

            # Check for next page
            next_link = soup.select_one("li.next a")
            if not next_link:
                break
            page_num += 1

        logger.info(f"Found {len(all_items)} manuscripts across {page_num} pages")

        # Apply limits
        if test_mode:
            all_items = all_items[:5]
            logger.info("Test mode: limiting to 5 items")
        elif limit:
            all_items = all_items[:limit]
            logger.info(f"Limiting to {limit} items")

        # Step 2: Visit each detail page to extract handle PID
        logger.info(
            f"\nPhase 1b: Fetching {len(all_items)} detail pages for PIDs..."
        )
        errors = 0

        for i, item in enumerate(all_items):
            slug = item["slug"]
            url = (
                ARCHIVES_BASE + slug if slug.startswith("/") else slug
            )

            logger.info(
                f"  [{i+1}/{len(all_items)}] {item.get('shelfmark', slug)}"
            )

            try:
                result = await crawler.arun(url=url, config=crawl_config)
                soup = BeautifulSoup(result.html, "html.parser")

                # Extract handle PID from "Existence and location of copies"
                for field in soup.select(".field"):
                    label = field.select_one("h3")
                    if not label:
                        continue
                    label_text = label.get_text(strip=True)

                    if "Existence" in label_text:
                        body = field.get_text(strip=True)
                        match = re.search(r"10107/(\d+)", body)
                        if match:
                            item["pid"] = match.group(1)

                    # Also grab language and extent from detail page
                    if "Language" in label_text and "language" not in item:
                        body_el = field.select_one(".field-body")
                        if body_el:
                            item["language"] = body_el.get_text(strip=True)

                    if "Scope and content" in label_text and "contents" not in item:
                        body_el = field.select_one(".field-body")
                        if body_el:
                            text = body_el.get_text(strip=True)
                            item["contents"] = (
                                text[:1000] if len(text) > 1000 else text
                            )

                    if "Extent" in label_text and "extent" not in item:
                        body_el = field.select_one(".field-body")
                        if body_el:
                            item["extent"] = body_el.get_text(strip=True)

                    if "Archival history" in label_text and "provenance" not in item:
                        body_el = field.select_one(".field-body")
                        if body_el:
                            text = body_el.get_text(strip=True)
                            item["provenance"] = (
                                text[:1000] if len(text) > 1000 else text
                            )

                if "pid" not in item:
                    logger.warning(f"    No handle PID found for {slug}")
                    errors += 1
                else:
                    logger.debug(f"    PID: {item['pid']}")

            except Exception as e:
                logger.error(f"    Error fetching {slug}: {e}")
                errors += 1

            if (i + 1) % 25 == 0:
                logger.info(
                    f"  Progress: {i+1}/{len(all_items)} detail pages fetched"
                )

        found = sum(1 for item in all_items if "pid" in item)
        logger.info(
            f"Discovery complete: {found}/{len(all_items)} PIDs found, "
            f"{errors} errors"
        )

    return all_items


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


def extract_metadata_value(metadata: list[dict], label: str) -> Optional[str]:
    """Extract a value from the IIIF metadata array by label.

    NLW manifests use bilingual labels:
        [{"@value": "Title", "@language": "en"},
         {"@value": "Teitl", "@language": "cy-GB"}]
    """
    for entry in metadata:
        entry_label = entry.get("label", "")

        # Handle bilingual label arrays
        if isinstance(entry_label, list):
            matched = False
            for lbl in entry_label:
                if isinstance(lbl, dict):
                    val = lbl.get("@value", "")
                    if val.lower().strip() == label.lower().strip():
                        matched = True
                        break
                elif isinstance(lbl, str):
                    if lbl.lower().strip() == label.lower().strip():
                        matched = True
                        break
            if not matched:
                continue
        elif isinstance(entry_label, dict):
            if entry_label.get("@value", "").lower().strip() != label.lower().strip():
                continue
        elif isinstance(entry_label, str):
            if entry_label.lower().strip() != label.lower().strip():
                continue
        else:
            continue

        value = entry.get("value", "")
        if isinstance(value, list):
            for v in value:
                if isinstance(v, dict):
                    return v.get("@value", str(v))
            value = "; ".join(str(v) for v in value)
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
    # Try explicit years: "1300-1400", "1350"
    years = re.findall(r"\b(\d{4})\b", date_str)
    if len(years) >= 2:
        return int(years[0]), int(years[-1])
    if len(years) == 1:
        return int(years[0]), int(years[0])

    # Century patterns: "13 cent.", "mid-14 cent.", "15 cent., second ½"
    century_matches = re.findall(
        r"(\d{1,2})\s*(?:st|nd|rd|th)?\s*cent", date_str, re.IGNORECASE
    )
    if century_matches:
        first = (int(century_matches[0]) - 1) * 100
        last = (int(century_matches[-1]) - 1) * 100 + 99
        return first, last

    return None, None


def parse_manifest(
    manifest_data: dict,
    manifest_url: str,
    discovery_item: dict,
) -> Optional[dict]:
    """Parse an NLW IIIF manifest into a Compilatio record."""
    metadata = manifest_data.get("metadata", [])

    # Shelfmark: prefer discovery data, fall back to manifest
    shelfmark = discovery_item.get("shelfmark")
    if not shelfmark:
        shelfmark_raw = extract_metadata_value(metadata, "Title") or ""
        # Try to extract "Peniarth MS X" from the title
        match = re.search(
            r"(Peniarth MS \d+[A-Za-z]*(?:\s*\([^)]+\))?)", shelfmark_raw
        )
        if match:
            shelfmark = match.group(1)
        else:
            shelfmark = manifest_data.get("label", "Unknown")

    record = {
        "shelfmark": shelfmark,
        "collection": "Peniarth",
        "iiif_manifest_url": manifest_url,
    }

    # Title / contents: prefer manifest metadata, fall back to discovery
    title = extract_metadata_value(metadata, "Title")
    if title:
        # Remove shelfmark and date from title if present
        contents = re.sub(
            r",?\s*\[.*$", "", title
        ).strip()
        # Also remove trailing commas
        contents = contents.rstrip(",").strip()
        if contents:
            record["contents"] = contents
    if "contents" not in record and discovery_item.get("title"):
        record["contents"] = discovery_item["title"]
    # If we got a richer description from the detail page, prefer it
    if discovery_item.get("contents"):
        record["contents"] = discovery_item["contents"]

    # Date
    date_str = extract_metadata_value(metadata, "Date")
    if not date_str:
        date_str = discovery_item.get("date_text", "")
    if date_str:
        record["date_display"] = date_str
        start, end = parse_date(date_str)
        if start:
            record["date_start"] = start
        if end:
            record["date_end"] = end

    # Physical description / extent
    extent = extract_metadata_value(metadata, "Physical description")
    if not extent:
        extent = discovery_item.get("extent")
    if extent:
        record["folios"] = extent

    # Language (from discovery detail page)
    language = discovery_item.get("language")
    if language:
        record["language"] = language

    # Provenance (from discovery detail page)
    provenance = discovery_item.get("provenance")
    if provenance:
        record["provenance"] = provenance

    # Thumbnail
    record["thumbnail_url"] = extract_thumbnail_url(manifest_data)

    # Source URL: viewer page
    pid = discovery_item.get("pid", "")
    record["source_url"] = f"{VIEWER_BASE}/{pid}" if pid else manifest_url

    return record


# =============================================================================
# Database Operations
# =============================================================================


def ensure_repository(cursor) -> int:
    """Ensure NLW repository exists and return its ID."""
    cursor.execute(
        "SELECT id FROM repositories WHERE short_name = ?", ("NLW",)
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
            "National Library of Wales",
            "NLW",
            None,
            "https://www.library.wales/discover-learn/digital-exhibitions/manuscripts",
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


def import_nlw(
    db_path: Path,
    cache_path: Path,
    dry_run: bool = True,
    test_mode: bool = False,
    verbose: bool = False,
    limit: int = None,
    discover_only: bool = False,
    skip_discovery: bool = False,
):
    """Import NLW Peniarth manuscripts."""
    if verbose:
        logger.setLevel(logging.DEBUG)

    # Phase 1: Discovery
    items = None
    if not skip_discovery:
        items = load_discovery_cache(cache_path)

    if items is None and not skip_discovery:
        logger.info("No discovery cache found. Running crawl4ai discovery...")
        items = asyncio.run(
            discover_manuscripts(test_mode=test_mode, limit=limit)
        )
        save_discovery_cache(items, cache_path)
    elif items is not None:
        # Apply limits to cached data
        if test_mode:
            items = items[:5]
        elif limit:
            items = items[:limit]

    if items is None:
        logger.error("No discovery data available")
        return False

    # Filter to items with PIDs
    items_with_pids = [item for item in items if item.get("pid")]
    logger.info(
        f"Discovery: {len(items)} total items, "
        f"{len(items_with_pids)} with PIDs"
    )

    if discover_only:
        print(f"\nDiscovery complete. {len(items_with_pids)} manuscripts with PIDs.")
        print(f"Cache saved to: {cache_path}")
        return True

    # Phase 2: Fetch IIIF manifests and import
    if not db_path.exists():
        logger.error(f"Database not found: {db_path}")
        logger.info("Initialize the database first:")
        logger.info("  sqlite3 database/compilatio.db < database/schema.sql")
        return False

    records = []
    fetch_errors = 0

    for i, item in enumerate(items_with_pids):
        pid = item["pid"]
        manifest_url = f"{IIIF_BASE}/{pid}/manifest.json"

        logger.info(
            f"[{i+1}/{len(items_with_pids)}] "
            f"Fetching manifest for {item.get('shelfmark', pid)}"
        )

        manifest_data = fetch_json(manifest_url)
        if not manifest_data:
            fetch_errors += 1
            continue

        record = parse_manifest(manifest_data, manifest_url, item)
        if record:
            records.append(record)
            logger.debug(f"  -> {record['shelfmark']}")
        else:
            logger.warning(f"  -> Could not parse manifest for {pid}")
            fetch_errors += 1

        if i < len(items_with_pids) - 1:
            time.sleep(MANIFEST_DELAY)

        if (i + 1) % 25 == 0:
            logger.info(
                f"Progress: {i+1}/{len(items_with_pids)} manifests, "
                f"{len(records)} parsed"
            )

    logger.info(
        f"Fetched {len(items_with_pids)} manifests, "
        f"parsed {len(records)} records, {fetch_errors} errors"
    )

    # Phase 3: Database operations
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    repo_id = ensure_repository(cursor) if not dry_run else 1

    stats = {
        "discovery_total": len(items),
        "discovery_with_pids": len(items_with_pids),
        "manifests_fetched": len(items_with_pids),
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
                            thumbnail_url = ?, source_url = ?
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
                            folios, iiif_manifest_url, thumbnail_url, source_url
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        "NATIONAL LIBRARY OF WALES (PENIARTH) IMPORT SUMMARY"
    )
    print("=" * 70)
    print(f"\nDiscovery (archives.library.wales):")
    print(f"  Total items found:    {stats['discovery_total']}")
    print(f"  Items with PIDs:      {stats['discovery_with_pids']}")
    print(f"\nIIIF Manifest Fetch (damsssl.llgc.org.uk):")
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


def main():
    parser = argparse.ArgumentParser(
        description="Import NLW Peniarth manuscripts into Compilatio"
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually execute the import (default is dry-run)",
    )
    parser.add_argument(
        "--discover-only",
        action="store_true",
        help="Only run discovery phase (crawl4ai), save to cache",
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
        "--cache",
        type=Path,
        default=CACHE_PATH,
        help=f"Path to discovery cache (default: {CACHE_PATH})",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of manuscripts to process",
    )

    args = parser.parse_args()

    print("Compilatio National Library of Wales Import Tool")
    print("Source: NLW Archives — Peniarth Manuscripts Collection")
    print(f"DB:    {args.db}")
    print(f"Cache: {args.cache}")
    mode = "DISCOVER-ONLY" if args.discover_only else (
        "TEST" if args.test else (
            "EXECUTE" if args.execute else "DRY-RUN"
        )
    )
    print(f"Mode:  {mode}")
    if args.limit:
        print(f"Limit: {args.limit}")
    print()

    success = import_nlw(
        db_path=args.db,
        cache_path=args.cache,
        dry_run=not args.execute,
        test_mode=args.test,
        verbose=args.verbose,
        limit=args.limit,
        discover_only=args.discover_only,
        skip_discovery=args.skip_discovery,
    )
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
