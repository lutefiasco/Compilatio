#!/usr/bin/env python3
"""
Import a curated set of BL codices into compilatio.db from the Scriptorium
shelfmark-driven harvest records.

Why this exists (2026-06-29): Compilatio's primary BL discovery path
(scrape_bl_inventory.py) is a *faceted crawl* of searcharchives.bl.uk filtered
to "Western Manuscripts + url_non_blank=available". That facet never surfaces
certain digitised codices — notably split/multi-part codices (manifests live at
the subpart level, not the parent record) and items in other ARK namespaces
(e.g. the Cotton Genesis, Otho B VI, whose manifest is `man_*` not `vdc_*`).

The CONR/RONR/HONR re-harvest (Scriptorium/tools/bl_harvest/) instead enumerates
the authoritative shelfmark census directly, so it captured IIIF manifests the
facet missed. Diffing that harvest against Compilatio surfaced 14 codices with a
manifest in hand but no Compilatio row (active-planning item 22). This importer
adds exactly those 14, sourcing shelfmark + manifest + metadata straight from the
harvest record JSON (the only complete source — the on-Rails DBs store the split
codices as parent rows with NULL digitised_url and are missing two outright).

Native BL shelfmark forms are preserved verbatim ("Cotton MS Otho C I/1") so a
later `build_concordance.py --update` can match/mint deterministically.

Upserts by (repository_id, shelfmark). Dry-run by default — use --execute.
Does not touch the concordance (run build_concordance.py --update afterward).

Usage:
    python3 scripts/importers/import_bl_codices.py             # Dry run
    python3 scripts/importers/import_bl_codices.py --execute
    python3 scripts/importers/import_bl_codices.py --no-manifest-fetch
    python3 scripts/importers/import_bl_codices.py -v
"""

import argparse
import json
import re
import sqlite3
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
ADDITIONS_DIR = DATA_DIR / "bl_additions"
DB_PATH = PROJECT_ROOT / "database" / "compilatio.db"

# Harvest record dirs (absolute; these projects live beside Compilatio).
HARVEST_DIRS = {
    "Cotton": Path.home() / "Geekery" / "CONR" / "data" / "bl_harvest" / "records",
    "Harley": Path.home() / "Geekery" / "HONR" / "data" / "bl_harvest" / "records",
    "Royal": Path.home() / "Geekery" / "RONR" / "data" / "bl_harvest" / "records",
}

# The curated 14 (active-planning item 22). Value = Compilatio collection.
TARGETS = {
    "Cotton MS Otho B VI": "Cotton",
    "Cotton MS Otho C I/1": "Cotton",
    "Cotton MS Otho C I/2": "Cotton",
    "Cotton MS Nero E I/1": "Cotton",
    "Cotton MS Nero E I/2": "Cotton",
    "Cotton MS Vitellius C XII/1": "Cotton",
    "Cotton MS Vitellius C XII/2": "Cotton",
    "Harley MS 1709": "Harley",
    "Harley MS 3941/2": "Harley",
    "Harley MS 4804/1": "Harley",
    "Harley MS 5471": "Harley",
    "Harley MS 7629": "Harley",
    "Royal Appendix MS 56": "Royal",
    "Royal Appendix MS 58": "Royal",
}


def field(attrs: dict, name: str):
    f = attrs.get(name)
    try:
        return f["attributes"]["value"]
    except (KeyError, TypeError):
        return None


