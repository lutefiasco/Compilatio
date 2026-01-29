#!/usr/bin/env python3
"""
UCLA Library Medieval Manuscripts Import Script for Compilatio.

Imports digitized medieval manuscripts from UCLA Library Digital Collections.
Uses the Blacklight catalog JSON API for metadata and IIIF v3 manifests for
thumbnails and image counts.

No browser needed — pure HTTP/JSON.

Source:
    Catalog: https://digital.library.ucla.edu/catalog?f[member_of_collections_ssim][]=Medieval+and+Renaissance+Manuscripts
    IIIF: https://iiif.library.ucla.edu/

Usage:
    python scripts/importers/ucla.py                    # Dry-run mode
    python scripts/importers/ucla.py --execute          # Actually import
    python scripts/importers/ucla.py --test             # First 5 only
    python scripts/importers/ucla.py --verbose          # Detailed logging
"""

import argparse
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
from urllib.parse import quote

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
DB_PATH = PROJECT_ROOT / "database" / "compilatio.db"

# UCLA API endpoints
CATALOG_BASE = "https://digital.library.ucla.edu/catalog"
COLLECTION_QUERY = "f%5Bmember_of_collections_ssim%5D%5B%5D=Medieval+and+Renaissance+Manuscripts"

# Rate limiting
REQUEST_DELAY = 0.5  # seconds between requests

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)

# User-Agent header
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


def strip_html(text: str) -> str:
    """Remove HTML tags and normalize whitespace."""
    text = re.sub(r'<[^>]+>', ' ', str(text))
    text = re.sub(r'\s+', ' ', text).strip()
    return text


# =============================================================================
# Catalog API
# =============================================================================

def fetch_all_ark_ids() -> list[str]:
    """
    Fetch all manuscript ARK identifiers from the UCLA catalog JSON API.

    Uses Blacklight's JSON API with pagination (100 per page).
    """
    ark_ids = []
    page = 1

    while True:
        url = f"{CATALOG_BASE}.json?{COLLECTION_QUERY}&per_page=100&page={page}"
        logger.info(f"Fetching catalog page {page}")
        data = fetch_json(url)

        if not data:
            break

        items = data.get("data", [])
        if not items:
            break

        for item in items:
            ark = item.get("id")
            if ark:
                ark_ids.append(ark)

        # Check pagination
        meta = data.get("meta", {}).get("pages", {})
        total_pages = meta.get("total_pages", 1)
        if page >= total_pages:
            break

        page += 1
        time.sleep(REQUEST_DELAY)

    logger.info(f"Found {len(ark_ids)} manuscripts in collection")
    return ark_ids


def extract_field(data: dict, field_name: str) -> Optional[str]:
    """
    Extract a value from a catalog item JSON response.

    UCLA's Blacklight JSON API nests values as:
        data.attributes.{field}.attributes.value

    Values often contain HTML which is stripped.
    """
    attrs = data.get("data", data).get("attributes", {})
    field = attrs.get(field_name)

    if field is None:
        return None

    if isinstance(field, str):
        cleaned = strip_html(field)
        return cleaned if cleaned else None

    if isinstance(field, dict):
        value = field.get("attributes", {}).get("value", "")
        if value:
            cleaned = strip_html(str(value))
            return cleaned if cleaned else None

    return None


def fetch_catalog_item(ark_id: str) -> Optional[dict]:
    """Fetch a single catalog item's full metadata."""
    url = f"{CATALOG_BASE}/{ark_id}.json"
    return fetch_json(url)


# =============================================================================
# IIIF v3 Manifest Parsing
# =============================================================================

def extract_thumbnail_from_manifest(manifest: dict) -> Optional[str]:
    """
    Extract thumbnail URL from a IIIF v3 manifest.

    Tries manifest-level thumbnail, then first canvas thumbnail,
    then first canvas painting annotation body with image service.
    """
    # Try manifest-level thumbnail
    thumb = manifest.get("thumbnail")
    if thumb and isinstance(thumb, list) and thumb:
        thumb_id = thumb[0].get("id")
        if thumb_id:
            return thumb_id

    # Try first canvas
    items = manifest.get("items", [])
    if not items:
        return None

    first_canvas = items[0]

    # Canvas-level thumbnail
    canvas_thumb = first_canvas.get("thumbnail")
    if canvas_thumb and isinstance(canvas_thumb, list) and canvas_thumb:
        thumb_id = canvas_thumb[0].get("id")
        if thumb_id:
            return thumb_id

    # Fall back to first painting annotation body
    for page in first_canvas.get("items", []):
        for anno in page.get("items", []):
            body = anno.get("body", {})
            if isinstance(body, dict):
                # Check for IIIF image service to construct thumbnail
                service = body.get("service", [])
                if isinstance(service, list) and service:
                    service_id = service[0].get("id") or service[0].get("@id")
                    if service_id:
                        return f"{service_id}/full/!200,200/0/default.jpg"
                # Direct image URL — resize via IIIF
                body_id = body.get("id")
                if body_id and body.get("type") == "Image":
                    return re.sub(r'/full/[^/]+/', '/full/!200,200/', body_id)

    return None


