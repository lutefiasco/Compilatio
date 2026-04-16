#!/usr/bin/env python3
"""
Fix broken BL thumbnail URLs by fetching correct sizes from IIIF manifests.

The BL's level0 image service only serves exact pixel dimensions listed in
the manifest. Thumbnail URLs scraped from catalogue HTML sometimes have
dimensions off by a pixel, causing 404s.

This script checks each BL thumbnail URL, and for any that 404, fetches
the manuscript's IIIF manifest and extracts the correct thumbnail URL.

Dry-run by default — use --execute to write.

Usage:
    python3 scripts/fix_bl_thumbnails.py                    # Dry run
    python3 scripts/fix_bl_thumbnails.py --execute          # Write fixes
    python3 scripts/fix_bl_thumbnails.py --broken-file f    # Use pre-scanned list
"""

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = PROJECT_ROOT / "database" / "compilatio.db"

REQUEST_DELAY = 0.5
REQUEST_TIMEOUT = 15
USER_AGENT = "Compilatio/1.0 (manuscript research; IIIF aggregator)"


def check_url(url: str) -> int:
    """Return HTTP status code for a URL."""
    try:
        resp = requests.head(url, timeout=REQUEST_TIMEOUT,
                             headers={"User-Agent": USER_AGENT},
                             allow_redirects=True)
        return resp.status_code
    except requests.RequestException:
        return 0


def get_thumbnail_from_manifest(manifest_url: str) -> str | None:
    """Fetch IIIF manifest and extract a working thumbnail URL."""
    try:
        resp = requests.get(manifest_url, timeout=REQUEST_TIMEOUT,
                            headers={"User-Agent": USER_AGENT})
        resp.raise_for_status()
        m = resp.json()
    except (requests.RequestException, ValueError):
        return None

    # IIIF v3 (BL uses this)
    thumb = m.get("thumbnail")
    if thumb and isinstance(thumb, list) and thumb:
        t = thumb[0]
        # Use the service to build a URL with a known-good size
        services = t.get("service", [])
        for svc in services:
            svc_id = svc.get("@id") or svc.get("id")
            sizes = svc.get("sizes", [])
            if svc_id and sizes:
                # Pick the ~200px wide size
                best = min(sizes, key=lambda s: abs(s["width"] - 200))
                return f"{svc_id}/full/{best['width']},{best['height']}/0/default.jpg"
        # Fallback: use the thumbnail id directly
        tid = t.get("id") or t.get("@id")
        if tid:
            return tid

    # IIIF v2 fallback
    seqs = m.get("sequences", [])
    if seqs:
        canvases = seqs[0].get("canvases", [])
        if canvases:
            thumb = canvases[0].get("thumbnail")
            if isinstance(thumb, dict):
                return thumb.get("@id")
            elif isinstance(thumb, str):
                return thumb

    return None


def run(execute: bool, broken_file: str | None):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    if broken_file:
        # Read pre-scanned broken URLs: "status|shelfmark|url" per line
        broken = []
        with open(broken_file) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split("|", 2)
                if len(parts) == 3:
                    shelfmark = parts[1]
                    row = conn.execute(
                        "SELECT id, shelfmark, thumbnail_url, iiif_manifest_url "
                        "FROM manuscripts WHERE shelfmark = ? AND repository_id = "
                        "(SELECT id FROM repositories WHERE short_name = 'BL')",
                        (shelfmark,)
                    ).fetchone()
                    if row:
                        broken.append(dict(row))
        print(f"Loaded {len(broken)} broken thumbnails from {broken_file}", file=sys.stderr)
    else:
        # Scan all BL thumbnails
        rows = conn.execute(
            "SELECT id, shelfmark, thumbnail_url, iiif_manifest_url "
            "FROM manuscripts WHERE repository_id = "
            "(SELECT id FROM repositories WHERE short_name = 'BL') "
            "AND thumbnail_url IS NOT NULL"
        ).fetchall()

        print(f"Checking {len(rows)} BL thumbnail URLs...", file=sys.stderr)
        broken = []
        for i, row in enumerate(rows):
            status = check_url(row["thumbnail_url"])
            if status != 200:
                broken.append(dict(row))
                print(f"  [{i+1}/{len(rows)}] {row['shelfmark']}: {status}", file=sys.stderr)
            if (i + 1) % 100 == 0:
                print(f"  ... checked {i+1}/{len(rows)}", file=sys.stderr)

        print(f"\n{len(broken)} broken thumbnails out of {len(rows)}", file=sys.stderr)

    if not broken:
        print("All thumbnails OK.", file=sys.stderr)
        conn.close()
        return

    # Fix broken thumbnails from manifests
    fixed = 0
    failed = 0
    for i, row in enumerate(broken):
        shelfmark = row["shelfmark"]
        manifest_url = row["iiif_manifest_url"]

        if not manifest_url:
            print(f"  {shelfmark}: no manifest URL, can't fix", file=sys.stderr)
            failed += 1
            continue

        print(f"  [{i+1}/{len(broken)}] {shelfmark}...", file=sys.stderr, end="")
        time.sleep(REQUEST_DELAY)

        new_url = get_thumbnail_from_manifest(manifest_url)
        if not new_url:
            print(" couldn't extract thumbnail from manifest", file=sys.stderr)
            failed += 1
            continue

        # Verify the new URL works
        status = check_url(new_url)
        if status != 200:
            print(f" new URL also broken ({status})", file=sys.stderr)
            failed += 1
            continue

        print(f" fixed", file=sys.stderr)
        if execute:
            conn.execute(
                "UPDATE manuscripts SET thumbnail_url = ? WHERE id = ?",
                (new_url, row["id"])
            )
        fixed += 1

    if execute:
        conn.commit()
    conn.close()

    mode = "DRY RUN" if not execute else "FIX"
    print(f"\n{'=' * 50}", file=sys.stderr)
    print(f"  {mode}: BL thumbnail repair", file=sys.stderr)
    print(f"{'=' * 50}", file=sys.stderr)
    print(f"  Broken:   {len(broken)}", file=sys.stderr)
    print(f"  {'Would fix' if not execute else 'Fixed'}:    {fixed}", file=sys.stderr)
    print(f"  Failed:   {failed}", file=sys.stderr)
    if not execute and fixed:
        print(f"\n  Run with --execute to apply fixes.", file=sys.stderr)
    print(f"{'=' * 50}\n", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(
        description="Fix broken BL thumbnail URLs from IIIF manifests"
    )
    parser.add_argument("--execute", action="store_true",
                        help="Actually update the database (default is dry-run)")
    parser.add_argument("--broken-file", default=None,
                        help="File with pre-scanned broken URLs (status|shelfmark|url per line)")
    args = parser.parse_args()

    run(execute=args.execute, broken_file=args.broken_file)


if __name__ == "__main__":
    main()
