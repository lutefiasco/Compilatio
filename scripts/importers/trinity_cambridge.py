#!/usr/bin/env python3
"""
Trinity College Cambridge (Wren Library) Manuscript Import Script for Compilatio.

Imports digitized medieval manuscripts from the James Catalogue of Western Manuscripts
(mss-cat.trin.cam.ac.uk). Uses Playwright to scrape search results with the
"Digitised Copies Only" filter, then fetches IIIF manifests for each manuscript.

Two-phase process with checkpoint resumability:
  Phase 1 (Discovery): Scrape search results to get all shelfmarks
  Phase 2 (Import): Fetch IIIF manifests, parse metadata, insert to database

Collection: ~850 digitized medieval manuscripts from Trinity College Cambridge
Source: James Catalogue online (M.R. James catalog, 1900-1904)
IIIF: Presentation API v2 manifests

Requirements:
- playwright

First-time setup:
    pip install playwright
    playwright install chromium

Usage:
    python scripts/importers/trinity_cambridge.py                  # Dry-run
    python scripts/importers/trinity_cambridge.py --execute        # Import
    python scripts/importers/trinity_cambridge.py --resume --execute # Resume interrupted
    python scripts/importers/trinity_cambridge.py --test           # First page only
    python scripts/importers/trinity_cambridge.py --verbose        # Detailed logging
    python scripts/importers/trinity_cambridge.py --discover-only  # Discovery phase only
    python scripts/importers/trinity_cambridge.py --skip-discovery # Use cached data

Note: Full import takes ~30 minutes. Use --resume to continue if interrupted.
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
from urllib.parse import urljoin

from playwright.async_api import async_playwright, Page, Browser

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
DB_PATH = PROJECT_ROOT / "database" / "compilatio.db"
CACHE_DIR = PROJECT_ROOT / "scripts" / "importers" / "cache"
DISCOVERY_CACHE = CACHE_DIR / "trinity_discovery.json"
PROGRESS_FILE = CACHE_DIR / "trinity_progress.json"

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================

TRINITY_BASE_URL = "https://mss-cat.trin.cam.ac.uk"
SEARCH_URL = f"{TRINITY_BASE_URL}/Search"
MANIFEST_BASE = f"{TRINITY_BASE_URL}/manuscripts"
VIEWER_BASE = f"{TRINITY_BASE_URL}/manuscripts/uv/view.php"

# Repository metadata
REPO_NAME = "Trinity College Cambridge"
REPO_SHORT = "TCC"
REPO_LOGO_URL = "https://www.trin.cam.ac.uk/assets/images/logo.png"
CATALOGUE_URL = TRINITY_BASE_URL

# Rate limiting
REQUEST_DELAY = 1.0  # seconds between manifest requests

# Shelfmark pattern: B.x.y, O.x.y, R.x.y, etc.
SHELFMARK_PATTERN = re.compile(r'\b([A-Z]\.\d+\.\d+)\b')

# =============================================================================
# Browser-based Scraper
# =============================================================================

class TrinityScraper:
    """Browser-based scraper for Trinity College Cambridge catalogue."""

    def __init__(self, headless: bool = True, delay: float = 0.5):
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

    async def discover_manuscripts(self, test_mode: bool = False) -> list[str]:
        """
        Discover all digitized manuscripts by scraping search results.

        Args:
            test_mode: If True, only process first page

        Returns:
            List of shelfmarks
        """
        logger.info("Loading Trinity search page...")
        await self.page.goto(SEARCH_URL, wait_until="networkidle")
        await asyncio.sleep(2)

        # Check the "Digitised Copies Only" filter
        logger.info("Applying 'Digitised Copies Only' filter...")
        digitised_label = self.page.locator("label:has-text('Digitised Copies Only')")

        if await digitised_label.count() > 0:
            checkbox = digitised_label.locator("input[type='checkbox']").or_(
                self.page.locator("#DigitisedOnly")
            )
            if await checkbox.count() > 0:
                await checkbox.first.check()
                await asyncio.sleep(1)
                logger.info("✓ Digitised filter applied")

        # Submit search
        search_button = self.page.locator("button:has-text('Search')").or_(
            self.page.locator("input[type='submit']")
        ).or_(
            self.page.locator("button[type='submit']")
        )

        if await search_button.count() > 0:
            logger.info("Submitting search...")
            await search_button.first.click()
            await asyncio.sleep(3)  # Wait for results

        all_shelfmarks = []
        page_num = 1

        while True:
            logger.info(f"Processing page {page_num}...")

            # Extract shelfmarks from current page
            results = self.page.locator("[class*='result']")
            result_count = await results.count()

            if result_count == 0:
                logger.warning("No results found on this page")
                break

            logger.info(f"Found {result_count} result elements")

            # Extract shelfmarks from all results on this page
            page_shelfmarks = set()
            for i in range(result_count):
                result = results.nth(i)
                text = await result.inner_text()

                # Find all shelfmark patterns in the text
                matches = SHELFMARK_PATTERN.findall(text)
                for shelfmark in matches:
                    if shelfmark not in page_shelfmarks:
                        page_shelfmarks.add(shelfmark)
                        logger.debug(f"  Found: {shelfmark}")

            all_shelfmarks.extend(sorted(page_shelfmarks))
            logger.info(f"Extracted {len(page_shelfmarks)} unique shelfmarks from page {page_num}")

            if test_mode:
                logger.info("Test mode: stopping after first page")
                break

            # Look for pagination - next page button
            next_button = self.page.locator("a:has-text('Next')").or_(
                self.page.locator("a[rel='next']")
            ).or_(
                self.page.locator("button:has-text('Next')")
            )

            if await next_button.count() == 0:
                logger.info("No 'Next' button found - this is the last page")
                break

            # Check if next button is disabled
            next_btn = next_button.first
            is_disabled = await next_btn.get_attribute("disabled")
            classes = await next_btn.get_attribute("class") or ""

            if is_disabled or "disabled" in classes:
                logger.info("'Next' button is disabled - this is the last page")
                break

            # Click next page
            logger.info("Clicking 'Next' page...")
            await next_btn.click()
            await asyncio.sleep(3)  # Wait for next page to load
            page_num += 1

        logger.info(f"Discovery complete: {len(all_shelfmarks)} manuscripts found")
        return all_shelfmarks


# =============================================================================
# Progress/Checkpoint Management
# =============================================================================

def load_progress(progress_path: Path) -> dict:
    """Load progress from checkpoint file."""
    if not progress_path.exists():
        return {
            "last_updated": None,
            "total_discovered": 0,
            "completed_shelfmarks": [],
            "failed_shelfmarks": [],
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


def mark_completed(progress: dict, shelfmark: str, progress_path: Path):
    """Mark a shelfmark as completed and save checkpoint."""
    if shelfmark not in progress["completed_shelfmarks"]:
        progress["completed_shelfmarks"].append(shelfmark)
    if shelfmark in progress["failed_shelfmarks"]:
        progress["failed_shelfmarks"].remove(shelfmark)
    save_progress(progress, progress_path)


def mark_failed(progress: dict, shelfmark: str, progress_path: Path):
    """Mark a shelfmark as failed and save checkpoint."""
    if shelfmark not in progress["failed_shelfmarks"]:
        progress["failed_shelfmarks"].append(shelfmark)
    save_progress(progress, progress_path)


# =============================================================================
# IIIF Manifest Fetching
# =============================================================================

async def fetch_manifest(shelfmark: str) -> Optional[dict]:
    """
    Fetch IIIF manifest for a shelfmark.

    Args:
        shelfmark: Manuscript shelfmark (e.g., "B.1.1")

    Returns:
        Parsed manifest dict or None on error
    """
    url = f"{MANIFEST_BASE}/{shelfmark}.json"

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()
            page = await context.new_page()

            response = await page.goto(url, timeout=30000)

            if response.status != 200:
                logger.warning(f"HTTP {response.status} for {shelfmark}")
                await browser.close()
                return None

            # Try to extract JSON from page
            try:
                # Check if page has <pre> tag with JSON
                pre_element = page.locator("pre")
                if await pre_element.count() > 0:
                    json_text = await pre_element.inner_text()
                else:
                    json_text = await page.content()

                manifest = json.loads(json_text)
                await browser.close()
                return manifest

            except json.JSONDecodeError:
                logger.error(f"Invalid JSON for {shelfmark}")
                await browser.close()
                return None

    except Exception as e:
        logger.error(f"Error fetching manifest for {shelfmark}: {e}")
        return None


# =============================================================================
# Manifest Parsing
# =============================================================================

def parse_manifest(manifest: dict, shelfmark: str) -> Optional[dict]:
    """
    Parse IIIF manifest into Compilatio database record.

    Args:
        manifest: IIIF manifest dict
        shelfmark: Manuscript shelfmark

    Returns:
        Database record dict or None on error
    """
    try:
        record = {
            "shelfmark": shelfmark,
            "iiif_manifest_url": f"{MANIFEST_BASE}/{shelfmark}.json",
            "source_url": f"{VIEWER_BASE}?n={shelfmark}",
        }

        # Extract label
        label = manifest.get("label", "")
        if label and label != shelfmark:
            record["contents"] = label

        # Get thumbnail from first canvas
        sequences = manifest.get("sequences", [])
        if sequences and sequences[0].get("canvases"):
            canvases = sequences[0]["canvases"]
            record["image_count"] = len(canvases)

            # Get thumbnail from first canvas
            first_canvas = canvases[0]
            if "thumbnail" in first_canvas:
                thumb = first_canvas["thumbnail"]
                if isinstance(thumb, dict):
                    record["thumbnail_url"] = thumb.get("@id", "")
                else:
                    record["thumbnail_url"] = thumb

        # Extract metadata fields
        metadata_fields = manifest.get("metadata", [])
        for field in metadata_fields:
            label = field.get("label", "").lower()
            value = field.get("value", "")

            if not value:
                continue

            # Map metadata fields to database columns
            if "title" in label:
                record["contents"] = value
            elif "language" in label:
                record["language"] = value
            elif "date" in label:
                record["date_display"] = value
                # Try to extract year range
                years = re.findall(r'\b(1?\d{3})\b', value)
                if years:
                    record["date_start"] = int(years[0])
                    if len(years) > 1:
                        record["date_end"] = int(years[-1])
                    else:
                        record["date_end"] = int(years[0])
            elif "extent" in label or "folio" in label:
                record["folios"] = value

        return record

    except Exception as e:
        logger.error(f"Error parsing manifest for {shelfmark}: {e}")
        return None


# =============================================================================
# Database Operations
# =============================================================================

def ensure_repository(cursor) -> int:
    """Create or get Trinity College Cambridge repository ID."""
    cursor.execute(
        "SELECT id FROM repositories WHERE short_name = ?",
        (REPO_SHORT,)
    )
    row = cursor.fetchone()
    if row:
        return row[0]

    logger.info(f"Creating repository record for {REPO_NAME}...")
    cursor.execute("""
        INSERT INTO repositories (name, short_name, logo_url, catalogue_url)
        VALUES (?, ?, ?, ?)
    """, (REPO_NAME, REPO_SHORT, REPO_LOGO_URL, CATALOGUE_URL))

    return cursor.lastrowid


def manuscript_exists(cursor, shelfmark: str, repo_id: int) -> Optional[int]:
    """Check if manuscript already exists in database."""
    cursor.execute(
        "SELECT id FROM manuscripts WHERE shelfmark = ? AND repository_id = ?",
        (shelfmark, repo_id)
    )
    row = cursor.fetchone()
    return row[0] if row else None


def insert_manuscript(cursor, record: dict, repo_id: int) -> int:
    """Insert manuscript record into database."""
    cursor.execute("""
        INSERT INTO manuscripts (
            repository_id, shelfmark, collection,
            iiif_manifest_url, thumbnail_url, source_url,
            date_display, date_start, date_end,
            contents, language, provenance, folios, image_count
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        repo_id,
        record.get("shelfmark"),
        record.get("collection"),
        record.get("iiif_manifest_url"),
        record.get("thumbnail_url"),
        record.get("source_url"),
        record.get("date_display"),
        record.get("date_start"),
        record.get("date_end"),
        record.get("contents"),
        record.get("language"),
        record.get("provenance"),
        record.get("folios"),
        record.get("image_count"),
    ))

    return cursor.lastrowid