def count_canvases(manifest: dict) -> int:
    """Count the number of canvases (pages) in a IIIF v3 manifest."""
    return len(manifest.get("items", []))


# =============================================================================
# Shelfmark & Collection Extraction
# =============================================================================

def extract_shelfmark_from_title(title: str) -> Optional[str]:
    """
    Extract the shelfmark prefix from a UCLA manuscript title.

    UCLA titles follow the pattern: "[Shelfmark]. [DESCRIPTIVE TITLE]"
    The shelfmark is the canonical scholarly identifier.

    Examples:
        "ROUSE MS 1. CARTULARY OF WINDSHEIM"    -> "Rouse MS 1"
        "Rouse MS. 66. BOOK OF HOURS."          -> "Rouse MS. 66"
        "Coll. 170. MS. 685. BOOK OF HOURS."    -> "Coll. 170. MS. 685"
        "BELT MS 37 [Book of hours]"            -> "Belt MS 37"
        "Belt D 19. Francesco Melzi"            -> "Belt D 19"
        "ROUSE leaf/XI/FRA/1. BURCHARD..."      -> "ROUSE leaf/XI/FRA/1"
    """
    if not title:
        return None

    # Ordered list of shelfmark patterns found in UCLA titles
    patterns = [
        # Rouse MS. Illum. 3. BREVIARY... or ROUSE ILLUM. 14...
        r'((?:ROUSE|Rouse)\s+(?:MS\.?\s*)?Illum\.?\s*\d+)',
        # ROUSE leaf/XI/FRA/1. BURCHARD...
        r'((?:ROUSE|Rouse)\s+leaf/\S+)',
        # Rouse MS. 66. BOOK OF HOURS... or ROUSE MS 1. CARTULARY...
        r'((?:ROUSE|Rouse)\s+MS\.?\s*\d+)',
        # BELT MS 37 [Book of hours...
        r'((?:BELT|Belt)\s+MS\s+\d+)',
        # Belt D 19. Francesco Melzi
        r'((?:BELT|Belt)\s+D\s+\d+)',
        # Belt Leaf Vitruvius Man
        r'((?:BELT|Belt)\s+Leaf\s+.+?)(?:\.|$)',
        # Coll. 170. MS. 685. BOOK OF HOURS...
        r'(Coll\.?\s*\d+\.?\s*MS\.?\s*\d+)',
        # Coll. 100. Box 178 f.2 Ovid's...
        r'(Coll\.?\s*\d+\.?\s*Box\s*\d+)',
    ]

    for pattern in patterns:
        m = re.match(pattern, title)
        if m:
            return m.group(1).strip().rstrip('.')

    return None


def extract_collection(shelfmark: str) -> str:
    """
    Map UCLA shelfmark to a collection name.

    Handles both title-derived shelfmarks and raw local identifiers.

    Examples:
        "Rouse MS 1"                -> "Rouse"
        "Rouse MS. Illum. 3"        -> "Rouse Illuminated"
        "ROUSE leaf/XI/FRA/1"       -> "Rouse Leaves"
        "Belt MS 37"                -> "Belt"
        "Coll. 170. MS. 685"        -> "Collection 170"
        "Coll. 100. Box 178"        -> "Collection 100"
        "170/ 685"                  -> "Collection 170"
        "***BELT A 1 P719hI leaf"   -> "Belt"
    """
    # Strip leading punctuation (UCLA uses *** prefix on some IDs)
    s = re.sub(r'^[^A-Za-z0-9]+', '', shelfmark).upper().strip()

    patterns = [
        (r'ROUSE\s+(?:MS\.?\s*)?ILLUM', "Rouse Illuminated"),
        (r'ROUSE\s+LEAF', "Rouse Leaves"),
        (r'ROUSE[_ ]+MS', "Rouse"),
        (r'BELT', "Belt"),
        (r'COLL\.?\s*170', "Collection 170"),
        (r'^170[/\s]', "Collection 170"),
        (r'COLLECTION\s+170', "Collection 170"),
        (r'COLL\.?\s*100', "Collection 100"),
        (r'^100[/\s]', "Collection 100"),
        (r'COLLECTION\s+100', "Collection 100"),
    ]

    for pattern, collection in patterns:
        if re.search(pattern, s):
            return collection

    return "Other"


