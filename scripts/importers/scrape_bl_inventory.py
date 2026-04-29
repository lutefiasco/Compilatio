#!/usr/bin/env python3
"""
Scrape the complete BL digitized Western Manuscripts inventory via JSON API.

Paginates through searcharchives.bl.uk at 100 results/page, extracting
manuscript-level records (040- prefix IDs). Saves to data/bl_inventory.json.

Resumable: saves progress after each page. SIGINT-safe.

Usage:
    python3 scripts/importers/scrape_bl_inventory.py              # Run/resume
    python3 scripts/importers/scrape_bl_inventory.py --restart     # Start fresh
    python3 scripts/importers/scrape_bl_inventory.py --limit 3     # Test: 3 pages
    python3 scripts/importers/scrape_bl_inventory.py --retry-failed
    python3 scripts/importers/scrape_bl_inventory.py --check       # Compare BL count to local snapshot
"""

import argparse
import json
import re
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
STATE_FILE = DATA_DIR / "bl_inventory_state.json"
OUTPUT_FILE = DATA_DIR / "bl_inventory.json"
META_FILE = DATA_DIR / "bl_inventory_meta.json"  # last-scrape stats for --check

BASE_URL = "https://searcharchives.bl.uk/"
# All digitized Western Manuscripts
LIST_PARAMS = (
    "?f[collection_area_ssi][]=Western+Manuscripts"
    "&f[url_non_blank_si][]=Yes+(available)"
    "&format=json"
    "&per_page=100"
)

REQUEST_DELAY = 1.0
REQUEST_TIMEOUT = 30
USER_AGENT = "Compilatio/1.0 (manuscript research; IIIF aggregator)"

# Global for SIGINT handler
_state = None
_interrupted = False


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
        print(f"State saved to {STATE_FILE} (page {_state['last_completed_page']})", file=sys.stderr)
    sys.exit(1)


