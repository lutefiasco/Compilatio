#!/usr/bin/env python3
"""
Import BL charters & rolls (Cotton / Harley) into compilatio.db.

Source is NOT the BL JSON API but the two "MSS on Rails" databases, which now
hold the charter/roll records natively with a `digitised_url` after the
2026-06-27 Scriptorium catalogue_url fix:

    ~/Geekery/CONR/database/cotton.db
    ~/Geekery/HONR/database/harley.db

Only rows whose `digitised_url` resolves to a real IIIF manifest
(iiif.bl.uk / bl.digirati.io) are ingestable; the rest are legacy non-IIIF
viewers ("digital images currently unavailable") and are skipped.

Native shelfmark forms are preserved verbatim ("Cotton Charter IV 5",
"Harley Roll Y 6") so the downstream `build_concordance.py --update` matches the
existing concordance rows (keyed by cotton_id / harley_id) and backfills
compilatio_id rather than minting duplicates.

Upserts by (repository_id, shelfmark). Dry-run by default — use --execute.
Does not touch the concordance. Full stop. (Run build_concordance.py --update
afterward, per CLAUDE.md.)

Usage:
    python3 scripts/importers/import_bl_charters_rolls.py            # Dry run
    python3 scripts/importers/import_bl_charters_rolls.py --execute
    python3 scripts/importers/import_bl_charters_rolls.py --no-manifest-fetch
    python3 scripts/importers/import_bl_charters_rolls.py -v
"""

import argparse
import json
import sqlite3
import sys
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
ADDITIONS_DIR = DATA_DIR / "bl_additions"
DB_PATH = PROJECT_ROOT / "database" / "compilatio.db"

# On-Rails source databases (absolute; these projects live beside Compilatio).
COTTON_DB = Path.home() / "Geekery" / "CONR" / "database" / "cotton.db"
HARLEY_DB = Path.home() / "Geekery" / "HONR" / "database" / "harley.db"


def extract_manifest_url(digitised_url: str | None) -> str | None:
    """Return the bare IIIF manifest URL, or None if this isn't an IIIF link.

    The on-Rails `digitised_url` is usually a BL universal-viewer wrapper that
    carries the real manifest in a `#?manifest=` fragment:

        https://iiif.bl.uk/uv/#?manifest=https://bl.digirati.io/iiif/ark:/.../vdc_*.0x*

    Bare digirati manifest URLs are passed through unchanged. Legacy viewers
    (FullDisplay.aspx, access.bl.uk) carry no manifest and return None.
    """
    if not digitised_url:
        return None

    parts = urlsplit(digitised_url)
    # The viewer puts the manifest after '#'; it may be "?manifest=..." or
    # "manifest=...". parse_qs ignores a leading '?' fine once stripped.
    for blob in (parts.fragment, parts.query):
        if not blob:
            continue
        blob = blob[1:] if blob.startswith("?") else blob
        params = parse_qs(blob)
        if "manifest" in params:
            return unquote(params["manifest"][0])

    # No wrapper: accept a bare digirati IIIF manifest, reject everything else.
    if "bl.digirati.io/iiif" in digitised_url:
        return digitised_url
    return None


def classify_collection(shelfmark: str) -> str | None:
    """Map a native charter/roll shelfmark to one of the four collections.

    "Cotton Charter IV 5" -> "Cotton Charters"
    "Cotton Roll XIV 8"   -> "Cotton Rolls"
    "Harley Charter 43 C 1" -> "Harley Charters"
    "Harley Roll Y 6"     -> "Harley Rolls"

    Anything that isn't a Cotton/Harley charter or roll returns None.
    """
    if not shelfmark:
        return None
    if shelfmark.startswith("Cotton "):
        institution = "Cotton"
    elif shelfmark.startswith("Harley "):
        institution = "Harley"
    else:
        return None

    if " Charter" in shelfmark:
        kind = "Charters"
    elif " Roll" in shelfmark:
        kind = "Rolls"
    else:
        return None

    return f"{institution} {kind}"