# =============================================================================
# Date Parsing
# =============================================================================

ROMAN_NUMERALS = {
    'I': 1, 'II': 2, 'III': 3, 'IV': 4, 'V': 5,
    'VI': 6, 'VII': 7, 'VIII': 8, 'IX': 9, 'X': 10,
    'XI': 11, 'XII': 12, 'XIII': 13, 'XIV': 14, 'XV': 15,
    'XVI': 16, 'XVII': 17, 'XVIII': 18, 'XIX': 19, 'XX': 20,
}


def parse_roman_century(s: str) -> Optional[int]:
    """Parse a Roman numeral string and return century number (e.g. 'XV' -> 15)."""
    return ROMAN_NUMERALS.get(s.strip().upper())


def parse_date_range(date_str: str) -> tuple[Optional[int], Optional[int]]:
    """
    Parse UCLA date string into (start_year, end_year).

    UCLA uses idiosyncratic date notation mixing Roman numeral centuries
    with fractions, qualifiers, and Arabic numerals:

        "1421-1462"         -> (1421, 1462)
        "1476"              -> (1476, 1476)
        "XV2/2"             -> (1450, 1499)
        "s. XV 1/4"         -> (1400, 1424)
        "XIII 3/4"          -> (1250, 1274)
        "XV med"            -> (1425, 1474)
        "XVex"              -> (1475, 1499)
        "ca. 1520"          -> (1510, 1530)
        "before 1250"       -> (None, 1250)
        "XIII-XVII"         -> (1200, 1699)
        "1370-80"           -> (1370, 1380)
    """
    if not date_str:
        return None, None

    s = date_str.strip()
    # Remove parenthetical notes like "(ca. 1470)" or "(binder)"
    s = re.sub(r'\([^)]*\)', '', s).strip()
    # Remove leading "s. " (saeculum)
    s = re.sub(r'^s\.?\s*', '', s, flags=re.IGNORECASE)
    # Track and remove "ca."
    is_circa = bool(re.match(r'^ca\.?\s', s, re.IGNORECASE))
    s = re.sub(r'^ca\.?\s*', '', s, flags=re.IGNORECASE)
    # Normalize Unicode fractions and superscripts
    s = s.replace('\u00bc', '1/4').replace('\u00bd', '1/2').replace('\u00be', '3/4')
    s = s.replace('\u00b2', '2').replace('\u00b9', '1').replace('\u00b3', '3')

    # 1. Year range: "1421-1462"
    m = re.match(r'^(\d{4})\s*[-\u2013]\s*(\d{4})', s)
    if m:
        return int(m.group(1)), int(m.group(2))

    # 2. Abbreviated range: "1370-80"
    m = re.match(r'^(\d{4})\s*[-\u2013]\s*(\d{1,2})(?:\s|$)', s)
    if m:
        start = int(m.group(1))
        end_suffix = int(m.group(2))
        century_prefix = start // 100 * 100
        return start, century_prefix + end_suffix

    # 3. Single year: "1476", possibly with month/day
    m = re.match(r'^(\d{4})', s)
    if m:
        year = int(m.group(1))
        if is_circa:
            return year - 10, year + 10
        return year, year

    # 4. "before YYYY"
    m = re.match(r'^before\s+(\d{4})', s, re.IGNORECASE)
    if m:
        return None, int(m.group(1))

    # 5. "between YYYY-YYYY"
    m = re.match(r'^between\s+(\d{4})\s*[-\u2013]\s*(\d{4})', s, re.IGNORECASE)
    if m:
        return int(m.group(1)), int(m.group(2))

    # 6. Roman century range: "XIII-XVII"
    m = re.match(
        r'^(X{0,3}(?:IX|IV|V?I{0,3}))\s*[-\u2013]\s*(X{0,3}(?:IX|IV|V?I{0,3}))(?:\s|$)',
        s, re.IGNORECASE
    )
    if m:
        c1 = parse_roman_century(m.group(1))
        c2 = parse_roman_century(m.group(2))
        if c1 and c2:
            return (c1 - 1) * 100, c2 * 100 - 1

    # 7. Roman century with fraction: "XV 1/4", "XV2/2", "XIII 3/4"
    m = re.match(
        r'^(X{0,3}(?:IX|IV|V?I{0,3}))\s*(\d)/(\d)',
        s, re.IGNORECASE
    )
    if m:
        century = parse_roman_century(m.group(1))
        if century:
            base = (century - 1) * 100
            num, denom = int(m.group(2)), int(m.group(3))
            if denom == 2:
                if num == 1:
                    return base, base + 49
                else:
                    return base + 50, base + 99
            elif denom == 4:
                start_off = (num - 1) * 25
                end_off = min(num * 25 - 1, 99)
                return base + start_off, base + end_off
            elif denom == 3:
                start_off = (num - 1) * 33
                end_off = min(num * 33 - 1, 99)
                return base + start_off, base + end_off

    # 8. Roman century with qualifier: "XV med", "XVex", "XV in", "XIII ex-in"
    m = re.match(
        r'^(X{0,3}(?:IX|IV|V?I{0,3}))\s*(in|med|ex)',
        s, re.IGNORECASE
    )
    if m:
        century = parse_roman_century(m.group(1))
        if century:
            base = (century - 1) * 100
            qual = m.group(2).lower()
            if qual == 'in':
                return base, base + 25
            elif qual == 'med':
                return base + 25, base + 74
            elif qual == 'ex':
                return base + 75, base + 99

    # 9. Roman century with bare half digit: "XIV 2" (second half)
    m = re.match(
        r'^(X{0,3}(?:IX|IV|V?I{0,3}))\s+(\d)(?:\s|$)',
        s, re.IGNORECASE
    )
    if m:
        century = parse_roman_century(m.group(1))
        num = int(m.group(2))
        if century and num in (1, 2):
            base = (century - 1) * 100
            if num == 1:
                return base, base + 49
            else:
                return base + 50, base + 99

    # 10. Bare Roman numeral: "XIII"
    m = re.match(r'^(X{0,3}(?:IX|IV|V?I{0,3}))(?:\s|$)', s, re.IGNORECASE)
    if m:
        century = parse_roman_century(m.group(1))
        if century:
            return (century - 1) * 100, century * 100 - 1

    # 11. Ordinal century: "17th Century"
    m = re.search(r'(\d{1,2})(?:st|nd|rd|th)\s*[Cc]entury', s)
    if m:
        century = int(m.group(1))
        return (century - 1) * 100, century * 100 - 1

    return None, None