# =============================================================================
# Main Import Function
# =============================================================================

async def import_trinity(
    db_path: Path,
    dry_run: bool = True,
    test_mode: bool = False,
    verbose: bool = False,
    discover_only: bool = False,
    skip_discovery: bool = False,
    resume: bool = False,
    limit: Optional[int] = None,
):
    """
    Main import function for Trinity College Cambridge manuscripts.

    Args:
        db_path: Path to SQLite database
        dry_run: If True, don't write to database
        test_mode: If True, only process first page
        verbose: Enable debug logging
        discover_only: Only run discovery phase, don't fetch manifests
        skip_discovery: Use cached discovery data
        resume: Resume from last checkpoint
        limit: Maximum number of manuscripts to process
    """
    if verbose:
        logger.setLevel(logging.DEBUG)

    # Ensure cache directory exists
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Load or initialize progress
    progress = load_progress(PROGRESS_FILE) if resume else {
        "last_updated": None,
        "total_discovered": 0,
        "completed_shelfmarks": [],
        "failed_shelfmarks": [],
        "phase": "discovery",
    }

    # Phase 1: Discovery
    shelfmarks = []

    if skip_discovery and DISCOVERY_CACHE.exists():
        logger.info(f"Loading cached discovery data from {DISCOVERY_CACHE}")
        with open(DISCOVERY_CACHE) as f:
            shelfmarks = json.load(f)
        logger.info(f"Loaded {len(shelfmarks)} shelfmarks from cache")

    else:
        logger.info("=" * 60)
        logger.info("PHASE 1: DISCOVERY")
        logger.info("=" * 60)

        async with TrinityScraper(headless=True) as scraper:
            shelfmarks = await scraper.discover_manuscripts(test_mode=test_mode)

        # Save to cache
        with open(DISCOVERY_CACHE, "w") as f:
            json.dump(shelfmarks, f, indent=2)
        logger.info(f"Cached discovery data to {DISCOVERY_CACHE}")

        # Update progress
        progress["total_discovered"] = len(shelfmarks)
        progress["phase"] = "import"
        save_progress(progress, PROGRESS_FILE)

        if discover_only:
            logger.info("Discovery-only mode: stopping here")
            return

    # Apply limit if specified
    if limit:
        shelfmarks = shelfmarks[:limit]
        logger.info(f"Limiting to {limit} manuscripts")

    # Phase 2: Manifest fetching and import
    logger.info("=" * 60)
    logger.info("PHASE 2: MANIFEST FETCHING AND IMPORT")
    logger.info("=" * 60)

    if dry_run:
        logger.info("DRY RUN MODE - No database changes will be made")
    else:
        logger.info("EXECUTE MODE - Database will be updated")

    if resume and progress["completed_shelfmarks"]:
        logger.info(f"RESUME MODE - Skipping {len(progress['completed_shelfmarks'])} already completed")
        logger.info(f"Failed in previous runs: {len(progress['failed_shelfmarks'])}")

    # Filter out already completed shelfmarks if resuming
    if resume:
        original_count = len(shelfmarks)
        shelfmarks = [s for s in shelfmarks if s not in progress["completed_shelfmarks"]]
        if len(shelfmarks) < original_count:
            logger.info(f"Resuming: {len(shelfmarks)} remaining of {original_count} total")

    # Connect to database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        repo_id = ensure_repository(cursor)
        logger.info(f"Repository ID: {repo_id}")

        imported = 0
        skipped = 0
        errors = 0

        # Calculate progress stats
        total_in_db = len(progress["completed_shelfmarks"])
        total_to_process = len(shelfmarks)

        for i, shelfmark in enumerate(shelfmarks, 1):
            overall_index = total_in_db + i
            total_overall = total_in_db + total_to_process

            logger.info(f"[{overall_index}/{total_overall}] Processing {shelfmark}...")

            # Check if already exists in database
            existing_id = manuscript_exists(cursor, shelfmark, repo_id)
            if existing_id:
                logger.info(f"  ✓ Already in database (ID {existing_id}), skipping")
                skipped += 1
                # Mark as completed in progress tracker
                if not dry_run:
                    mark_completed(progress, shelfmark, PROGRESS_FILE)
                continue

            # Fetch manifest
            await asyncio.sleep(REQUEST_DELAY)
            manifest = await fetch_manifest(shelfmark)

            if not manifest:
                logger.warning(f"  ✗ Failed to fetch manifest")
                errors += 1
                if not dry_run:
                    mark_failed(progress, shelfmark, PROGRESS_FILE)
                continue

            # Parse manifest
            record = parse_manifest(manifest, shelfmark)

            if not record:
                logger.warning(f"  ✗ Failed to parse manifest")
                errors += 1
                if not dry_run:
                    mark_failed(progress, shelfmark, PROGRESS_FILE)
                continue

            # Log what we found
            logger.info(f"  Title: {record.get('contents', 'N/A')}")
            logger.info(f"  Images: {record.get('image_count', 'N/A')}")

            if not dry_run:
                ms_id = insert_manuscript(cursor, record, repo_id)
                conn.commit()  # Commit after each insert for safety
                logger.info(f"  ✓ Inserted as ID {ms_id}")
                mark_completed(progress, shelfmark, PROGRESS_FILE)
                imported += 1
            else:
                logger.info(f"  ✓ Would insert (dry-run)")
                imported += 1

        # Summary
        logger.info("=" * 60)
        logger.info("IMPORT SUMMARY")
        logger.info("=" * 60)
        logger.info(f"This run:")
        logger.info(f"  Processed: {len(shelfmarks)}")
        logger.info(f"  Imported: {imported}")
        logger.info(f"  Skipped (already exists): {skipped}")
        logger.info(f"  Errors: {errors}")

        if not dry_run:
            logger.info(f"\nOverall progress:")
            logger.info(f"  Total completed: {len(progress['completed_shelfmarks'])}")
            logger.info(f"  Total discovered: {progress['total_discovered']}")
            logger.info(f"  Remaining: {progress['total_discovered'] - len(progress['completed_shelfmarks'])}")

            if progress['failed_shelfmarks']:
                logger.info(f"\nFailed shelfmarks ({len(progress['failed_shelfmarks'])}):")
                for failed in progress['failed_shelfmarks'][:10]:
                    logger.info(f"  - {failed}")
                if len(progress['failed_shelfmarks']) > 10:
                    logger.info(f"  ... and {len(progress['failed_shelfmarks']) - 10} more")

        if errors > 0 and not dry_run:
            logger.info(f"\nTo retry failed items, run with --resume flag")

    finally:
        conn.close()


# =============================================================================
# CLI Entry Point
# =============================================================================

def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Import Trinity College Cambridge manuscripts to Compilatio"
    )
    parser.add_argument(
        '--execute',
        action='store_true',
        help='Actually execute the import (default is dry-run)'
    )
    parser.add_argument(
        '--test',
        action='store_true',
        help='Test mode: only process first page of results'
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
        help='Path to database'
    )
    parser.add_argument(
        '--discover-only',
        action='store_true',
        help='Only run discovery phase, save to cache'
    )
    parser.add_argument(
        '--skip-discovery',
        action='store_true',
        help='Use cached discovery data, skip scraping'
    )
    parser.add_argument(
        '--resume',
        action='store_true',
        help='Resume from last checkpoint (skips completed manuscripts)'
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=None,
        help='Limit number of manuscripts to process'
    )

    args = parser.parse_args()

    try:
        asyncio.run(import_trinity(
            db_path=args.db,
            dry_run=not args.execute,
            test_mode=args.test,
            verbose=args.verbose,
            discover_only=args.discover_only,
            skip_discovery=args.skip_discovery,
            resume=args.resume,
            limit=args.limit,
        ))
    except KeyboardInterrupt:
        logger.info("\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Import failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
