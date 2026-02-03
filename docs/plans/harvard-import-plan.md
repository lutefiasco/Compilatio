# Harvard Houghton Library Import Plan

**Date:** 2026-02-02
**Status:** Complete
**Scope:** 238 Harvard/Houghton Library manuscripts (via Biblissima)

---

## Executive Summary

Harvard Houghton Library has approximately **249 digitized medieval manuscripts** indexed by Biblissima.

**Recommended Approach:** Biblissima scraping - provides a pre-curated list of medieval manuscripts with verified IIIF manifests. The alternative (LibraryCloud API) would require extensive filtering to isolate medieval manuscripts from 2,000+ items.

---

## Technical Assessment

### Platform Overview

| Component | Details |
|-----------|---------|
| Repository | Houghton Library, Harvard University |
| Digital Repository System | Harvard DRS (Digital Repository Service) |
| IIIF Version | Presentation API v2 |
| Manifest URL Pattern | `https://iiif.lib.harvard.edu/manifests/drs:{DRS_ID}` |
| Image API Base | `https://ids.lib.harvard.edu/ids/iiif/` |
| Viewer | Harvard Digital Collections |

### IIIF Manifest Structure

From manifests like MS Lat 249 (`drs:26120881`):

```json
{
  "@context": "http://iiif.io/api/presentation/2/context.json",
  "@type": "sc:Manifest",
  "@id": "https://iiif.lib.harvard.edu/manifests/drs:26120881",
  "label": "Catholic Church. Book of hours : use of Rome : manuscript, [ca. 1485]. MS Lat 249. Houghton Library, Harvard University, Cambridge, Mass.",
  "license": "http://nrs.harvard.edu/urn-3:hul.ois:hlviewerterms",
  "sequences": [...],
  "metadata": [...]
}
```

**Key Observations:**
- Manifest `label` contains both title AND shelfmark - requires parsing
- Shelfmark patterns: `MS Lat {N}`, `MS Typ {N}`, `MS Gr {N}`, `MS Richardson {N}`
- Date often embedded in label in brackets `[ca. 1485]`
- Metadata array is minimal - most info is in the label

### No Public IIIF Collection Manifest

**Critical finding:** Harvard does NOT publish a public IIIF collection manifest for Houghton manuscripts. No equivalent to Cambridge's collection endpoint.

---

## Import Approach: Biblissima Scraping

### Why Biblissima?

- Pre-curated list of 249 medieval manuscripts (already filtered)
- Includes shelfmark, date, language metadata
- Direct IIIF manifest URLs provided
- No need to filter non-medieval content from 2,000+ LibraryCloud results

### Discovery Source

- URL: `https://iiif.biblissima.fr/collections/search?q=houghton+harvard&from={offset}`
- 249 results, 20 per page (13 pages)
- Pagination: `from=0`, `from=20`, ... `from=240`

### Method

**Phase 1: Discovery**
- Scrape all 13 Biblissima search result pages
- Extract: shelfmark, IIIF manifest URL, title, date, language
- Cache results in `harvard_discovery.json`

**Phase 2: Import**
- Fetch each manifest from Harvard (`iiif.lib.harvard.edu`)
- Parse full metadata from manifest
- Insert into Compilatio database

---

## Data Mapping

| Source (Biblissima/Manifest) | Compilatio Field | Notes |
|------------------------------|------------------|-------|
| Shelfmark from title/HTML | `shelfmark` | Extract "MS Lat 249" from full title |
| Collection from shelfmark | `collection` | "Latin", "Typographic", "Greek", etc. |
| Manifest label | `contents` | Extract title portion, remove shelfmark |
| Date from label/HTML | `date_display` | Parse "[ca. 1485]" format |
| Date parsed | `date_start`, `date_end` | Parse centuries and year ranges |
| Language from HTML | `language` | "lat", "fre", etc. |
| Manifest @id | `iiif_manifest_url` | Direct Harvard manifest URL |
| First canvas image | `thumbnail_url` | Derive from IIIF Image API |
| Harvard DRS viewer | `source_url` | Link to Harvard Digital Collections |

---

## Shelfmark Patterns and Collection Mapping

```python
COLLECTION_MAPPING = {
    r'^MS Lat': "Latin",
    r'^MS Typ': "Typographic",
    r'^MS Gr': "Greek",
    r'^MS Richardson': "Richardson",
    r'^MS Ital': "Italian",
    r'^MS Span': "Spanish",
    r'^MS Eng': "English",
    r'^MS Fr': "French",
    r'^MS Ger': "German",
}
```