# =============================================================================
# Record Building
# =============================================================================

def build_record(
    catalog_data: dict,
    manifest_data: Optional[dict],
    ark_id: str,
) -> Optional[dict]:
    """
    Build a Compilatio manuscript record from catalog and manifest data.

    Returns dict with database fields, or None if not importable.
    """
    # Title is the best source for shelfmarks at UCLA
    title = (extract_field(catalog_data, "title_tesim")
             or extract_field(catalog_data, "title") or "")

    # Try title-based shelfmark extraction first (scholarly format)
    shelfmark = extract_shelfmark_from_title(title)
    if not shelfmark:
        # Fall back to local identifier
        shelfmark = extract_field(catalog_data, "local_identifier_ssim")
    if not shelfmark:
        # Last resort: use full title
        shelfmark = title if title else ark_id

    record = {
        "shelfmark": shelfmark,
        "collection": extract_collection(shelfmark),
    }

    # IIIF manifest URL
    manifest_url = extract_field(catalog_data, "iiif_manifest_url_ssi")
    if not manifest_url:
        encoded_ark = quote(ark_id, safe='')
        manifest_url = f"https://iiif.library.ucla.edu/{encoded_ark}/manifest"
    record["iiif_manifest_url"] = manifest_url

    # Title / contents
    if title:
        record["contents"] = title[:1000]

    # Date
    date_display = extract_field(catalog_data, "date_created_tesim")
    if date_display:
        record["date_display"] = date_display
        start, end = parse_date_range(date_display)
        if start:
            record["date_start"] = start
        if end:
            record["date_end"] = end

    # Language
    language = extract_field(catalog_data, "human_readable_language_tesim")
    if language:
        record["language"] = language

    # Provenance — combine place of origin + provenance
    provenance = extract_field(catalog_data, "provenance_tesim")
    origin = extract_field(catalog_data, "place_of_origin_tesim")
    if provenance and origin:
        record["provenance"] = f"{origin}. {provenance}"
    elif provenance:
        record["provenance"] = provenance
    elif origin:
        record["provenance"] = origin

    # Physical description (medium field has material and dimensions)
    medium = extract_field(catalog_data, "medium_tesim")
    extent = extract_field(catalog_data, "extent_tesim")
    if medium:
        record["folios"] = medium
    elif extent:
        record["folios"] = extent

    # Source URL (catalog page)
    record["source_url"] = f"{CATALOG_BASE}/{ark_id}"

    # Thumbnail and image count from manifest
    if manifest_data:
        record["thumbnail_url"] = extract_thumbnail_from_manifest(manifest_data)
        record["image_count"] = count_canvases(manifest_data)

    return record


