#!/usr/bin/env python3
"""
Bodleian Library Manuscript Import Script for Compilatio.

Imports fully digitized medieval manuscripts from the Bodleian's
medieval-mss GitHub repository (TEI XML files).

Requirements:
- Clone https://github.com/bodleian/medieval-mss to data/bodleian-medieval-mss/
- Only imports manuscripts marked as "Fully Digitized" (not partial)
- Filters to manuscripts with IIIF manifests

Usage:
    python scripts/importers/bodleian.py                    # Dry-run mode
    python scripts/importers/bodleian.py --execute          # Actually import
    python scripts/importers/bodleian.py --verbose          # Detailed logging
    python scripts/importers/bodleian.py --limit 10         # Process first 10 only
"""

import argparse
import logging
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
DB_PATH = PROJECT_ROOT / "database" / "compilatio.db"
DATA_DIR = PROJECT_ROOT / "data" / "bodleian-medieval-mss" / "collections"

# TEI namespace
TEI_NS = {"tei": "http://www.tei-c.org/ns/1.0"}

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)


def extract_collection_from_shelfmark(shelfmark: str) -> str:
    """
    Extract collection name from a shelfmark.

    Examples:
        "MS. Bodl. 196" -> "Bodley"
        "MS. Junius 11" -> "Junius"
        "MS. Laud Misc. 108" -> "Laud Misc."
        "MS. Ashmole 1511" -> "Ashmole"
    """
    # Remove "MS. " prefix
    s = re.sub(r'^MS\.\s*', '', shelfmark)

    # Collection mappings
    patterns = [
        (r'^Bodl\.', 'Bodley'),
        (r'^Junius', 'Junius'),
        (r'^Ashmole', 'Ashmole'),
        (r'^Digby', 'Digby'),
        (r'^Douce', 'Douce'),
        (r'^Laud Misc\.', 'Laud Misc.'),
        (r'^Laud Lat\.', 'Laud Lat.'),
        (r'^Rawl\.?\s*([A-Z])', r'Rawlinson \1'),
        (r'^Rawl\.\s*poet', 'Rawlinson Poet.'),
        (r'^Rawl\.\s*liturg', 'Rawlinson Liturg.'),
        (r'^Add\.\s*([A-Z])', r'Additional \1'),
        (r'^Auct\.', 'Auct.'),
        (r'^Fairfax', 'Fairfax'),
        (r'^Hatton', 'Hatton'),
        (r'^Tanner', 'Tanner'),
        (r'^Eng\.\s*hist', 'Eng. hist.'),
        (r'^Eng\.\s*poet', 'Eng. poet.'),
        (r'^Eng\.\s*th', 'Eng. th.'),
        (r'^Lat\.\s*liturg', 'Lat. liturg.'),
        (r'^Lat\.\s*misc', 'Lat. misc.'),
        (r'^Lat\.\s*th', 'Lat. th.'),
        (r'^Gough', 'Gough'),
        (r'^Lyell', 'Lyell'),
        (r'^Barlow', 'Barlow'),
        (r'^Canon\.\s*Misc', 'Canon. Misc.'),
        (r'^Canon\.\s*Ital', 'Canon. Ital.'),
        (r'^D\'?Orville', "D'Orville"),
        (r'^Holkham', 'Holkham'),
        (r'^Selden', 'Selden'),
        (r'^e\s*Mus', 'e Musaeo'),
    ]

    for pattern, collection in patterns:
        if re.match(pattern, s, re.IGNORECASE):
            if r'\1' in collection:
                match = re.match(pattern, s, re.IGNORECASE)
                if match and match.groups():
                    return re.sub(pattern, collection, s[:match.end()], flags=re.IGNORECASE)
            return collection

    # Fallback: use first word
    parts = s.split()
    if parts:
        return parts[0].rstrip('.')

    return "Unknown"


