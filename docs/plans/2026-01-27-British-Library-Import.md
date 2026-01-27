# British Library Import Plan

## Overview

Import digitized medieval manuscripts from the British Library catalogue into Compilatio, focusing on three major collections: Cotton, Harley, and Royal.

## Reference Materials

### Existing Code in Connundra

The Connundra project contains a working Cotton Collection scraper in `database/`:

| File | Purpose |
|------|---------|
| `scrape_cotton_collection.py` | Main orchestration script |
| `bl_config.py` | URLs, selectors, field mappings |
| `bl_search_scraper.py` | Paginated search result scraping |
| `bl_detail_scraper.py` | Individual manuscript page scraping |
| `bl_iiif_locator.py` | IIIF manifest URL extraction |

This code handles:
- Async HTTP requests with rate limiting
- Search result pagination (100 per page)
- Detail page metadata extraction
- IIIF manifest URL discovery
- Resume capability for interrupted scrapes
- Database insertion with duplicate checking

### Digitized-Only Filter

The BL catalogue supports filtering to items with digital surrogates:

```
https://searcharchives.bl.uk/?f%5Burl_non_blank_si%5D%5B%5D=Yes+%28available%29
```

Decoded: `f[url_non_blank_si][]=Yes (available)`

This filter should be applied to all collection queries to ensure we only import manuscripts that have IIIF manifests.

### Target Collections

| Collection | Search Parameter | Notes |
|------------|------------------|-------|
| Cotton | `f[project_collections_ssim][]=Cotton Collection` | ~2,900 items total, ~500-600 digitized |
| Harley | `f[project_collections_ssim][]=Harley Collection` | Major collection, many digitized |
| Royal | `f[project_collections_ssim][]=Royal Collection` | Medieval royal library |

All queries also include: `f[collection_area_ssi][]=Western Manuscripts`

---

## Phase 1: Adapt Scraper Infrastructure

**Status: COMPLETE**

**Goal**: Create Compilatio-specific BL scraper based on Connundra code.

### Completed

1. **Created `scripts/importers/british_library.py`** - Single-file importer using Playwright for browser-based scraping (BL site requires JavaScript)

2. **Key technical decisions**:
   - Uses Playwright instead of crawl4ai (simpler dependency)
   - Digitized-only filter applied to all searches
   - Paginates until no more results (BL doesn't show total counts)
   - Filters to "MS" items only (excludes Charters, Rolls)
   - Extracts IIIF manifest URLs from detail pages

3. **Dependencies added to `requirements.txt`**:
   - playwright
   - beautifulsoup4

### Usage (on rabota)

```bash
# Setup (one-time)
cd /path/to/Compilatio
python3 -m venv .venv
source .venv/bin/activate
pip install playwright beautifulsoup4
playwright install chromium

# Run importer
python scripts/importers/british_library.py --collection cotton          # Dry-run
python scripts/importers/british_library.py --collection cotton --execute # Execute
python scripts/importers/british_library.py --collection cotton --test    # Test mode (1 page, 5 items)
```

### Test Results

- Successfully scraped Cotton Collection digitized items
- Page 1: 100 items total, 41 Cotton MS (rest are Charters)
- Detail pages: metadata + IIIF manifest extraction working
- Rate limiting: 2.5 seconds between requests

---

## Phase 2: Cotton Collection Import (on rabota)

**Status: Not Started**

**Goal**: Import all digitized Cotton manuscripts.

### Tasks

```bash
# On rabota
source .venv/bin/activate

# Test first
python scripts/importers/british_library.py --collection cotton --test

# Full import
python scripts/importers/british_library.py --collection cotton --execute
```

### Expected Output

- Cotton manuscripts added to database
- Repository record for "British Library" created
- All entries have IIIF manifest URLs

---

## Phase 3: Harley Collection Import (on rabota)

**Status: Not Started**

**Goal**: Import all digitized Harley manuscripts.

```bash
python scripts/importers/british_library.py --collection harley --test
python scripts/importers/british_library.py --collection harley --execute
```

---

## Phase 4: Royal Collection Import (on rabota)

**Status: Not Started**

**Goal**: Import all digitized Royal manuscripts.

```bash
python scripts/importers/british_library.py --collection royal --test
python scripts/importers/british_library.py --collection royal --execute
```

---

## Phase 5: Documentation and Cleanup

**Status: Not Started**

**Goal**: Document the import process for future use.

### Tasks

1. Update `Compilatio_Project_Status.md` with import results
2. Verify manuscripts display correctly in Compilatio UI

---

## Technical Notes

### BL Catalogue Structure

The BL uses Blacklight (Ruby on Rails) for their catalogue. Key observations from the Connundra scraper:

- Search results use CSS class `.document` for each entry
- Metadata fields use `dt`/`dd` pairs with Blacklight field classes like `blacklight-reference_ssi`
- IIIF manifests are served from `bl.digirati.io/iiif`
- Rate limiting of 2.5 seconds between requests recommended

### Compilatio Database Mapping

| BL Field | Compilatio Field |
|----------|------------------|
| Reference (shelfmark) | `shelfmark` |
| Title / Scope & Content | `contents` |
| Date Range | `date_display` |
| Project Collection | `collection` |
| (static) | `repository` = "British Library" |
| IIIF manifest URL | `iiif_manifest_url` |
| Thumbnail from IIIF | `thumbnail_url` |

### Shelfmark Formats

- Cotton: `Cotton MS Tiberius B V/1`
- Harley: `Harley MS 603`
- Royal: `Royal MS 2 B VII`

---

## Risk Mitigation

1. **Rate limiting**: BL may block aggressive crawling. Use 2.5s delay, consider longer if issues arise.
2. **HTML changes**: BL may update their catalogue UI. Selectors may need adjustment.
3. **Incomplete IIIF**: Some "digitized" items may not have proper manifests. Log and skip.

---

## Success Criteria

- [ ] Cotton digitized manuscripts imported with IIIF URLs
- [ ] Harley digitized manuscripts imported with IIIF URLs
- [ ] Royal digitized manuscripts imported with IIIF URLs
- [ ] All manuscripts viewable in Universal Viewer via Compilatio UI
- [ ] British Library attribution displays correctly on viewer page