def strip_html(text):
    if not text:
        return None
    cleaned = re.sub(r"<[^>]+>", "", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or None


def to_year(s):
    """'0400' -> 400; None/garbage -> None."""
    if not s:
        return None
    try:
        return int(str(s).lstrip("0") or "0")
    except ValueError:
        return None


def extract_manifest(url_tsi):
    if not url_tsi:
        return None
    m = re.search(r"manifest=([^\"&]+)", url_tsi)
    return m.group(1) if m else None


def fetch_manifest_meta(manifest_url: str) -> dict:
    """Fetch a IIIF manifest -> {image_count, thumbnail_url}. Best-effort."""
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


def load_target_rows() -> list[dict]:
    """Scan harvest records for the 14 targets; return one row each."""
    found: dict[str, dict] = {}
    for collection, d in HARVEST_DIRS.items():
        if not d.exists():
            print(f"Harvest dir not found: {d}", file=sys.stderr)
            continue
        for fp in d.glob("*.json"):
            try:
                obj = json.load(open(fp))
            except (json.JSONDecodeError, OSError):
                continue
            a = obj.get("data", {}).get("attributes", {})
            ref = field(a, "reference_ssi")
            if ref not in TARGETS or ref in found:
                continue
            manifest = extract_manifest(field(a, "url_tsi"))
            if not manifest:
                continue
            found[ref] = {
                "shelfmark": ref,
                "collection": TARGETS[ref],
                "iiif_manifest_url": manifest,
                "source_url": (obj.get("data", {}).get("links", {}) or {}).get("self")
                              or field(a, "url_tsi") and ref,
                "contents": strip_html(field(a, "title_tsi")),
                "language": strip_html(field(a, "language_ssim")
                                       or field(a, "languages_ssim")),
                "date_display": field(a, "date_range_tsi"),
                "date_start": to_year(field(a, "start_date_tsi")),
                "date_end": to_year(field(a, "end_date_tsi")),
            }
    return found


def run(execute: bool, verbose: bool, fetch_manifests: bool):
    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}", file=sys.stderr)
        sys.exit(1)

    found = load_target_rows()
    missing = sorted(set(TARGETS) - set(found))
    if missing:
        print(f"WARNING: {len(missing)} targets not found in harvest records:",
              file=sys.stderr)
        for m in missing:
            print(f"  - {m}", file=sys.stderr)
    print(f"Loaded {len(found)}/{len(TARGETS)} target codices from harvest records",
          file=sys.stderr)
    if not found:
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM repositories WHERE short_name = 'BL'")
    row = cursor.fetchone()
    if not row:
        print("BL repository missing from compilatio.db", file=sys.stderr)
        sys.exit(1)
    repo_id = row[0]

    stats = {"new": 0, "updated": 0, "errors": 0}
    inserted: list[tuple[str, str]] = []

    for shelfmark in sorted(found):
        ms = found[shelfmark]
        collection = ms["collection"]

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
                    stats["updated"] += 1
                    if verbose:
                        print(f"  UPDATE {shelfmark}", file=sys.stderr)
                except Exception as e:
                    print(f"  ERROR updating {shelfmark}: {e}", file=sys.stderr)
                    stats["errors"] += 1
            else:
                stats["updated"] += 1
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
                    stats["new"] += 1
                    inserted.append((shelfmark, collection))
                    if verbose:
                        print(f"  INSERT {shelfmark}", file=sys.stderr)
                except Exception as e:
                    print(f"  ERROR inserting {shelfmark}: {e}", file=sys.stderr)
                    stats["errors"] += 1
            else:
                stats["new"] += 1
                if verbose:
                    print(f"  WOULD INSERT {shelfmark}", file=sys.stderr)

    if execute:
        conn.commit()
    conn.close()

    mode = "DRY RUN" if not execute else "IMPORT"
    print(f"\n{'=' * 70}", file=sys.stderr)
    print(f"  {mode}: BL codices (active-planning item 22)", file=sys.stderr)
    print(f"{'=' * 70}", file=sys.stderr)
    print(f"  new={stats['new']}  updated={stats['updated']}  errors={stats['errors']}",
          file=sys.stderr)
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
    out_path = ADDITIONS_DIR / f"{now:%Y-%m-%d-%H%M}-codices.md"
    by_collection: dict[str, list[str]] = {}
    for shelfmark, collection in inserted:
        by_collection.setdefault(collection, []).append(shelfmark)
    lines = [
        f"# BL codices added {now:%Y-%m-%d %H:%M}",
        "",
        f"{len(inserted)} manuscripts imported into compilatio.db "
        "(from the Scriptorium shelfmark-driven harvest; active-planning item 22).",
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
        description="Import curated BL codices from harvest records into compilatio.db")
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