# =============================================================================
# Database Operations
# =============================================================================

def ensure_repository(cursor) -> int:
    """Ensure UCLA Library repository exists and return its ID."""
    cursor.execute(
        "SELECT id FROM repositories WHERE short_name = ?",
        ("UCLA",)
    )
    row = cursor.fetchone()
    if row:
        return row[0]

    cursor.execute("""
        INSERT INTO repositories (name, short_name, logo_url, catalogue_url)
        VALUES (?, ?, ?, ?)
    """, (
        "UCLA Library",
        "UCLA",
        "",
        "https://digital.library.ucla.edu/catalog?"
        "f%5Bmember_of_collections_ssim%5D%5B%5D="
        "Medieval+and+Renaissance+Manuscripts"
    ))
    return cursor.lastrowid


def manuscript_exists(cursor, shelfmark: str, repo_id: int) -> Optional[int]:
    """Check if manuscript exists. Returns ID if found, None otherwise."""
    cursor.execute(
        "SELECT id FROM manuscripts WHERE shelfmark = ? AND repository_id = ?",
        (shelfmark, repo_id)
    )
    row = cursor.fetchone()
    return row[0] if row else None


# =============================================================================
# Main Import Logic
# =============================================================================

def import_ucla(
    db_path: Path,
    dry_run: bool = True,
    test_mode: bool = False,
    verbose: bool = False,
    limit: int = None,
):
    """
    Import UCLA medieval manuscripts from catalog JSON API.
    """
    if verbose:
        logger.setLevel(logging.DEBUG)

    if not db_path.exists():
        logger.error(f"Database not found: {db_path}")
        logger.info("Initialize the database first:")
        logger.info("  sqlite3 database/compilatio.db < database/schema.sql")
        return False

    # Step 1: Get all ARK IDs from catalog
    ark_ids = fetch_all_ark_ids()
    if not ark_ids:
        logger.error("No manuscripts found in collection")
        return False

    # Apply limits
    if test_mode:
        ark_ids = ark_ids[:5]
        logger.info(f"Test mode: limiting to {len(ark_ids)} manuscripts")
    elif limit:
        ark_ids = ark_ids[:limit]
        logger.info(f"Limiting to {limit} manuscripts")

    # Step 2: Fetch metadata and build records
    records = []
    errors = 0

    for i, ark_id in enumerate(ark_ids):
        logger.info(f"[{i+1}/{len(ark_ids)}] Fetching {ark_id}")

        # Fetch catalog item metadata
        catalog_data = fetch_catalog_item(ark_id)
        if not catalog_data:
            logger.warning(f"  -> Failed to fetch catalog data")
            errors += 1
            time.sleep(REQUEST_DELAY)
            continue

        # Get IIIF manifest URL
        manifest_url = extract_field(catalog_data, "iiif_manifest_url_ssi")
        if not manifest_url:
            encoded_ark = quote(ark_id, safe='')
            manifest_url = (
                f"https://iiif.library.ucla.edu/{encoded_ark}/manifest"
            )

        # Fetch IIIF v3 manifest for thumbnail and image count
        time.sleep(REQUEST_DELAY)
        manifest_data = fetch_json(manifest_url)
        if not manifest_data:
            logger.debug(
                f"  -> Could not fetch manifest (importing without thumbnail)"
            )

        # Build record
        record = build_record(catalog_data, manifest_data, ark_id)
        if record:
            records.append(record)
            logger.debug(
                f"  -> {record['shelfmark']} [{record['collection']}]"
            )
        else:
            logger.warning(f"  -> Could not build record")
            errors += 1

        time.sleep(REQUEST_DELAY)

        # Progress logging
        if (i + 1) % 25 == 0:
            logger.info(
                f"Progress: {i+1}/{len(ark_ids)} items, "
                f"{len(records)} parsed"
            )

    logger.info(
        f"Fetched {len(ark_ids)} items, built {len(records)} records, "
        f"{errors} errors"
    )

    # Step 3: Database operations
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    repo_id = ensure_repository(cursor) if not dry_run else 1

    stats = {
        "items_fetched": len(ark_ids),
        "records_built": len(records),
        "fetch_errors": errors,
        "inserted": 0,
        "updated": 0,
        "db_errors": 0,
    }

    results = {
        "inserted": [],
        "updated": [],
    }

    for record in records:
        shelfmark = record["shelfmark"]

        if dry_run:
            cursor.execute(
                "SELECT id FROM manuscripts WHERE shelfmark = ?",
                (shelfmark,)
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
                            source_url = ?,
                            image_count = ?
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
                        record.get("image_count"),
                        existing_id,
                    ))
                    stats["updated"] += 1
                else:
                    cursor.execute("""
                        INSERT INTO manuscripts (
                            repository_id, shelfmark, collection,
                            date_display, date_start, date_end,
                            contents, provenance, language, folios,
                            iiif_manifest_url, thumbnail_url,
                            source_url, image_count
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
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
                        record.get("image_count"),
                    ))
                    stats["inserted"] += 1

            except Exception as e:
                stats["db_errors"] += 1
                logger.error(f"Error importing {shelfmark}: {e}")

    if not dry_run:
        conn.commit()
    conn.close()

    # Print summary
    print_summary(stats, results, dry_run, verbose)
    return True


def print_summary(stats: dict, results: dict, dry_run: bool, verbose: bool):
    """Print import summary report."""
    print("\n" + "=" * 70)
    print(f"{'DRY RUN - ' if dry_run else ''}UCLA LIBRARY IMPORT SUMMARY")
    print("=" * 70)

    print(f"\nCatalog Crawl:")
    print(f"  Items fetched:        {stats['items_fetched']}")
    print(f"  Records built:        {stats['records_built']}")
    print(f"  Fetch errors:         {stats['fetch_errors']}")

    print(f"\nDatabase Operations {'(would be)' if dry_run else ''}:")
    print(f"  {'Would insert' if dry_run else 'Inserted'}:  {stats['inserted']}")
    print(f"  {'Would update' if dry_run else 'Updated'}:   {stats['updated']}")
    print(f"  Errors:               {stats['db_errors']}")

    if results.get("inserted"):
        print("\n" + "-" * 70)
        print(f"RECORDS TO {'INSERT' if dry_run else 'INSERTED'} (sample):")
        print("-" * 70)

        # Group by collection for display
        by_collection = {}
        for rec in results["inserted"]:
            col = rec.get("collection", "Unknown")
            by_collection.setdefault(col, []).append(rec)

        for col in sorted(by_collection.keys()):
            recs = by_collection[col]
            print(f"\n  {col} ({len(recs)}):")
            for rec in recs[:3]:
                date = (
                    f" ({rec.get('date_display', '')})"
                    if rec.get('date_display') else ""
                )
                contents = rec.get('contents', '')
                if contents and len(contents) > 60:
                    contents = contents[:57] + "..."
                print(f"    {rec['shelfmark']}{date}")
                if contents:
                    print(f"      {contents}")
            if len(recs) > 3:
                print(f"    ... and {len(recs) - 3} more")

    if results.get("updated"):
        print("\n" + "-" * 70)
        print(f"RECORDS TO {'UPDATE' if dry_run else 'UPDATED'}:")
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


# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Import UCLA medieval manuscripts from catalog JSON API"
    )
    parser.add_argument(
        '--execute',
        action='store_true',
        help='Actually execute the import (default is dry-run)'
    )
    parser.add_argument(
        '--test',
        action='store_true',
        help='Test mode: limit to first 5 manuscripts'
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
        '--limit',
        type=int,
        default=None,
        help='Limit number of manuscripts to fetch'
    )

    args = parser.parse_args()

    print("Compilatio UCLA Library Import Tool")
    print(f"Source: UCLA Digital Library - Medieval and Renaissance Manuscripts")
    print(f"DB:   {args.db}")
    print(f"Mode: {'TEST' if args.test else 'EXECUTE' if args.execute else 'DRY-RUN'}")
    if args.limit:
        print(f"Limit: {args.limit}")
    print()

    success = import_ucla(
        db_path=args.db,
        dry_run=not args.execute,
        test_mode=args.test,
        verbose=args.verbose,
        limit=args.limit,
    )

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