def strip_html(text: str | None) -> str | None:
    if text is None:
        return None
    cleaned = re.sub(r"<[^>]+>", "", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned if cleaned else None


def extract_field(attributes: dict, field_name: str) -> str | None:
    """Extract a field value from the nested attributes structure."""
    field = attributes.get(field_name)
    if field is None:
        return None
    try:
        return field["attributes"]["value"]
    except (KeyError, TypeError):
        return None


def infer_collection(shelfmark: str) -> str:
    """Infer collection name from BL shelfmark prefix.

    The search-results JSON does not include project_collections_ssim;
    that field is only on detail pages. For inventory-level filtering
    we derive collection from the shelfmark.
    """
    PREFIXES = [
        ("Cotton MS", "Cotton Manuscripts"),
        ("Cotton Ch", "Cotton Charters"),
        ("Cotton Roll", "Cotton Rolls"),
        ("Harley MS", "Harley Manuscripts"),
        ("Harley Ch", "Harley Charters"),
        ("Harley Roll", "Harley Rolls"),
        ("Royal MS", "Royal Manuscripts"),
        ("Arundel MS", "Arundel Manuscripts"),
        ("Arundel Or", "Arundel Collection"),
        ("Egerton MS", "Egerton Manuscripts"),
        ("Egerton Ch", "Egerton Charters"),
        ("Lansdowne MS", "Lansdowne Manuscripts"),
        ("Lansdowne Ch", "Lansdowne Charters"),
        ("Lansdowne Roll", "Lansdowne Rolls"),
        ("Stowe MS", "Stowe Manuscripts"),
        ("Stowe Ch", "Stowe Charters"),
        ("Burney MS", "Burney Manuscripts"),
        ("Yates Thompson MS", "Yates Thompson Manuscripts"),
        ("Add MS", "Additional Manuscripts"),
        ("Add Ch", "Additional Charters"),
        ("Add Roll", "Additional Rolls"),
        ("Sloane MS", "Sloane Manuscripts"),
        ("Kings MS", "King's Manuscripts"),
        ("Zweig MS", "Zweig Collection"),
        ("Ashley MS", "Ashley Collection"),
    ]
    for prefix, collection in PREFIXES:
        if shelfmark.startswith(prefix):
            return collection
    return "Unknown"


def transform_record(record: dict) -> dict | None:
    """Transform an API record into inventory format. Returns None if filtered out."""
    record_id = record.get("id", "")
    # Only manuscript-level records (040- prefix)
    if not record_id.startswith("040-"):
        return None

    attributes = record.get("attributes", {})
    shelfmark = extract_field(attributes, "reference_ssi")
    if not shelfmark:
        return None

    title = extract_field(attributes, "title_tsi")
    start_date = extract_field(attributes, "start_date_tsi")
    end_date = extract_field(attributes, "end_date_tsi")
    date_range = extract_field(attributes, "date_range_tsi")

    links = record.get("links", {})
    catalogue_url = links.get("self")

    return {
        "bl_record_id": record_id,
        "shelfmark": shelfmark,
        "title": strip_html(title),
        "collections": infer_collection(shelfmark),
        "start_date": start_date,
        "end_date": end_date,
        "date_range": date_range,
        "catalogue_url": catalogue_url,
    }


def fetch_json(url: str) -> dict | None:
    """Fetch JSON with one retry on failure."""
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


def build_page_url(page: int) -> str:
    return f"{BASE_URL}{LIST_PARAMS}&page={page}"


def scrape(limit: int | None = None):
    global _state

    existing = load_state()
    if existing:
        start_page = existing["last_completed_page"] + 1
        total_pages = existing["total_pages"]
        total_count = existing.get("total_count")
        records = existing["records"]
        failed_pages = existing.get("failed_pages", [])
        print(f"Resuming from page {start_page}/{total_pages} "
              f"({len(records)} records so far, {len(failed_pages)} failed)",
              file=sys.stderr)
    else:
        print("Fetching page 1 to determine total...", file=sys.stderr)
        first = fetch_json(build_page_url(1))
        if not first:
            print("Failed to fetch first page. Aborting.", file=sys.stderr)
            sys.exit(1)

        meta = first["meta"]["pages"]
        total_pages = meta["total_pages"]
        total_count = meta["total_count"]
        print(f"Total: {total_count} results across {total_pages} pages", file=sys.stderr)

        records = []
        for item in first.get("data", []):
            transformed = transform_record(item)
            if transformed:
                records.append(transformed)

        failed_pages = []
        _state = {
            "last_completed_page": 1,
            "total_pages": total_pages,
            "total_count": total_count,
            "records": records,
            "failed_pages": failed_pages,
        }
        save_state(_state)
        print(f"  Page 1: {len(records)} manuscript records", file=sys.stderr)
        start_page = 2

    max_page = total_pages
    if limit is not None:
        max_page = min(total_pages, start_page + limit - 1)

    for page_num in range(start_page, max_page + 1):
        if _interrupted:
            break

        time.sleep(REQUEST_DELAY)
        url = build_page_url(page_num)
        print(f"  Page {page_num}/{max_page}...", file=sys.stderr, end="")

        page_data = fetch_json(url)
        if page_data is None:
            print(" FAILED", file=sys.stderr)
            if page_num not in failed_pages:
                failed_pages.append(page_num)
            _state = {
                "last_completed_page": page_num,
                "total_pages": total_pages,
                "total_count": total_count,
                "records": records,
                "failed_pages": failed_pages,
            }
            save_state(_state)
            continue

        page_records = []
        for item in page_data.get("data", []):
            transformed = transform_record(item)
            if transformed:
                page_records.append(transformed)

        records.extend(page_records)
        print(f" {len(page_records)} records (total: {len(records)})", file=sys.stderr)

        _state = {
            "last_completed_page": page_num,
            "total_pages": total_pages,
            "total_count": total_count,
            "records": records,
            "failed_pages": failed_pages,
        }
        save_state(_state)

    actual_last = _state["last_completed_page"] if _state else 0
    if actual_last >= total_pages or (limit is not None and actual_last >= max_page):
        finalize(records, failed_pages, total_count=total_count)
    else:
        print(f"\nStopped at page {actual_last}/{total_pages}. Resume to continue.",
              file=sys.stderr)


def retry_failed():
    global _state

    existing = load_state()
    failed_file = DATA_DIR / "bl_inventory_failed_pages.json"

    if existing:
        failed_pages = existing.get("failed_pages", [])
        records = existing["records"]
        total_pages = existing["total_pages"]
        total_count = existing.get("total_count")
    elif failed_file.exists():
        with open(failed_file) as f:
            failed_pages = json.load(f)
        with open(OUTPUT_FILE) as f:
            records = json.load(f)
        total_pages = None
        total_count = None
    else:
        print("No state file or output file found. Run a full scrape first.", file=sys.stderr)
        sys.exit(1)

    if not failed_pages:
        print("No failed pages to retry.", file=sys.stderr)
        return

    print(f"Retrying {len(failed_pages)} failed pages: {failed_pages}", file=sys.stderr)

    still_failed = []
    for page_num in failed_pages:
        if _interrupted:
            break

        time.sleep(REQUEST_DELAY)
        url = build_page_url(page_num)
        print(f"  Page {page_num}...", file=sys.stderr, end="")

        page_data = fetch_json(url)
        if page_data is None:
            print(" STILL FAILED", file=sys.stderr)
            still_failed.append(page_num)
            continue

        page_records = []
        for item in page_data.get("data", []):
            transformed = transform_record(item)
            if transformed:
                page_records.append(transformed)

        records.extend(page_records)
        print(f" {len(page_records)} records", file=sys.stderr)

    if existing:
        _state = {
            "last_completed_page": existing["last_completed_page"],
            "total_pages": existing["total_pages"],
            "total_count": total_count,
            "records": records,
            "failed_pages": still_failed,
        }

    finalize(records, still_failed, total_count=total_count)


def finalize(records: list[dict], failed_pages: list[int], total_count: int | None = None):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)
    print(f"\nWrote {len(records)} records to {OUTPUT_FILE}", file=sys.stderr)

    if total_count is not None:
        meta = {
            "total_count": total_count,
            "manuscript_records": len(records),
            "scraped_at": datetime.now().isoformat(timespec="seconds"),
        }
        with open(META_FILE, "w") as f:
            json.dump(meta, f, indent=2)
        print(f"Wrote scrape metadata to {META_FILE}", file=sys.stderr)

    # Summary by collection
    collections: dict[str, int] = {}
    for r in records:
        coll = r.get("collections") or "Unknown"
        collections[coll] = collections.get(coll, 0) + 1
    print("\nInventory by collection:", file=sys.stderr)
    for coll in sorted(collections, key=collections.get, reverse=True):
        print(f"  {coll}: {collections[coll]}", file=sys.stderr)

    if failed_pages:
        failed_file = DATA_DIR / "bl_inventory_failed_pages.json"
        with open(failed_file, "w") as f:
            json.dump(sorted(failed_pages), f)
        print(f"\nWARNING: {len(failed_pages)} pages failed: {sorted(failed_pages)}",
              file=sys.stderr)
        print(f"  Re-run with --retry-failed to fetch them", file=sys.stderr)
    else:
        failed_file = DATA_DIR / "bl_inventory_failed_pages.json"
        failed_file.unlink(missing_ok=True)

    if STATE_FILE.exists():
        STATE_FILE.unlink()
        print(f"Removed state file", file=sys.stderr)


