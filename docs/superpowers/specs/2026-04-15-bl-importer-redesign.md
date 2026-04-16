# British Library Importer Redesign

Replaces the Playwright-based `british_library.py` with a JSON API pipeline modeled on HONR's `scrape_bl_catalogue.py`. Expands BL coverage from 3 collections (Cotton, Harley, Royal) to all medieval digitized Western Manuscripts.

## Motivation

The BL has significantly expanded its IIIF digitization since Compilatio's last BL import (Cotton 41 -> ~287, Harley 56 -> ~246). The old importer uses Playwright to scrape rendered HTML, which is slow and fragile. The BL's `searcharchives.bl.uk` serves JSON via `?format=json` on both search and detail pages, providing structured access to all metadata including IIIF manifest URLs, thumbnails, ARK identifiers, dates, and provenance.

Compilatio is the only live site across the Geekery projects (https://oldbooks.humspace.ucla.edu), so the database must be treated carefully.

## Architecture: Four Scripts, Two JSON Files

```
scrape_bl_inventory.py          scrape_bl_details.py
        |                               |
        v                               v
data/bl_inventory.json  --->  data/bl_manuscripts.json
(full BL listing)             (filtered + IIIF-enriched)
                                        |
                                        v
                                  import_bl.py
                                        |
                                        v
                                  compilatio.db
                                        |
                                        v
                              sync_bl_concordance.py
                                        |
                                        v
                                  concordance.db
```

Each script is independently runnable. No script triggers the next automatically. The user inspects output between phases.

## Script 1: `scripts/importers/scrape_bl_inventory.py`

Scrapes the complete BL digitized Western Manuscripts inventory via JSON API.

**API endpoint:**
```
https://searcharchives.bl.uk/?f[collection_area_ssi][]=Western+Manuscripts&f[url_non_blank_si][]=Yes+(available)&format=json&per_page=100&page={N}
```

**Behavior:**
- Paginates through all results at 100/page, 1s delay between requests
- For each record, extracts from the search-results JSON:
  - `id` (BL record ID, e.g., `040-002354542`)
  - `reference_ssi` (shelfmark)
  - `title_tsi` (title, HTML-stripped)
  - `project_collections_ssim` (collection name)
  - `start_date_tsi`, `end_date_tsi`, `date_range_tsi`
  - `links.self` (catalogue URL)
- Filters to `040-` prefixed record IDs only (manuscript-level records)
- Saves all records to `data/bl_inventory.json`
- Resumable: saves progress to `data/bl_inventory_state.json` after each page
- SIGINT handler saves state before exit

**CLI:**
```
python3 scripts/importers/scrape_bl_inventory.py              # Run/resume
python3 scripts/importers/scrape_bl_inventory.py --restart     # Start fresh
python3 scripts/importers/scrape_bl_inventory.py --limit 3     # Test: 3 pages
python3 scripts/importers/scrape_bl_inventory.py --retry-failed
```

**Output:** `data/bl_inventory.json` — array of records. This file is the diffable inventory for detecting future BL additions.

## Script 2: `scripts/importers/scrape_bl_details.py`

Filters the inventory and fetches IIIF detail pages for new manuscripts.

**Filter pipeline (applied in order):**

1. **Collection include-list** — only manuscripts from known collections (see filter config below)
2. **Prefix exclusions** — skip charters, rolls, seals by shelfmark prefix
3. **Date filter** — for mixed-period collections (Additional, Sloane), require `end_date <= 1550`. If no date fields present, include but flag for review.
4. **Existing manuscript check** — query compilatio.db for known BL shelfmarks, skip those already present (unless `--refresh-existing`)

**Filter configuration** (dict at top of script):

```python
# Collections to include unconditionally (all dates)
INCLUDE_COLLECTIONS = [
    "Cotton Collection",
    "Harley Collection",
    "Royal Collection",
    "Arundel Collection",
    "Egerton Collection",
    "Lansdowne Collection",
    "Stowe Collection",
    "Burney Collection",
    "Yates Thompson Collection",
]

# Collections to include with date filtering (end_date <= 1550)
DATE_FILTERED_COLLECTIONS = [
    "Additional Manuscripts",
    "Sloane Collection",
]

# Collections to exclude entirely
EXCLUDE_COLLECTIONS = [
    "Zweig Collection",
    "Ashley Collection",
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
```

These lists are provisional. The inventory scrape will reveal the actual collection names and shelfmark prefixes in use; the lists get refined before the first real detail crawl.

**Detail page fetch:**

For each manuscript passing filters, fetches:
```
https://searcharchives.bl.uk/catalog/{record_id}?format=json
```

Extracts:

| BL JSON field | Output field | Extraction |
|---|---|---|
| `reference_ssi` | `shelfmark` | Plain text |
| `project_collections_ssim` | `collection` | Plain text |
| `date_range_tsi` | `date_display` | Plain text |
| `start_date_tsi` | `date_start` | Integer |
| `end_date_tsi` | `date_end` | Integer |
| `scope_and_content_tsi` | `contents` | Strip HTML |
| `custodial_history_tsi` | `provenance` | Strip HTML |
| `language_ssim` | `language` | Plain text |
| `extent_tsi` | `folios` | Strip HTML |
| `url_tsi` | `iiif_manifest_url` | Extract URL from `<a href="...">` |
| `thumbnail_path_ss` | `thumbnail_url` | Extract URL from `<img src="...">` |
| `lark_tsi` | `ark_id` | Plain text (stored in JSON, not in DB) |
| `links.self` | `source_url` | Plain text |

**CLI:**
```
python3 scripts/importers/scrape_bl_details.py                    # Run with filters
python3 scripts/importers/scrape_bl_details.py --collection cotton # One collection
python3 scripts/importers/scrape_bl_details.py --refresh-existing  # Re-fetch known MSS
python3 scripts/importers/scrape_bl_details.py --limit 5           # Test: 5 detail pages
python3 scripts/importers/scrape_bl_details.py --verbose           # Show filter decisions
```

**Output:**
- `data/bl_manuscripts.json` — array of enriched manuscript records ready for import
- Filter summary to stderr: per-collection counts of passed/skipped with reasons

**Resumable:** Saves progress to `data/bl_details_state.json`. SIGINT-safe.

## Script 3: `scripts/importers/import_bl.py`

Upserts manuscripts from `data/bl_manuscripts.json` into compilatio.db.

**Behavior:**
- Ensures the "British Library" repository row exists (short_name `BL`)
- For each manuscript, checks for existing row by `(repository_id, shelfmark)` UNIQUE constraint
  - Existing: UPDATE metadata fields (dates, contents, provenance, IIIF URLs, etc.)
  - New: INSERT full row
- Dry-run by default. `--execute` required to write.
- Prints per-collection summary table: new / updated / skipped / errors

**Collection name extraction:** Uses `project_collections_ssim` from the BL data, mapped to short names for the `collection` column:

```python
COLLECTION_MAP = {
    "Cotton Collection": "Cotton",
    "Harley Collection": "Harley",
    "Royal Collection": "Royal",
    "Arundel Collection": "Arundel",
    # etc.
}
```

**CLI:**
```
python3 scripts/importers/import_bl.py                        # Dry run (default)
python3 scripts/importers/import_bl.py --execute              # Write to DB
python3 scripts/importers/import_bl.py --execute --collection cotton  # One collection
python3 scripts/importers/import_bl.py --verbose
```

**Does not touch the concordance.** Full stop.

## Script 4: `scripts/importers/sync_bl_concordance.py`

Registers new Compilatio BL manuscripts in the Scriptorium concordance. Written after a careful audit of the current concordance schema and `build_concordance.py`.

**Development approach:**

Before writing any code, this script's development begins with an audit:

1. Read `~/Geekery/Scriptorium/tools/build_concordance.py` — understand what `--update` does today, specifically the Compilatio seeding logic (lines ~194-240)
2. Read the current concordance schema — identify all tables, especially anything added since the original build (scholarly xrefs, works, people, institutions, authors)
3. Identify which tables are safe to write: `concordance`, `concordance_variants`, `concordance_provenance`
4. Identify which tables must never be touched: everything else
5. Document findings in the script's docstring

**Behavior:**
- Queries compilatio.db for BL manuscripts
- Queries concordance.db for existing rows with `compilatio_id` set
- For new manuscripts (no concordance row):
  - Creates a new concordance row with `shelfmark_canonical`, `shelfmark_normalized`, `compilatio_id`, `repository`, `collection`
  - Uses Scriptorium's `shared.normalize()` for the normalized form
  - Logs creation in `concordance_provenance`
- For new manuscripts that match an existing concordance row by normalized shelfmark (e.g., a Cotton MS already in concordance via CONR):
  - Sets `compilatio_id` on the existing row
  - Does NOT overwrite any other project's ID (`cotton_id`, `royal_id`, `harley_id`, etc.)
  - Logs the link in `concordance_provenance`
- Adds BL shelfmark variants to `concordance_variants` with source `Compilatio_BL_2026`
- **Append-only.** Never deletes rows. Never nulls existing IDs. Never touches scholarly tables.
- Dry-run by default. `--execute` required to write.
- Dry run prints exactly what would be created/linked, so you can review before committing.

**CLI:**
```
python3 scripts/importers/sync_bl_concordance.py                # Dry run
python3 scripts/importers/sync_bl_concordance.py --execute      # Write
python3 scripts/importers/sync_bl_concordance.py --verbose      # Show matching logic
python3 scripts/importers/sync_bl_concordance.py --audit-only   # Just report concordance state, no writes
```

## What We're Not Changing

- **compilatio.db schema** — existing columns are sufficient
- **`british_library.py`** — old Playwright importer left in place, superseded not deleted
- **`build_concordance.py`** — not modified; script 4 is purpose-built
- **Frontend** — no changes to server.py, src/, php_deploy/
- **Other importers** — Bodleian, Cambridge, etc. untouched

## Post-Implementation

- Update `Feb04_2026_Status.md` with new BL counts and importer table
- Update `CLAUDE.md` to reference new scripts
- Update `~/Geekery/Scriptorium/docs/active-planning.md`
- Production deploy via existing `deploy_production.sh` pipeline

## Dependencies

- `requests` (already available, used by other scripts)
- No new dependencies. No Playwright. No BeautifulSoup (we're parsing JSON, not HTML; URL extraction from HTML-in-JSON fields uses regex).

## Operational Notes

- **First run estimate:** Inventory scrape ~5-10 minutes (depends on total BL pages). Detail scrape ~10-20 minutes for ~500 new manuscripts at 1s/page. Import is instant.
- **Rate limiting:** 1s delay between all BL API requests. User-Agent: `Compilatio/1.0 (manuscript research; IIIF aggregator)`
- **Subsequent runs:** Inventory scrape same duration (full refresh). Detail scrape much faster (only new manuscripts). Import same.
- **The intermediate JSON files are the safety net.** If anything goes wrong, the data is sitting in `data/` and no database was touched. You can inspect, adjust filters, and re-run the import without re-scraping.
