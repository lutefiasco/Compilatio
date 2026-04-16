#!/usr/bin/env python3
"""
Import BL manuscripts from data/bl_manuscripts.json into compilatio.db.

Upserts by (repository_id, shelfmark): inserts new rows, updates existing ones.
Dry-run by default — use --execute to write.

Does not touch the concordance. Full stop.

Usage:
    python3 scripts/importers/import_bl.py                        # Dry run (default)
    python3 scripts/importers/import_bl.py --execute              # Write to DB
    python3 scripts/importers/import_bl.py --execute --collection cotton
    python3 scripts/importers/import_bl.py --verbose
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = PROJECT_ROOT / "database" / "compilatio.db"
INPUT_FILE = DATA_DIR / "bl_manuscripts.json"

# Map BL collection names to short names for the collection column
# The collections field in bl_manuscripts.json comes from the BL API
# (project_collections_ssim), which uses these names. Map to short forms.
COLLECTION_MAP = {
    # BL API labels
    "Cotton Collection": "Cotton",
    "Harley Collection": "Harley",
    "Royal Collection": "Royal",
    "Arundel Collection": "Arundel",
    "Egerton Collection": "Egerton",
    "Lansdowne Collection": "Lansdowne",
    "Stowe Collection": "Stowe",
    "Burney Collection": "Burney",
    "Yates Thompson Collection": "Yates Thompson",
    "Additional Manuscripts": "Additional",
    "Sloane Collection": "Sloane",
    "King's Manuscripts": "King's",
    # Inventory-inferred labels (if detail page had no project_collections_ssim)
    "Cotton Manuscripts": "Cotton",
    "Harley Manuscripts": "Harley",
    "Royal Manuscripts": "Royal",
    "Arundel Manuscripts": "Arundel",
    "Egerton Manuscripts": "Egerton",
    "Lansdowne Manuscripts": "Lansdowne",
    "Stowe Manuscripts": "Stowe",
    "Burney Manuscripts": "Burney",
    "Yates Thompson Manuscripts": "Yates Thompson",
    "Sloane Manuscripts": "Sloane",
}


def map_collection(bl_collections: str | None) -> str:
    """Map BL collection string to short name."""
    if not bl_collections:
        return "Unknown"
    for bl_name, short in COLLECTION_MAP.items():
        if bl_name.lower() in bl_collections.lower():
            return short
    return bl_collections


def ensure_repository(cursor) -> int:
    """Ensure British Library repository exists and return its ID."""
    cursor.execute("SELECT id FROM repositories WHERE short_name = ?", ("BL",))
    row = cursor.fetchone()
    if row:
        return row[0]
    cursor.execute("""
        INSERT INTO repositories (name, short_name, logo_url, catalogue_url)
        VALUES (?, ?, ?, ?)
    """, ("British Library", "BL", None, "https://searcharchives.bl.uk/"))
    return cursor.lastrowid


def run(execute: bool, collection_filter: str | None, verbose: bool):
    if not INPUT_FILE.exists():
        print(f"Input file not found: {INPUT_FILE}", file=sys.stderr)
        print("Run scrape_bl_details.py first.", file=sys.stderr)
        sys.exit(1)

    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}", file=sys.stderr)
        sys.exit(1)

    with open(INPUT_FILE) as f:
        manuscripts = json.load(f)
    print(f"Loaded {len(manuscripts)} manuscripts from {INPUT_FILE}", file=sys.stderr)

    # Optional collection filter
    if collection_filter:
        target = collection_filter.lower()
        manuscripts = [m for m in manuscripts
                       if target in (m.get("collections") or "").lower()]
        print(f"Filtered to {len(manuscripts)} for collection '{collection_filter}'",
              file=sys.stderr)

    # Collapse folio-level records (", f 1r", ", ff 3r-6r") into one
    # top-level record per manuscript. The BL catalogues some miscellanies
    # item-by-item with no top-level record; we want one entry per MS.
    import re
    collapsed: dict[str, dict] = {}
    plain = []
    for ms in manuscripts:
        sm = ms.get("shelfmark", "")
        m = re.match(r'^(.+?),\s+ff?\s+', sm)
        if m:
            base = m.group(1)
            if base not in collapsed:
                # Use first fragment's data but with the base shelfmark
                entry = dict(ms)
                entry["shelfmark"] = base
                collapsed[base] = entry
                if verbose:
                    print(f"  COLLAPSE {sm} -> {base} (kept as representative)",
                          file=sys.stderr)
            else:
                if verbose:
                    print(f"  COLLAPSE {sm} -> {base} (skipped, already have)",
                          file=sys.stderr)
        else:
            plain.append(ms)

    if collapsed:
        print(f"Collapsed {sum(1 for ms in manuscripts if re.match(r'.+?,\\s+ff?\\s+', ms.get('shelfmark', '')))} "
              f"folio-level records into {len(collapsed)} manuscripts", file=sys.stderr)

    manuscripts = plain + list(collapsed.values())

    if not manuscripts:
        print("No manuscripts to import.", file=sys.stderr)
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    if execute:
        repo_id = ensure_repository(cursor)
    else:
        cursor.execute("SELECT id FROM repositories WHERE short_name = 'BL'")
        row = cursor.fetchone()
        repo_id = row[0] if row else 1

    stats: dict[str, dict[str, int]] = {}  # collection -> {new, updated, skipped, errors}

    for ms in manuscripts:
        shelfmark = ms.get("shelfmark")
        if not shelfmark:
            continue

        collection = map_collection(ms.get("collections"))
        iiif_url = ms.get("iiif_manifest_url")

        if not iiif_url:
            if verbose:
                print(f"  SKIP {shelfmark}: no IIIF manifest URL", file=sys.stderr)
            stats.setdefault(collection, {"new": 0, "updated": 0, "skipped": 0, "errors": 0})
            stats[collection]["skipped"] += 1
            continue

        # Check for existing
        cursor.execute(
            "SELECT id FROM manuscripts WHERE repository_id = ? AND shelfmark = ?",
            (repo_id, shelfmark)
        )
        existing = cursor.fetchone()

        stats.setdefault(collection, {"new": 0, "updated": 0, "skipped": 0, "errors": 0})

        if existing:
            if execute:
                try:
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
                        collection,
                        ms.get("date_display"),
                        ms.get("date_start"),
                        ms.get("date_end"),
                        ms.get("contents"),
                        ms.get("provenance"),
                        ms.get("language"),
                        ms.get("folios"),
                        iiif_url,
                        ms.get("thumbnail_url"),
                        ms.get("source_url"),
                        existing[0],
                    ))
                    stats[collection]["updated"] += 1
                    if verbose:
                        print(f"  UPDATE {shelfmark}", file=sys.stderr)
                except Exception as e:
                    print(f"  ERROR updating {shelfmark}: {e}", file=sys.stderr)
                    stats[collection]["errors"] += 1
            else:
                stats[collection]["updated"] += 1
                if verbose:
                    print(f"  WOULD UPDATE {shelfmark}", file=sys.stderr)
        else:
            if execute:
                try:
                    cursor.execute("""
                        INSERT INTO manuscripts (
                            repository_id, shelfmark, collection, date_display,
                            date_start, date_end, contents, provenance, language,
                            folios, iiif_manifest_url, thumbnail_url, source_url
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        repo_id,
                        shelfmark,
                        collection,
                        ms.get("date_display"),
                        ms.get("date_start"),
                        ms.get("date_end"),
                        ms.get("contents"),
                        ms.get("provenance"),
                        ms.get("language"),
                        ms.get("folios"),
                        iiif_url,
                        ms.get("thumbnail_url"),
                        ms.get("source_url"),
                    ))
                    stats[collection]["new"] += 1
                    if verbose:
                        print(f"  INSERT {shelfmark}", file=sys.stderr)
                except Exception as e:
                    print(f"  ERROR inserting {shelfmark}: {e}", file=sys.stderr)
                    stats[collection]["errors"] += 1
            else:
                stats[collection]["new"] += 1
                if verbose:
                    print(f"  WOULD INSERT {shelfmark}", file=sys.stderr)

    if execute:
        conn.commit()
    conn.close()

    # Print summary
    mode = "DRY RUN" if not execute else "IMPORT"
    print(f"\n{'=' * 70}", file=sys.stderr)
    print(f"  {mode}: British Library manuscripts", file=sys.stderr)
    print(f"{'=' * 70}", file=sys.stderr)
    print(f"\n  {'Collection':<20} {'New':>6} {'Updated':>8} {'Skipped':>8} {'Errors':>7}",
          file=sys.stderr)
    print(f"  {'-'*20} {'-'*6} {'-'*8} {'-'*8} {'-'*7}", file=sys.stderr)

    totals = {"new": 0, "updated": 0, "skipped": 0, "errors": 0}
    for coll in sorted(stats):
        s = stats[coll]
        print(f"  {coll:<20} {s['new']:>6} {s['updated']:>8} {s['skipped']:>8} {s['errors']:>7}",
              file=sys.stderr)
        for k in totals:
            totals[k] += s[k]

    print(f"  {'-'*20} {'-'*6} {'-'*8} {'-'*8} {'-'*7}", file=sys.stderr)
    print(f"  {'TOTAL':<20} {totals['new']:>6} {totals['updated']:>8} "
          f"{totals['skipped']:>8} {totals['errors']:>7}", file=sys.stderr)

    if not execute:
        print(f"\n  This was a DRY RUN. No changes were made.", file=sys.stderr)
        print(f"  Run with --execute to apply changes.", file=sys.stderr)
    print(f"{'=' * 70}\n", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(
        description="Import BL manuscripts from JSON into compilatio.db"
    )
    parser.add_argument("--execute", action="store_true",
                        help="Actually write to database (default is dry-run)")
    parser.add_argument("--collection", "-c", default=None,
                        help="Filter to one collection (e.g. cotton)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show each insert/update")
    args = parser.parse_args()

    run(execute=args.execute, collection_filter=args.collection, verbose=args.verbose)


if __name__ == "__main__":
    main()