def check():
    """Compare BL's current total_count against the count from our last scrape.

    Single HTTP request, no side effects. The comparison is total_count vs
    total_count (apples to apples) — not against the filtered manuscript
    record count, which is always smaller because total_count includes
    item-level and other non-manuscript records.

    A nonzero delta means the BL has added or removed records matching the
    filter since our last scrape; some fraction of any growth will be new
    digitized manuscripts.
    """
    print("Fetching BL page 1 for current total...", file=sys.stderr)
    first = fetch_json(build_page_url(1))
    if not first:
        print("Failed to fetch BL inventory page 1.", file=sys.stderr)
        sys.exit(1)

    remote_total = first["meta"]["pages"]["total_count"]
    print(f"BL inventory: {remote_total} results "
          f"(filter: Western MSS, IIIF available)", file=sys.stderr)

    if not META_FILE.exists():
        print(f"Local baseline: none ({META_FILE.relative_to(PROJECT_ROOT)} missing)",
              file=sys.stderr)
        print("Run a full scrape to establish a baseline.", file=sys.stderr)
        return

    with open(META_FILE) as f:
        meta = json.load(f)
    last_total = meta["total_count"]
    last_ms = meta.get("manuscript_records")
    scraped_at = meta.get("scraped_at", "unknown")
    ms_str = f", {last_ms} were manuscripts" if last_ms is not None else ""
    print(f"Last scrape: {last_total} results{ms_str} "
          f"({scraped_at})", file=sys.stderr)

    delta = remote_total - last_total
    if delta > 0:
        print(f"Delta: +{delta} results since last scrape — full re-scrape may surface new MSS",
              file=sys.stderr)
    elif delta < 0:
        print(f"Delta: {delta} results (BL has fewer than last scrape — records may have been withdrawn)",
              file=sys.stderr)
    else:
        print("Delta: 0 — nothing new to scrape", file=sys.stderr)


def main():
    global _state

    parser = argparse.ArgumentParser(
        description="Scrape BL digitized Western Manuscripts inventory via JSON API"
    )
    parser.add_argument("--restart", action="store_true",
                        help="Start fresh, ignoring any saved state")
    parser.add_argument("--limit", type=int, default=None,
                        help="Limit to N pages (for testing)")
    parser.add_argument("--retry-failed", action="store_true",
                        help="Re-fetch only pages that failed in a previous run")
    parser.add_argument("--check", action="store_true",
                        help="Compare BL's current total to local snapshot, no scrape")
    args = parser.parse_args()

    signal.signal(signal.SIGINT, handle_sigint)

    if args.check:
        check()
        return

    if args.retry_failed:
        retry_failed()
        return

    if args.restart and STATE_FILE.exists():
        STATE_FILE.unlink()
        print("Removed existing state file", file=sys.stderr)

    scrape(limit=args.limit)


if __name__ == "__main__":
    main()