def is_fully_digitized(ms_desc: ET.Element) -> bool:
    """
    Check if a manuscript is marked as fully digitized.

    Looks for:
    - <bibl type="digital-facsimile" subtype="full_digitisation">
    - Or text containing "Fully Digitized" / "Full digital facsimile"

    Returns False for:
    - Partial digitisation
    - No digitisation info
    """
    # Look in surrogates for bibl elements
    surrogates = ms_desc.find(".//tei:surrogates", TEI_NS)
    if surrogates is None:
        return False

    # Check for bibl with subtype
    for bibl in surrogates.findall(".//tei:bibl", TEI_NS):
        bibl_type = bibl.get("type", "")
        subtype = bibl.get("subtype", "")

        if "digital-facsimile" in bibl_type or "digital" in bibl_type:
            if "full" in subtype.lower():
                return True
            if "partial" in subtype.lower():
                return False

    # Check for ref elements with type
    for ref in surrogates.findall(".//tei:ref", TEI_NS):
        ref_type = ref.get("type", "")
        if "full" in ref_type.lower():
            return True
        if "partial" in ref_type.lower():
            return False

    # Fallback: check text content
    surrogates_text = ET.tostring(surrogates, encoding='unicode', method='text').lower()
    if "partial" in surrogates_text:
        return False
    if "full" in surrogates_text or "complete" in surrogates_text:
        return True

    # If we have a Digital Bodleian URL but no explicit partial marker, assume full
    for ref in surrogates.findall(".//tei:ref", TEI_NS):
        target = ref.get("target", "")
        if "digital.bodleian.ox.ac.uk" in target:
            return True

    return False


def extract_iiif_manifest(ms_desc: ET.Element) -> tuple[str, str]:
    """
    Extract IIIF manifest URL and Digital Bodleian URL from surrogates.

    Returns (iiif_manifest_url, source_url) tuple.
    """
    surrogates = ms_desc.find(".//tei:surrogates", TEI_NS)
    if surrogates is None:
        return None, None

    digital_bodleian_url = None

    for ref in surrogates.findall(".//tei:ref", TEI_NS):
        target = ref.get("target", "")
        if "digital.bodleian.ox.ac.uk" in target:
            digital_bodleian_url = target

            # Extract UUID and build IIIF manifest URL
            uuid_match = re.search(r'/objects/([a-f0-9-]+)/?', target)
            if uuid_match:
                uuid = uuid_match.group(1)
                iiif_manifest = f"https://iiif.bodleian.ox.ac.uk/iiif/manifest/{uuid}.json"
                return iiif_manifest, digital_bodleian_url

    return None, digital_bodleian_url


def extract_thumbnail_url(iiif_manifest_url: str) -> str:
    """Build thumbnail URL from IIIF manifest URL."""
    if not iiif_manifest_url:
        return None

    # Extract UUID from manifest URL
    uuid_match = re.search(r'/manifest/([a-f0-9-]+)\.json', iiif_manifest_url)
    if uuid_match:
        uuid = uuid_match.group(1)
        return f"https://iiif.bodleian.ox.ac.uk/iiif/image/{uuid}/full/200,/0/default.jpg"

    return None


def get_text_content(element: ET.Element) -> str:
    """Get all text content from an element, including nested elements."""
    if element is None:
        return ""
    texts = []
    if element.text:
        texts.append(element.text.strip())
    for child in element:
        if child.text:
            texts.append(child.text.strip())
        if child.tail:
            texts.append(child.tail.strip())
    return " ".join(t for t in texts if t)


