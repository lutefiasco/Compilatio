#!/usr/bin/env python3
"""
Filter BL inventory and fetch IIIF detail pages for new manuscripts.

Reads data/bl_inventory.json, applies collection/date/prefix filters, fetches
enriched detail pages from searcharchives.bl.uk JSON API, and outputs
data/bl_manuscripts.json ready for import.

Resumable: saves progress after each detail page. SIGINT-safe.

Usage:
    python3 scripts/importers/scrape_bl_details.py                    # Run with filters
    python3 scripts/importers/scrape_bl_details.py --collection cotton # One collection
    python3 scripts/importers/scrape_bl_details.py --refresh-existing  # Re-fetch known MSS
    python3 scripts/importers/scrape_bl_details.py --limit 5           # Test: 5 detail pages
    python3 scripts/importers/scrape_bl_details.py --verbose           # Show filter decisions
"""

import argparse
import json
import re
import signal
import sqlite3
import sys
import time
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = PROJECT_ROOT / "database" / "compilatio.db"
INVENTORY_FILE = DATA_DIR / "bl_inventory.json"
OUTPUT_FILE = DATA_DIR / "bl_manuscripts.json"
STATE_FILE = DATA_DIR / "bl_details_state.json"

DETAIL_URL_TEMPLATE = "https://searcharchives.bl.uk/catalog/{}?format=json"

REQUEST_DELAY = 1.0
REQUEST_TIMEOUT = 30
USER_AGENT = "Compilatio/1.0 (manuscript research; IIIF aggregator)"

# ============================================================
# FILTER CONFIGURATION
# ============================================================

# Collections to include unconditionally (all dates)
INCLUDE_COLLECTIONS = [
    "Cotton Manuscripts",
    "Harley Manuscripts",
    "Royal Manuscripts",
    "Arundel Manuscripts",
    "Arundel Collection",
    "Egerton Manuscripts",
    "Lansdowne Manuscripts",
    "Stowe Manuscripts",
    "Burney Manuscripts",
    "Yates Thompson Manuscripts",
    "King's Manuscripts",
]

# Collections to include with date filtering (end_date <= 1550)
DATE_FILTERED_COLLECTIONS = [
    "Additional Manuscripts",
    "Sloane Manuscripts",
]

# Collections to exclude entirely
EXCLUDE_COLLECTIONS = [
    "Zweig Collection",
    "Ashley Collection",
    # Charters and rolls are already excluded by EXCLUDE_PREFIXES,
    # but list them here too for completeness
    "Additional Charters",
    "Additional Rolls",
    "Cotton Charters",
    "Cotton Rolls",
    "Harley Charters",
    "Harley Rolls",
    "Egerton Charters",
    "Lansdowne Charters",
    "Lansdowne Rolls",
    "Stowe Charters",
]

# Shelfmark prefixes to exclude (charters, rolls, seals)
EXCLUDE_PREFIXES = [
    "Add Ch", "Add Roll",
    "Cotton Ch", "Cotton Roll",
    "Harley Ch", "Harley Roll",
    "Egerton Ch",
    "Lansdowne Ch", "Lansdowne Roll",
    "Stowe Ch",
    "Seal", "Cast",
]

# ============================================================
# GLOBALS
# ============================================================

_state = None
_interrupted = False
_verbose = False


