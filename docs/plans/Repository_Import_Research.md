# Repository Import Research

This document captures research on potential repositories for Compilatio, including API patterns, access methods, and implementation notes.

---

## Trinity College Cambridge (Wren Library)

**Status:** Research complete, ready for implementation

**Source:** James Catalogue of Western Manuscripts
- Catalogue: https://mss-cat.trin.cam.ac.uk/Search
- ~850+ medieval manuscripts digitized (of 1,200+ total)
- Filter: "Digitised Copies Only" checkbox

### IIIF Access

**Manifest URL pattern:**
```
https://mss-cat.trin.cam.ac.uk/manuscripts/{shelfmark}.json
```

**Example:**
```
https://mss-cat.trin.cam.ac.uk/manuscripts/R.14.9.json
```

**Manifest format:** IIIF Presentation API v2

**Viewer URL:**
```
https://mss-cat.trin.cam.ac.uk/manuscripts/uv/view.php?n={shelfmark}
```

### Shelfmark Patterns

Shelfmarks follow pattern: `{Letter}.{Number}.{Number}`
- **B.x.y** - e.g., B.1.1 through B.1.46 (digitized), B.2.1 through B.2.36
- **O.x.y** - e.g., O.1.1, O.2.16, O.7.31, O.8.25, O.9.38
- **R.x.y** - e.g., R.1.2, R.14.9, R.14.30, R.14.41

### Discovery Challenge

The search API (`/Search/GetResults`) requires browser-based requests:
- POST with form data doesn't work via curl (returns error)
- Likely requires CSRF tokens, cookies, or specific headers
- **Solution:** Use Playwright or crawl4ai to scrape search results

### Implementation Approach

1. **Playwright approach (preferred):**
   - Load search page with "Digitised Copies Only" filter
   - Paginate through results (up to 100 per page)
   - Extract shelfmarks from result cards
   - Fetch IIIF manifests for each

2. **Fallback - crawl4ai:**
   - Similar browser-based crawling
   - Used successfully for National Library of Wales

3. **Last resort - enumeration:**
   - Test all possible shelfmark combinations
   - Check which return valid manifests (200 vs 404)
   - Slower but reliable

### Metadata Available

From manifest metadata array:
- Title
- Language
- Folios
- Size (cm)
- Catalogue link (to record page)

### Notes

- Some Trinity manuscripts also available via CUDL (Scriptorium project subset)
- CUDL URL pattern: `https://cudl.lib.cam.ac.uk/iiif/MS-TRINITY-COLLEGE-{shelfmark}`
- License: CC BY-NC 4.0

---

## John Rylands Library (University of Manchester)

**Status:** Initial research started, paused

**Source:** Manchester Digital Collections
- Main site: https://www.digitalcollections.manchester.ac.uk
- Medieval manuscripts collection

### IIIF Access

**Manifest URL pattern (from Biblissima):**
```
https://www.digitalcollections.manchester.ac.uk/iiif/{item-id}
```

**Example item IDs:**
- MS-LATIN-00394
- MS-LATIN-00500
- MS-ENGLISH-00094
- MS-HEBREW-00007

**Manifest format:** Appears to be IIIF compliant

### View URL Pattern

```
https://www.digitalcollections.manchester.ac.uk/view/{item-id}/{page}
```

### Discovery

- Blog post mentions MDC is IIIF compliant
- May have collection-level IIIF manifest
- Need to explore API endpoints further

### Notes

- License: CC BY-NC 4.0
- Significant medieval Latin manuscript holdings
- Research paused in favor of Yale Takamiya

---

## Yale Beinecke (Takamiya Collection)

**Status:** Complete - imported 139 manuscripts

**Importer:** `scripts/importers/yale_takamiya.py`

### Technical Details

**Discovery API:**
```
https://collections.library.yale.edu/catalog.json?q=takamiya&per_page=100
```

**Manifest URL:**
```
https://collections.library.yale.edu/manifests/{catalog-id}
```

**Manifest format:** IIIF Presentation API v3

### Implementation Notes

- Clean JSON API, no browser automation needed
- Paginated results (100 per page)
- All 139 manuscripts public access
- 138 completely digitized, 1 partial

---

## Parker Library (Corpus Christi College, Cambridge)

**Status:** Partial - 176 of ~560 imported

**Importer:** `scripts/importers/parker.py`

### Technical Details

**Manifest URL:**
```
https://purl.stanford.edu/{druid}/iiif/manifest
```

**Discovery:**
- Stanford's bot protection blocks automated access
- Workaround: manually save HTML pages, parse locally
- `--from-html` mode in importer

### Current State

- Pages 1-2 downloaded and imported (176 manuscripts)
- Pages 3-6 need re-download (still duplicates of page 1)
- HTML files location: `scripts/importers/resources/parker_html/`

### Manual Download URLs

```
https://parker.stanford.edu/parker/browse/browse-by-manuscript-number?per_page=96&page=1
https://parker.stanford.edu/parker/browse/browse-by-manuscript-number?per_page=96&page=2
...through page=6
```

---

## Completed Repositories Reference

### Bodleian Library
- Importer: `scripts/importers/bodleian.py`
- Source: TEI XML files from GitHub repo
- 1,713 manuscripts (fully digitized only)

### Cambridge University Library
- Importer: `scripts/importers/cambridge.py`
- Source: CUDL IIIF collection
- 304 manuscripts

### British Library
- Importer: `scripts/importers/british_library.py`
- Source: Playwright-based (JS rendering required)
- 178 manuscripts (Cotton, Harley, Royal)

### Durham University Library
- Importer: `scripts/importers/durham.py`
- Source: IIIF collection tree crawl
- 287 manuscripts

### National Library of Scotland
- Importer: `scripts/importers/nls.py`
- Source: IIIF collection tree crawl
- 104 manuscripts

### National Library of Wales
- Importer: `scripts/importers/nlw.py`
- Source: crawl4ai discovery + IIIF manifests
- 226 manuscripts

### Huntington Library
- Importer: `scripts/importers/huntington.py`
- Source: CONTENTdm API
- 190 manuscripts (Ellesmere + HM 1-946)

### Lambeth Palace Library
- Importer: `scripts/importers/lambeth.py`
- Source: CUDL Scriptorium subset
- 2 manuscripts (main LUNA portal blocked)

### UCLA
- 115 manuscripts (pre-existing)

---

## Future Repositories

### Harvard (Houghton Library)
- No research yet
- Listed as future target

---

## Technical Patterns Summary

| Repository | Discovery Method | Manifest Format | Auth Required |
|------------|------------------|-----------------|---------------|
| Trinity Cambridge | Playwright/crawl4ai | IIIF v2 | No (public) |
| John Rylands | TBD | IIIF v2? | No |
| Yale Beinecke | JSON API | IIIF v3 | No |
| Parker Library | Manual HTML | IIIF v2 | No (bot blocked) |
| Bodleian | TEI XML files | IIIF v2 | No |
| CUL | IIIF Collection | IIIF v2 | No |
| British Library | Playwright | IIIF v2 | No |
| Durham | IIIF Collection | IIIF v2 | No |
| NLS | IIIF Collection | IIIF v2 | No |
| NLW | crawl4ai | IIIF v2 | No |
| Huntington | CONTENTdm API | IIIF v2 | No |