def parse_tei_file(xml_path: Path) -> dict:
    """
    Parse a TEI XML file and extract manuscript metadata.

    Returns dict with metadata, or None if not suitable for import.
    """
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
    except ET.ParseError as e:
        logger.debug(f"XML parse error in {xml_path.name}: {e}")
        return None

    # Find main msDesc element
    ms_desc = root.find(".//tei:msDesc", TEI_NS)
    if ms_desc is None:
        return None

    # Check if fully digitized
    if not is_fully_digitized(ms_desc):
        return None

    # Extract IIIF manifest
    iiif_manifest, source_url = extract_iiif_manifest(ms_desc)
    if not iiif_manifest:
        return None

    # Extract basic metadata
    record = {
        "xml_path": str(xml_path),
        "iiif_manifest_url": iiif_manifest,
        "source_url": source_url,
        "thumbnail_url": extract_thumbnail_url(iiif_manifest),
    }

    # msIdentifier
    ms_id = ms_desc.find("tei:msIdentifier", TEI_NS)
    if ms_id is not None:
        shelfmark_el = ms_id.find("tei:idno[@type='shelfmark']", TEI_NS)
        if shelfmark_el is not None and shelfmark_el.text:
            record["shelfmark"] = shelfmark_el.text.strip()
            record["collection"] = extract_collection_from_shelfmark(record["shelfmark"])

    if "shelfmark" not in record:
        return None

    # msContents - summary or titles
    ms_contents = ms_desc.find("tei:msContents", TEI_NS)
    if ms_contents is not None:
        summary = ms_contents.find("tei:summary", TEI_NS)
        if summary is not None:
            record["contents"] = get_text_content(summary)
        else:
            titles = []
            for item in ms_contents.findall(".//tei:msItem/tei:title", TEI_NS):
                if item.text:
                    titles.append(item.text.strip())
            if titles:
                record["contents"] = "; ".join(titles[:5])

        # Language
        text_lang = ms_contents.find("tei:textLang", TEI_NS)
        if text_lang is not None:
            main_lang = text_lang.get("mainLang")
            if main_lang:
                record["language"] = main_lang

    # physDesc
    phys_desc = ms_desc.find("tei:physDesc", TEI_NS)
    if phys_desc is not None:
        support_desc = phys_desc.find(".//tei:supportDesc", TEI_NS)
        if support_desc is not None:
            extent = support_desc.find("tei:extent", TEI_NS)
            if extent is not None:
                record["folios"] = get_text_content(extent)

    # history/origin
    origin = ms_desc.find(".//tei:history/tei:origin", TEI_NS)
    if origin is not None:
        orig_date = origin.find("tei:origDate", TEI_NS)
        if orig_date is not None:
            date_text = orig_date.text.strip() if orig_date.text else ""
            not_before = orig_date.get("notBefore")
            not_after = orig_date.get("notAfter")

            if date_text:
                record["date_display"] = date_text
            elif not_before and not_after:
                record["date_display"] = f"{not_before}–{not_after}"
            elif not_before:
                record["date_display"] = f"after {not_before}"
            elif not_after:
                record["date_display"] = f"before {not_after}"

            # Extract years for sorting
            if not_before:
                try:
                    record["date_start"] = int(not_before[:4])
                except (ValueError, IndexError):
                    pass
            if not_after:
                try:
                    record["date_end"] = int(not_after[:4])
                except (ValueError, IndexError):
                    pass

        orig_place = origin.find("tei:origPlace", TEI_NS)
        if orig_place is not None:
            country = orig_place.find("tei:country", TEI_NS)
            if country is not None and country.text:
                record["provenance"] = country.text.strip()
            else:
                place_text = get_text_content(orig_place)
                if place_text:
                    record["provenance"] = place_text

    return record


def ensure_repository(cursor) -> int:
    """Ensure Bodleian repository exists and return its ID."""
    cursor.execute(
        "SELECT id FROM repositories WHERE short_name = ?",
        ("Bodleian",)
    )
    row = cursor.fetchone()
    if row:
        return row[0]

    cursor.execute("""
        INSERT INTO repositories (name, short_name, logo_url, catalogue_url)
        VALUES (?, ?, ?, ?)
    """, (
        "Bodleian Library, University of Oxford",
        "Bodleian",
        "https://digital.bodleian.ox.ac.uk/assets/images/logo.png",
        "https://medieval.bodleian.ox.ac.uk/"
    ))
    return cursor.lastrowid