def save_state(state: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def load_state() -> dict | None:
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return None


def handle_sigint(signum, frame):
    global _interrupted
    _interrupted = True
    print("\nInterrupted — saving state...", file=sys.stderr)
    if _state is not None:
        save_state(_state)
        n = len(_state.get("completed_ids", []))
        print(f"State saved ({n} detail pages completed)", file=sys.stderr)
    sys.exit(1)


def strip_html(text: str | None) -> str | None:
    if text is None:
        return None
    cleaned = re.sub(r"<[^>]+>", "", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned if cleaned else None


def extract_manifest_url(html_str: str | None) -> str | None:
    """Extract IIIF manifest URL from the url_tsi field.

    The field contains HTML like:
      <a href="https://iiif.bl.uk/uv/#?manifest=https://bl.digirati.io/iiif/ark:/81055/...">
    We want the manifest URL, not the viewer URL.
    """
    if not html_str:
        return None
    # Look for manifest= parameter in viewer URL
    match = re.search(r'manifest=(https://bl\.digirati\.io/iiif/[^"&\s]+)', html_str)
    if match:
        return match.group(1)
    # Fallback: any digirati IIIF URL
    match = re.search(r'(https://bl\.digirati\.io/iiif/[^"&\s<>]+)', html_str)
    if match:
        return match.group(1)
    return None


def extract_thumbnail_url(html_str: str | None) -> str | None:
    """Extract thumbnail image URL from the thumbnail_path_ss field.

    The field contains HTML like:
      <img ... src="https://bl.digirati.io/thumbs/ark:/81055/.../full/196,200/0/default.jpg">
    """
    if not html_str:
        return None
    match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', html_str)
    if match:
        return match.group(1)
    return None


def extract_field(attributes: dict, field_name: str) -> str | None:
    field = attributes.get(field_name)
    if field is None:
        return None
    try:
        return field["attributes"]["value"]
    except (KeyError, TypeError):
        return None


# ============================================================
# FILTERING
# ============================================================

def get_existing_bl_shelfmarks() -> set[str]:
    """Get set of BL shelfmarks already in compilatio.db."""
    if not DB_PATH.exists():
        return set()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute(
        "SELECT shelfmark FROM manuscripts WHERE repository_id = "
        "(SELECT id FROM repositories WHERE short_name = 'BL')"
    )
    shelfmarks = {row[0] for row in cursor.fetchall()}
    conn.close()
    return shelfmarks


def parse_end_date(record: dict) -> int | None:
    """Parse end_date from inventory record, return as int or None."""
    end = record.get("end_date")
    if end is None:
        return None
    try:
        return int(end)
    except (ValueError, TypeError):
        match = re.search(r'\d{4}', str(end))
        return int(match.group()) if match else None


def filter_record(record: dict, existing_shelfmarks: set[str],
                  collection_filter: str | None, refresh_existing: bool) -> tuple[bool, str]:
    """
    Apply filter pipeline to an inventory record.

    Returns (pass: bool, reason: str).
    """
    shelfmark = record.get("shelfmark", "")
    collections = record.get("collections", "")

    # Prefix exclusions
    for prefix in EXCLUDE_PREFIXES:
        if shelfmark.startswith(prefix):
            return False, f"excluded prefix: {prefix}"

    # Collection filter (CLI --collection)
    if collection_filter:
        target = collection_filter.lower()
        if target not in (collections or "").lower():
            return False, f"not in requested collection ({collection_filter})"

    # Collection include/exclude
    coll_included = False
    date_filter_needed = False

    if collections:
        # Check each collection tag (can be comma-separated or single)
        for excl in EXCLUDE_COLLECTIONS:
            if excl.lower() in collections.lower():
                return False, f"excluded collection: {excl}"

        for incl in INCLUDE_COLLECTIONS:
            if incl.lower() in collections.lower():
                coll_included = True
                break

        if not coll_included:
            for df in DATE_FILTERED_COLLECTIONS:
                if df.lower() in collections.lower():
                    coll_included = True
                    date_filter_needed = True
                    break

        if not coll_included:
            return False, f"collection not in include list: {collections}"
    else:
        # No collection info — include but flag
        return True, "no collection info (flagged for review)"

    # Date filter for mixed-period collections
    if date_filter_needed:
        end_date = parse_end_date(record)
        if end_date is not None and end_date > 1550:
            return False, f"post-medieval (end_date={end_date})"
        if end_date is None:
            # No date — include but note it
            pass

    # Existing manuscript check
    if not refresh_existing and shelfmark in existing_shelfmarks:
        return False, "already in compilatio.db"

    return True, "passed"


# ============================================================
# DETAIL PAGE FETCHING
# ============================================================

def fetch_json(url: str) -> dict | None:
    headers = {"User-Agent": USER_AGENT}
    for attempt in range(2):
        try:
            resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as e:
            if attempt == 0:
                print(f"  Retry after error: {e}", file=sys.stderr)
                time.sleep(2)
            else:
                print(f"  SKIP after error: {e}", file=sys.stderr)
                return None


def fetch_detail(record_id: str) -> dict | None:
    """Fetch and parse a detail page, returning enriched manuscript dict."""
    url = DETAIL_URL_TEMPLATE.format(record_id)
    data = fetch_json(url)
    if not data:
        return None

    # The detail response has data.attributes with all fields
    try:
        attributes = data["data"]["attributes"]
    except (KeyError, TypeError):
        return None

    shelfmark = extract_field(attributes, "reference_ssi")
    collections = extract_field(attributes, "project_collections_ssim")
    date_range = extract_field(attributes, "date_range_tsi")
    start_date = extract_field(attributes, "start_date_tsi")
    end_date = extract_field(attributes, "end_date_tsi")
    scope_and_content = strip_html(extract_field(attributes, "scope_and_content_tsi"))
    custodial_history = strip_html(extract_field(attributes, "custodial_history_tsi"))
    language = extract_field(attributes, "language_ssim")
    extent = strip_html(extract_field(attributes, "extent_tsi"))
    url_field = extract_field(attributes, "url_tsi")
    thumbnail_field = extract_field(attributes, "thumbnail_path_ss")
    ark_id = extract_field(attributes, "lark_tsi")

    links = data.get("data", {}).get("links", {})
    source_url = links.get("self")

    # Strip HTML from collections (contains <br /> separators between multiple collections)
    if collections:
        collections = re.sub(r'<br\s*/?>', ' / ', collections)
        collections = strip_html(collections)

    # Extract IIIF manifest URL from the url field (viewer HTML with manifest= param)
    iiif_manifest_url = extract_manifest_url(url_field)

    # Extract thumbnail URL (img src from thumbnail HTML)
    thumbnail_url = extract_thumbnail_url(thumbnail_field)

    # Parse dates to integers
    date_start = None
    date_end = None
    if start_date:
        match = re.search(r'\d{4}', str(start_date))
        if match:
            date_start = int(match.group())
    if end_date:
        match = re.search(r'\d{4}', str(end_date))
        if match:
            date_end = int(match.group())

    result = {
        "bl_record_id": record_id,
        "shelfmark": shelfmark,
        "collections": collections,
        "date_display": date_range,
        "date_start": date_start,
        "date_end": date_end,
        "contents": scope_and_content,
        "provenance": custodial_history,
        "language": language,
        "folios": extent,
        "iiif_manifest_url": iiif_manifest_url,
        "thumbnail_url": thumbnail_url,
        "ark_id": ark_id,
        "source_url": source_url,
    }

    return result


# ============================================================
# MAIN SCRAPE LOGIC
# ============================================================

def run(collection_filter: str | None, refresh_existing: bool,
        limit: int | None, verbose: bool):
    global _state, _verbose
    _verbose = verbose

    # Load inventory
    if not INVENTORY_FILE.exists():
        print(f"Inventory file not found: {INVENTORY_FILE}", file=sys.stderr)
        print("Run scrape_bl_inventory.py first.", file=sys.stderr)
        sys.exit(1)

    with open(INVENTORY_FILE) as f:
        inventory = json.load(f)
    print(f"Loaded {len(inventory)} inventory records", file=sys.stderr)

    # Load existing shelfmarks
    existing = get_existing_bl_shelfmarks()
    print(f"Found {len(existing)} existing BL manuscripts in compilatio.db", file=sys.stderr)

    # Apply filters
    to_fetch = []
    filter_stats: dict[str, int] = {}
    for record in inventory:
        passed, reason = filter_record(record, existing, collection_filter, refresh_existing)
        if passed:
            to_fetch.append(record)
        key = reason if not passed else "passed"
        filter_stats[key] = filter_stats.get(key, 0) + 1
        if verbose and not passed:
            print(f"  SKIP {record.get('shelfmark', '?')}: {reason}", file=sys.stderr)

    # Print filter summary
    print(f"\nFilter results:", file=sys.stderr)
    for reason in sorted(filter_stats, key=filter_stats.get, reverse=True):
        print(f"  {reason}: {filter_stats[reason]}", file=sys.stderr)
    print(f"\n{len(to_fetch)} manuscripts to fetch detail pages for", file=sys.stderr)

    if limit is not None:
        to_fetch = to_fetch[:limit]
        print(f"Limited to {len(to_fetch)} (--limit {limit})", file=sys.stderr)

    if not to_fetch:
        print("Nothing to fetch.", file=sys.stderr)
        return

    # Check for resume state
    existing_state = load_state()
    completed_ids: set[str] = set()
    manuscripts: list[dict] = []
    failed_ids: list[str] = []

    if existing_state:
        completed_ids = set(existing_state.get("completed_ids", []))
        manuscripts = existing_state.get("manuscripts", [])
        failed_ids = existing_state.get("failed_ids", [])
        print(f"Resuming: {len(completed_ids)} already fetched, "
              f"{len(failed_ids)} failed", file=sys.stderr)

    # Fetch detail pages
    remaining = [r for r in to_fetch if r["bl_record_id"] not in completed_ids]
    total = len(remaining)
    print(f"\nFetching {total} detail pages...\n", file=sys.stderr)

    for i, record in enumerate(remaining):
        if _interrupted:
            break

        record_id = record["bl_record_id"]
        shelfmark = record.get("shelfmark", "?")
        print(f"  [{i+1}/{total}] {shelfmark}...", file=sys.stderr, end="")

        time.sleep(REQUEST_DELAY)
        detail = fetch_detail(record_id)

        if detail is None:
            print(" FAILED", file=sys.stderr)
            if record_id not in failed_ids:
                failed_ids.append(record_id)
        elif not detail.get("iiif_manifest_url"):
            print(" no IIIF manifest, skipping", file=sys.stderr)
            completed_ids.add(record_id)
        else:
            manuscripts.append(detail)
            completed_ids.add(record_id)
            print(" OK", file=sys.stderr)

        _state = {
            "completed_ids": list(completed_ids),
            "manuscripts": manuscripts,
            "failed_ids": failed_ids,
        }
        save_state(_state)

    # Finalize
    finalize(manuscripts, failed_ids)


def finalize(manuscripts: list[dict], failed_ids: list[str]):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(manuscripts, f, indent=2, ensure_ascii=False)
    print(f"\nWrote {len(manuscripts)} manuscripts to {OUTPUT_FILE}", file=sys.stderr)

    # Summary by collection
    collections: dict[str, int] = {}
    for m in manuscripts:
        coll = m.get("collections") or "Unknown"
        collections[coll] = collections.get(coll, 0) + 1
    print("\nManuscripts by collection:", file=sys.stderr)
    for coll in sorted(collections, key=collections.get, reverse=True):
        print(f"  {coll}: {collections[coll]}", file=sys.stderr)

    if failed_ids:
        print(f"\nWARNING: {len(failed_ids)} detail pages failed", file=sys.stderr)
        for fid in failed_ids[:10]:
            print(f"  {fid}", file=sys.stderr)
        if len(failed_ids) > 10:
            print(f"  ... and {len(failed_ids) - 10} more", file=sys.stderr)

    if STATE_FILE.exists():
        STATE_FILE.unlink()
        print(f"Removed state file", file=sys.stderr)


def main():
    global _state

    parser = argparse.ArgumentParser(
        description="Filter BL inventory and fetch IIIF detail pages"
    )
    parser.add_argument("--collection", "-c", default=None,
                        help="Filter to one collection (e.g. cotton, harley, royal, arundel)")
    parser.add_argument("--refresh-existing", action="store_true",
                        help="Re-fetch manuscripts already in compilatio.db")
    parser.add_argument("--limit", type=int, default=None,
                        help="Limit to N detail page fetches (for testing)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show filter decisions for each record")
    args = parser.parse_args()

    signal.signal(signal.SIGINT, handle_sigint)

    run(collection_filter=args.collection,
        refresh_existing=args.refresh_existing,
        limit=args.limit,
        verbose=args.verbose)


if __name__ == "__main__":
    main()