---

## Script Structure

```
scripts/importers/harvard.py
scripts/importers/cache/
    harvard_discovery.json   # Cached Biblissima scrape results
    harvard_progress.json    # Checkpoint file
```

**CLI Arguments:**

```bash
python scripts/importers/harvard.py                    # Dry-run
python scripts/importers/harvard.py --execute          # Execute import
python scripts/importers/harvard.py --test             # First 5 only
python scripts/importers/harvard.py --verbose          # Detailed logging
python scripts/importers/harvard.py --resume --execute # Resume from checkpoint
python scripts/importers/harvard.py --discover-only    # Only scrape Biblissima
python scripts/importers/harvard.py --skip-discovery   # Use cached discovery
python scripts/importers/harvard.py --limit 50         # Process only 50 manuscripts
```

---

## Progress File Structure

```json
{
  "last_updated": "2026-02-02T12:00:00Z",
  "total_discovered": 249,
  "completed_ids": ["drs:26120881", "drs:16110663"],
  "failed_ids": [],
  "phase": "import"
}
```

---

## Rate Limiting

- Biblissima scraping: 1 second delay between page requests (13 requests)
- Harvard manifests: 0.5 second delay between fetches (249 requests)
- Total estimated time: ~7-10 minutes for full import

---

## Repository Setup

```sql
INSERT INTO repositories (name, short_name, logo_url, catalogue_url)
VALUES (
    'Houghton Library, Harvard University',
    'Harvard',
    NULL,
    'https://library.harvard.edu/collections/medieval-and-renaissance-manuscripts'
);
```

---

## Error Handling

1. **Biblissima page errors:** Retry 3 times, then log and continue
2. **Manifest fetch failures (404s):** Mark as failed in progress file, continue
3. **Parse errors:** Log warning with DRS ID, skip, continue
4. **Database errors:** Log error, continue with remaining items

---

## Testing Workflow

```bash
# 1. Dry-run discovery
python scripts/importers/harvard.py --discover-only

# 2. Verify discovery cache
cat scripts/importers/cache/harvard_discovery.json | python -m json.tool | head -50

# 3. Test mode (5 manuscripts)
python scripts/importers/harvard.py --skip-discovery --test --verbose

# 4. Full dry-run
python scripts/importers/harvard.py --skip-discovery

# 5. Execute import
python scripts/importers/harvard.py --skip-discovery --execute

# 6. Verify database
sqlite3 database/compilatio.db "SELECT shelfmark, collection, date_display FROM manuscripts WHERE repository_id = (SELECT id FROM repositories WHERE short_name = 'Harvard') LIMIT 10;"
```

---

## Validation Checklist

- [ ] Biblissima scraping returns 249 manuscripts
- [ ] DRS IDs correctly extracted and validated
- [ ] IIIF manifests accessible for all discovered items
- [ ] Shelfmark parsing handles all patterns (MS Lat, MS Typ, etc.)
- [ ] Date parsing works for various formats ([ca. 1485], [15th century])
- [ ] Collection assignment correct
- [ ] Thumbnails load correctly
- [ ] Source URLs link to Harvard Digital Collections
- [ ] Checkpoint/resume works correctly
- [ ] Dry-run mode accurate

---

## Risk Assessment

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Biblissima structure changes | Low | Fallback to LibraryCloud API |
| Harvard rate limits | Medium | 0.5s delay, respectful User-Agent |
| Missing manifests (404s) | Low | Track in failed_ids, report at end |
| Shelfmark parsing edge cases | Medium | Start with test mode, refine regex |

---

## Alternative Approach: LibraryCloud API

If Biblissima becomes unavailable:

**API:** `https://api.lib.harvard.edu/v2/items.json`
- Rate Limit: 300 requests per 5 minutes
- Query: `?q=MS+Lat&physicalLocation=Houghton&limit=250`

**Challenges:**
- Returns 2,000+ results including printed books
- No direct filter for "medieval" or "manuscript"
- Requires extensive post-processing

---

## Reference Files

- `scripts/importers/huntington.py` - Best pattern for two-phase discovery/import with checkpoint support
- `scripts/importers/cambridge.py` - IIIF collection crawl and metadata parsing
- `scripts/importers/nlw.py` - BeautifulSoup HTML scraping pattern
- `Compilatio_Expansions.md` - Required script structure, CLI arguments, checkpoint format