def import_bodleian(
    db_path: Path,
    data_dir: Path,
    dry_run: bool = True,
    verbose: bool = False,
    limit: int = None
):
    """
    Import fully digitized Bodleian manuscripts from TEI XML files.
    """
    if verbose:
        logger.setLevel(logging.DEBUG)

    if not data_dir.exists():
        logger.error(f"Data directory not found: {data_dir}")
        logger.info("Clone the repository first:")
        logger.info("  git clone --depth 1 https://github.com/bodleian/medieval-mss data/bodleian-medieval-mss")
        return False

    if not db_path.exists():
        logger.error(f"Database not found: {db_path}")
        logger.info("Initialize the database first:")
        logger.info("  sqlite3 database/compilatio.db < database/schema.sql")
        return False

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Get or create repository
    repo_id = ensure_repository(cursor) if not dry_run else 1

    # Statistics
    stats = {
        "xml_files": 0,
        "fully_digitized": 0,
        "partial_or_none": 0,
        "inserted": 0,
        "updated": 0,
        "errors": 0,
    }

    results = {
        "inserted": [],
        "updated": [],
        "skipped_partial": [],
    }

    # Scan all XML files in collections
    xml_files = list(data_dir.glob("**/*.xml"))
    stats["xml_files"] = len(xml_files)

    if limit:
        xml_files = xml_files[:limit * 10]  # Process more to find enough fully digitized

    processed = 0
    for xml_path in xml_files:
        if limit and stats["fully_digitized"] >= limit:
            break

        record = parse_tei_file(xml_path)

        if record is None:
            stats["partial_or_none"] += 1
            if verbose:
                logger.debug(f"Skipped (not fully digitized or no IIIF): {xml_path.name}")
            continue

        stats["fully_digitized"] += 1
        processed += 1

        # Check for existing record
        cursor.execute(
            "SELECT id FROM manuscripts WHERE shelfmark = ? AND repository_id = ?",
            (record["shelfmark"], repo_id)
        )
        existing = cursor.fetchone()

        if dry_run:
            if existing:
                stats["updated"] += 1
                results["updated"].append({
                    "shelfmark": record["shelfmark"],
                    "collection": record.get("collection"),
                    "date": record.get("date_display"),
                })
            else:
                stats["inserted"] += 1
                results["inserted"].append({
                    "shelfmark": record["shelfmark"],
                    "collection": record.get("collection"),
                    "date": record.get("date_display"),
                })
        else:
            try:
                if existing:
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
                        existing[0]
                    ))
                    stats["updated"] += 1
                else:
                    cursor.execute("""
                        INSERT INTO manuscripts (
                            repository_id, shelfmark, collection, date_display,
                            date_start, date_end, contents, provenance, language,
                            folios, iiif_manifest_url, thumbnail_url, source_url
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        repo_id,
                        record["shelfmark"],
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
                    ))
                    stats["inserted"] += 1
            except Exception as e:
                stats["errors"] += 1
                logger.error(f"Error importing {record['shelfmark']}: {e}")

    if not dry_run:
        conn.commit()
    conn.close()

    # Print summary
    print_summary(stats, results, dry_run, verbose)
    return True


def print_summary(stats: dict, results: dict, dry_run: bool, verbose: bool):
    """Print import summary report."""
    print("\n" + "=" * 70)
    print(f"{'DRY RUN - ' if dry_run else ''}BODLEIAN IMPORT SUMMARY")
    print("=" * 70)

    print(f"\nXML Processing:")
    print(f"  Total XML files scanned:     {stats['xml_files']}")
    print(f"  Fully digitized (imported):  {stats['fully_digitized']}")
    print(f"  Partial/no digitization:     {stats['partial_or_none']}")

    print(f"\nDatabase Operations {'(would be)' if dry_run else ''}:")
    print(f"  {'Would insert' if dry_run else 'Inserted'}:  {stats['inserted']}")
    print(f"  {'Would update' if dry_run else 'Updated'}:   {stats['updated']}")
    print(f"  Errors:                      {stats['errors']}")

    if results["inserted"]:
        print("\n" + "-" * 70)
        print(f"RECORDS TO {'INSERT' if dry_run else 'INSERTED'} (sample):")
        print("-" * 70)
        for rec in results["inserted"][:10]:
            date = f" ({rec.get('date', '')})" if rec.get('date') else ""
            print(f"  {rec['shelfmark']} [{rec.get('collection', '?')}]{date}")
        if len(results["inserted"]) > 10:
            print(f"  ... and {len(results['inserted']) - 10} more")

    if results["updated"]:
        print("\n" + "-" * 70)
        print(f"RECORDS TO {'UPDATE' if dry_run else 'UPDATED'} (sample):")
        print("-" * 70)
        for rec in results["updated"][:5]:
            print(f"  {rec['shelfmark']} [{rec.get('collection', '?')}]")
        if len(results["updated"]) > 5:
            print(f"  ... and {len(results['updated']) - 5} more")

    if dry_run:
        print("\n" + "=" * 70)
        print("This was a DRY RUN. No changes were made to the database.")
        print("Run with --execute to apply changes.")
        print("=" * 70)


def main():
    parser = argparse.ArgumentParser(
        description="Import fully digitized Bodleian manuscripts from TEI XML"
    )
    parser.add_argument(
        '--execute',
        action='store_true',
        help='Actually execute the import (default is dry-run)'
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
        help=f'Path to database (default: {DB_PATH})'
    )
    parser.add_argument(
        '--data',
        type=Path,
        default=DATA_DIR,
        help=f'Path to TEI data (default: {DATA_DIR})'
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=None,
        help='Limit number of manuscripts to import'
    )

    args = parser.parse_args()

    print("Compilatio Bodleian Import Tool")
    print(f"Data: {args.data}")
    print(f"DB:   {args.db}")
    print(f"Mode: {'EXECUTE' if args.execute else 'DRY-RUN'}")
    print(f"Filter: Fully Digitized only")
    if args.limit:
        print(f"Limit: {args.limit}")

    success = import_bodleian(
        db_path=args.db,
        data_dir=args.data,
        dry_run=not args.execute,
        verbose=args.verbose,
        limit=args.limit,
    )

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
