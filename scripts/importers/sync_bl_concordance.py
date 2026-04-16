#!/usr/bin/env python3
"""
Register new Compilatio BL manuscripts in the Scriptorium concordance.

Queries compilatio.db for BL manuscripts, checks concordance.db for existing
rows, and either creates new concordance rows or links to existing ones by
normalized shelfmark.

SAFE TABLES (this script writes to):
  - concordance: creates new rows or sets compilatio_id on existing rows
  - concordance_variants: adds BL shelfmark variants
  - concordance_provenance: logs all actions

NEVER TOUCHED:
  - concordance_connundra_parts, concordance_builds
  - scholarly_xrefs, people, people_roles, concordance_institutions
  - concordance_authors, concordance_author_variants
  - concordance_works, concordance_works_links
  - dimev_works, dimev_witnesses, work_authority_xrefs

Append-only. Never deletes rows. Never nulls existing IDs.
Dry-run by default — use --execute to write.

Usage:
    python3 scripts/importers/sync_bl_concordance.py                # Dry run
    python3 scripts/importers/sync_bl_concordance.py --execute      # Write
    python3 scripts/importers/sync_bl_concordance.py --verbose      # Show matching logic
    python3 scripts/importers/sync_bl_concordance.py --audit-only   # Report concordance state
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
COMPILATIO_DB = PROJECT_ROOT / "database" / "compilatio.db"
CONCORDANCE_DB = Path.home() / "Geekery" / "Scriptorium" / "database" / "concordance.db"

# Add Scriptorium shared module to path for normalize()
SCRIPTORIUM_ROOT = Path.home() / "Geekery" / "Scriptorium"
sys.path.insert(0, str(SCRIPTORIUM_ROOT))

from shared.normalize import normalize


def log_provenance(conn, concordance_id, action, project, source_id=None, details=None):
    conn.execute("""
        INSERT INTO concordance_provenance (concordance_id, action, project, source_id, details)
        VALUES (?, ?, ?, ?, ?)
    """, (concordance_id, action, project, source_id,
          json.dumps(details) if details else None))


def audit_only():
    """Report current concordance state for BL manuscripts."""
    if not CONCORDANCE_DB.exists():
        print(f"Concordance DB not found: {CONCORDANCE_DB}", file=sys.stderr)
        sys.exit(1)
    if not COMPILATIO_DB.exists():
        print(f"Compilatio DB not found: {COMPILATIO_DB}", file=sys.stderr)
        sys.exit(1)

    conc = sqlite3.connect(CONCORDANCE_DB)
    conc.row_factory = sqlite3.Row
    comp = sqlite3.connect(COMPILATIO_DB)
    comp.row_factory = sqlite3.Row

    # BL manuscripts in Compilatio
    bl_mss = comp.execute(
        "SELECT id, shelfmark, collection FROM manuscripts "
        "WHERE repository_id = (SELECT id FROM repositories WHERE short_name = 'BL')"
    ).fetchall()

    # Concordance rows with compilatio_id set (BL repo)
    conc_with_compilatio = conc.execute(
        "SELECT id, shelfmark_canonical, compilatio_id FROM concordance "
        "WHERE compilatio_id IS NOT NULL AND repository = 'BL'"
    ).fetchall()

    compilatio_ids_in_conc = {row["compilatio_id"] for row in conc_with_compilatio}
    bl_ids = {row["id"] for row in bl_mss}

    linked = bl_ids & compilatio_ids_in_conc
    unlinked = bl_ids - compilatio_ids_in_conc

    print(f"\n{'=' * 60}")
    print(f"  BL Concordance Audit")
    print(f"{'=' * 60}")
    print(f"  BL manuscripts in Compilatio:     {len(bl_mss)}")
    print(f"  Concordance rows with BL link:    {len(conc_with_compilatio)}")
    print(f"  Linked (compilatio_id in conc):   {len(linked)}")
    print(f"  Unlinked (need sync):             {len(unlinked)}")

    # Breakdown by collection
    collections: dict[str, dict[str, int]] = {}
    for row in bl_mss:
        coll = row["collection"] or "Unknown"
        collections.setdefault(coll, {"total": 0, "linked": 0, "unlinked": 0})
        collections[coll]["total"] += 1
        if row["id"] in linked:
            collections[coll]["linked"] += 1
        else:
            collections[coll]["unlinked"] += 1

    print(f"\n  {'Collection':<20} {'Total':>6} {'Linked':>7} {'Unlinked':>9}")
    print(f"  {'-'*20} {'-'*6} {'-'*7} {'-'*9}")
    for coll in sorted(collections):
        c = collections[coll]
        print(f"  {coll:<20} {c['total']:>6} {c['linked']:>7} {c['unlinked']:>9}")

    print(f"{'=' * 60}\n")

    conc.close()
    comp.close()


def run(execute: bool, verbose: bool):
    if not CONCORDANCE_DB.exists():
        print(f"Concordance DB not found: {CONCORDANCE_DB}", file=sys.stderr)
        sys.exit(1)
    if not COMPILATIO_DB.exists():
        print(f"Compilatio DB not found: {COMPILATIO_DB}", file=sys.stderr)
        sys.exit(1)

    comp = sqlite3.connect(COMPILATIO_DB)
    comp.row_factory = sqlite3.Row
    conc = sqlite3.connect(CONCORDANCE_DB)
    conc.row_factory = sqlite3.Row

    # Get all BL manuscripts from Compilatio
    bl_mss = comp.execute(
        "SELECT id, shelfmark, collection FROM manuscripts "
        "WHERE repository_id = (SELECT id FROM repositories WHERE short_name = 'BL')"
    ).fetchall()
    print(f"Found {len(bl_mss)} BL manuscripts in Compilatio", file=sys.stderr)

    # Get existing concordance rows with compilatio_id set
    existing_compilatio_ids = set()
    for row in conc.execute("SELECT compilatio_id FROM concordance WHERE compilatio_id IS NOT NULL"):
        existing_compilatio_ids.add(row["compilatio_id"])

    # Build normalized shelfmark -> concordance id lookup
    norm_to_conc: dict[str, list[dict]] = {}
    for row in conc.execute("SELECT id, shelfmark_normalized, compilatio_id, repository FROM concordance"):
        norm = row["shelfmark_normalized"]
        norm_to_conc.setdefault(norm, []).append(dict(row))

    stats = {"created": 0, "linked": 0, "skipped": 0, "errors": 0}

    for ms in bl_mss:
        compilatio_id = ms["id"]
        shelfmark = ms["shelfmark"]
        collection = ms["collection"]

        # Already in concordance?
        if compilatio_id in existing_compilatio_ids:
            stats["skipped"] += 1
            if verbose:
                print(f"  SKIP {shelfmark}: already linked (compilatio_id={compilatio_id})",
                      file=sys.stderr)
            continue

        # Normalize the shelfmark
        result = normalize(shelfmark, repository='BL')
        normalized = result.normalized or shelfmark

        # Try to find existing concordance row by normalized shelfmark
        candidates = norm_to_conc.get(normalized, [])

        # Only match rows from same repository (BL) without a compilatio_id.
        # Arundel, Sloane, etc. exist at multiple institutions — never
        # cross-link a BL manuscript to a College of Arms concordance row.
        match = None
        for c in candidates:
            if c["repository"] == "BL" and c["compilatio_id"] is None:
                match = c
                break

        if match:
            # Link to existing row
            conc_id = match["id"]
            if verbose:
                print(f"  LINK {shelfmark} -> concordance #{conc_id} "
                      f"(matched by normalized: {normalized})", file=sys.stderr)
            if execute:
                try:
                    conc.execute(
                        "UPDATE concordance SET compilatio_id = ?, updated_at = CURRENT_TIMESTAMP "
                        "WHERE id = ?",
                        (compilatio_id, conc_id)
                    )
                    log_provenance(conc, conc_id, 'linked', 'compilatio_bl_sync',
                                   source_id=compilatio_id,
                                   details={'shelfmark': shelfmark, 'method': 'normalized_match'})
                except Exception as e:
                    print(f"  ERROR linking {shelfmark}: {e}", file=sys.stderr)
                    stats["errors"] += 1
                    continue
            stats["linked"] += 1
        else:
            # Create new concordance row
            if verbose:
                print(f"  CREATE {shelfmark} (normalized: {normalized})", file=sys.stderr)
            if execute:
                try:
                    cur = conc.execute("""
                        INSERT INTO concordance
                            (shelfmark_canonical, shelfmark_normalized, repository, collection,
                             compilatio_id, match_method, seeded_by)
                        VALUES (?, ?, 'BL', ?, ?, 'seed', 'compilatio_bl_sync')
                    """, (shelfmark, normalized, collection, compilatio_id))
                    conc_id = cur.lastrowid
                    log_provenance(conc, conc_id, 'created', 'compilatio_bl_sync',
                                   source_id=compilatio_id,
                                   details={'shelfmark': shelfmark})
                except sqlite3.IntegrityError:
                    # Duplicate canonical shelfmark — try linking instead
                    row = conc.execute(
                        "SELECT id, compilatio_id FROM concordance WHERE shelfmark_canonical = ?",
                        (shelfmark,)
                    ).fetchone()
                    if row and row["compilatio_id"] is None:
                        conc.execute(
                            "UPDATE concordance SET compilatio_id = ?, updated_at = CURRENT_TIMESTAMP "
                            "WHERE id = ?",
                            (compilatio_id, row["id"])
                        )
                        log_provenance(conc, row["id"], 'linked', 'compilatio_bl_sync',
                                       source_id=compilatio_id,
                                       details={'shelfmark': shelfmark,
                                                'method': 'canonical_collision_link'})
                        stats["linked"] += 1
                        if verbose:
                            print(f"    -> canonical collision, linked to #{row['id']}",
                                  file=sys.stderr)
                        continue
                    else:
                        if verbose:
                            print(f"    -> canonical collision, already has compilatio_id",
                                  file=sys.stderr)
                        stats["skipped"] += 1
                        continue
                except Exception as e:
                    print(f"  ERROR creating {shelfmark}: {e}", file=sys.stderr)
                    stats["errors"] += 1
                    continue
            stats["created"] += 1

        # Add variant form
        if execute and shelfmark != normalized:
            try:
                conc.execute("""
                    INSERT OR IGNORE INTO concordance_variants
                        (concordance_id, variant_form, source)
                    VALUES (?, ?, 'Compilatio_BL_2026')
                """, (conc_id, shelfmark))
            except Exception:
                pass  # Non-critical

    if execute:
        conc.commit()

    comp.close()
    conc.close()

    # Print summary
    mode = "DRY RUN" if not execute else "SYNC"
    print(f"\n{'=' * 60}", file=sys.stderr)
    print(f"  {mode}: BL concordance sync", file=sys.stderr)
    print(f"{'=' * 60}", file=sys.stderr)
    print(f"  {'Would create' if not execute else 'Created'} new rows:  {stats['created']}",
          file=sys.stderr)
    print(f"  {'Would link' if not execute else 'Linked'} existing:     {stats['linked']}",
          file=sys.stderr)
    print(f"  Skipped (already linked):          {stats['skipped']}", file=sys.stderr)
    print(f"  Errors:                            {stats['errors']}", file=sys.stderr)

    if not execute:
        print(f"\n  This was a DRY RUN. No changes were made.", file=sys.stderr)
        print(f"  Run with --execute to apply changes.", file=sys.stderr)
    print(f"{'=' * 60}\n", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(
        description="Sync BL manuscripts from Compilatio to Scriptorium concordance"
    )
    parser.add_argument("--execute", action="store_true",
                        help="Actually write to concordance (default is dry-run)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show matching logic for each manuscript")
    parser.add_argument("--audit-only", action="store_true",
                        help="Just report current concordance state, no writes")
    args = parser.parse_args()

    if args.audit_only:
        audit_only()
        return

    run(execute=args.execute, verbose=args.verbose)


if __name__ == "__main__":
    main()