def fetch_manifest_meta(manifest_url: str) -> dict:
    """Fetch a IIIF manifest and return {image_count, thumbnail_url}.

    Best-effort: on any failure returns empty dict so import still proceeds.
    Supports IIIF Presentation 2 (sequences/canvases) and 3 (items).
    """
    try:
        req = urllib.request.Request(
            manifest_url,
            headers={"User-Agent": "Compilatio-importer/1.0",
                     "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:
        print(f"    manifest fetch failed ({e}): {manifest_url}", file=sys.stderr)
        return {}

    count = 0
    if "sequences" in data:  # Presentation 2
        for seq in data.get("sequences", []):
            count += len(seq.get("canvases", []))
    elif "items" in data:  # Presentation 3
        count = len(data.get("items", []))

    thumb = None
    t = data.get("thumbnail")
    if isinstance(t, dict):
        thumb = t.get("@id") or t.get("id")
    elif isinstance(t, list) and t:
        first = t[0]
        thumb = first.get("@id") or first.get("id") if isinstance(first, dict) else None
    elif isinstance(t, str):
        thumb = t

    return {"image_count": count or None, "thumbnail_url": thumb}


def load_source_rows() -> list[dict]:
    """Read ingestable charter/roll rows from the two on-Rails databases."""
    rows: list[dict] = []
    for db_path in (COTTON_DB, HARLEY_DB):
        if not db_path.exists():
            print(f"Source DB not found: {db_path}", file=sys.stderr)
            sys.exit(1)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        for r in conn.execute(
            """SELECT shelfmark_display, digitised_url, catalogue_url,
                      scope_and_content, languages, date_range, date_start, date_end
               FROM manuscripts
               WHERE shelfmark_display LIKE '%Charter%'
                  OR shelfmark_display LIKE '%Roll%'"""
        ):
            manifest = extract_manifest_url(r["digitised_url"])
            collection = classify_collection(r["shelfmark_display"])
            if not manifest or not collection:
                continue
            rows.append({
                "shelfmark": r["shelfmark_display"],
                "collection": collection,
                "iiif_manifest_url": manifest,
                "source_url": r["catalogue_url"],
                "contents": r["scope_and_content"],
                "language": r["languages"],
                "date_display": r["date_range"],
                "date_start": r["date_start"],
                "date_end": r["date_end"],
            })
        conn.close()
    return rows


def run(execute: bool, verbose: bool, fetch_manifests: bool):
    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}", file=sys.stderr)
        sys.exit(1)

    rows = load_source_rows()
    print(f"Loaded {len(rows)} ingestable charter/roll rows from on-Rails DBs",
          file=sys.stderr)
    if not rows:
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM repositories WHERE short_name = 'BL'")
    row = cursor.fetchone()
    if not row:
        print("BL repository missing from compilatio.db", file=sys.stderr)
        sys.exit(1)
    repo_id = row[0]

    stats: dict[str, dict[str, int]] = {}
    inserted: list[tuple[str, str]] = []

    for ms in rows:
        shelfmark = ms["shelfmark"]
        collection = ms["collection"]
        stats.setdefault(collection, {"new": 0, "updated": 0, "errors": 0})

        cursor.execute(
            "SELECT id FROM manuscripts WHERE repository_id = ? AND shelfmark = ?",
            (repo_id, shelfmark),
        )
        existing = cursor.fetchone()

        meta = {}
        if fetch_manifests and (execute or verbose):
            meta = fetch_manifest_meta(ms["iiif_manifest_url"])

        fields = (
            collection, ms["date_display"], ms["date_start"], ms["date_end"],
            ms["contents"], ms["language"], ms["iiif_manifest_url"],
            meta.get("thumbnail_url"), ms["source_url"], meta.get("image_count"),
        )

        if existing:
            if execute:
                try:
                    cursor.execute(
                        """UPDATE manuscripts SET
                               collection=?, date_display=?, date_start=?, date_end=?,
                               contents=?, language=?, iiif_manifest_url=?,
                               thumbnail_url=?, source_url=?, image_count=?
                           WHERE id=?""",
                        (*fields, existing[0]),
                    )
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
                    cursor.execute(
                        """INSERT INTO manuscripts (
                               repository_id, shelfmark, collection, date_display,
                               date_start, date_end, contents, language,
                               iiif_manifest_url, thumbnail_url, source_url, image_count
                           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (repo_id, shelfmark, *fields),
                    )
                    stats[collection]["new"] += 1
                    inserted.append((shelfmark, collection))
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

    mode = "DRY RUN" if not execute else "IMPORT"
    print(f"\n{'=' * 70}", file=sys.stderr)
    print(f"  {mode}: BL charters & rolls", file=sys.stderr)
    print(f"{'=' * 70}", file=sys.stderr)
    print(f"\n  {'Collection':<20} {'New':>6} {'Updated':>8} {'Errors':>7}",
          file=sys.stderr)
    print(f"  {'-'*20} {'-'*6} {'-'*8} {'-'*7}", file=sys.stderr)
    totals = {"new": 0, "updated": 0, "errors": 0}
    for coll in sorted(stats):
        s = stats[coll]
        print(f"  {coll:<20} {s['new']:>6} {s['updated']:>8} {s['errors']:>7}",
              file=sys.stderr)
        for k in totals:
            totals[k] += s[k]
    print(f"  {'-'*20} {'-'*6} {'-'*8} {'-'*7}", file=sys.stderr)
    print(f"  {'TOTAL':<20} {totals['new']:>6} {totals['updated']:>8} "
          f"{totals['errors']:>7}", file=sys.stderr)
    if not execute:
        print("\n  This was a DRY RUN. No changes were made.", file=sys.stderr)
        print("  Run with --execute to apply changes.", file=sys.stderr)
    print(f"{'=' * 70}\n", file=sys.stderr)

    if execute and inserted:
        log_path = write_additions_log(inserted)
        print(f"  Logged {len(inserted)} additions to "
              f"{log_path.relative_to(PROJECT_ROOT)}\n", file=sys.stderr)


def write_additions_log(inserted: list[tuple[str, str]]) -> Path:
    ADDITIONS_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    out_path = ADDITIONS_DIR / f"{now:%Y-%m-%d-%H%M}-charters-rolls.md"
    by_collection: dict[str, list[str]] = {}
    for shelfmark, collection in inserted:
        by_collection.setdefault(collection, []).append(shelfmark)
    lines = [
        f"# BL charters & rolls added {now:%Y-%m-%d %H:%M}",
        "",
        f"{len(inserted)} manuscripts imported into compilatio.db.",
        "",
    ]
    for collection in sorted(by_collection):
        shelfmarks = sorted(by_collection[collection])
        lines.append(f"## {collection} ({len(shelfmarks)})")
        for sm in shelfmarks:
            lines.append(f"- {sm}")
        lines.append("")
    out_path.write_text("\n".join(lines))
    return out_path


def main():
    parser = argparse.ArgumentParser(
        description="Import BL charters & rolls from on-Rails DBs into compilatio.db")
    parser.add_argument("--execute", action="store_true",
                        help="Actually write to database (default is dry-run)")
    parser.add_argument("--no-manifest-fetch", action="store_true",
                        help="Skip fetching manifests for image_count/thumbnail")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show each insert/update")
    args = parser.parse_args()
    run(execute=args.execute, verbose=args.verbose,
        fetch_manifests=not args.no_manifest_fetch)


if __name__ == "__main__":
    main()
