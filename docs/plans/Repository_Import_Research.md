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

### Shelfmark Ranges (Known Digitized)

Shelfmarks follow pattern: `{Letter}.{Number}.{Number}` with occasional suffixes (e.g., B.1.30A).

**B Series:**
- B.1.1 to B.1.46 (includes B.1.30A)
- B.2.1 to B.2.36
- B.3.1 to B.3.35
- B.4.1 to B.4.32
- B.5.1 to B.5.28
- B.7.1 to B.7.7
- B.8.1 to B.8.12
- B.9.1 to B.9.15
- B.10.1 to B.10.27
- B.11.1 to B.11.34
- B.13.1 to B.13.30
- B.14.1 to B.14.55
- B.15.1 to B.15.42
- B.16.1 to B.16.47
- B.17.1 to B.17.42

**F Series:**
- F.12.40 to F.12.44

**O Series:**
- O.1.1 to O.1.79
- O.2.1 to O.2.68
- O.3.1 to O.3.63
- O.4.1 to O.4.52
- O.5.2 to O.5.54
- O.7.1 to O.7.47
- O.8.1 to O.8.37
- O.9.1 to O.9.40
- O.10.2 to O.10.34
- O.11.2 to O.11.19

**R Series:**
- R.1.2 to R.1.92
- R.2.4 to R.2.98
- R.3.1 to R.3.68
- R.4.1 to R.4.52
- R.5.3 to R.5.46
- R.7.1 to R.7.51
- R.8.3 to R.8.35
- R.9.8 to R.9.39
- R.10.5 to R.10.15
- R.11.1 to R.11.2
- R.13.8 to R.13.74
- R.14.1 to R.14.16
- R.15.1 to R.15.55
- R.16.2 to R.16.40
- R.17.1 to R.17.23

### Discovery Challenge

The search API (`/Search/GetResults`) requires browser-based requests:
- POST with form data doesn't work via curl (returns error)
- Likely requires CSRF tokens, cookies, or specific headers
- **Solution:** Use Playwright or crawl4ai to scrape search results

### Implementation Approach

**Current approach: Shelfmark enumeration**

The Playwright-based discovery was unreliable (pagination issues), so we use known shelfmark ranges instead.

**Script:** `scripts/importers/trinity_cambridge.py`

**Workflow:**
1. Generate all candidate shelfmarks from documented ranges (1,663 total)
2. Test each against manifest endpoint (HTTP 200 = exists, 404 = skip)
3. Fetch and parse valid IIIF manifests
4. Insert into database with checkpoint after each item

**Script Features:**
- Rate limiting: 0.5s delay between requests
- Timeout: 30s per manifest fetch
- Checkpoint file: `scripts/importers/cache/trinity_progress.json`
- Resume support: `--resume` skips already-completed and not-found shelfmarks
- Standard library only (no Playwright/crawl4ai dependency)

**Usage:**
```bash
python3 scripts/importers/trinity_cambridge.py --execute           # Full import
python3 scripts/importers/trinity_cambridge.py --resume --execute  # Resume after interrupt
python3 scripts/importers/trinity_cambridge.py --test              # First 10 only (dry-run)
```

**Estimated runtime:** ~15-20 minutes for full import (1,663 candidates × 0.5s delay)

**Previous approaches (deprecated):**
- Playwright scraping: Failed due to AJAX pagination issues
- crawl4ai: Not attempted (Playwright issues likely apply)

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

**Status:** Complete - imported 138 manuscripts (2026-02-02)

**Importer:** `scripts/importers/john_rylands.py`

### Technical Details

**Discovery:** Biblissima IIIF Collections search
- URL: `https://iiif.biblissima.fr/collections/search?q=manchester+rylands`
- 138 manuscripts with MS-* shelfmarks (excludes PR-* printed materials)

**Manifest URL pattern:**
```
https://www.digitalcollections.manchester.ac.uk/iiif/{item-id}
```

**Manifest format:** IIIF Presentation API v2

### Implementation Notes

- Two-phase import: Biblissima discovery → MDC manifest fetch
- Shelfmark normalization: MS-LATIN-00006 → "Latin MS 6"
- Collections: Latin, English, Hebrew, French, Italian, Gaster Hebrew, etc.
- Uses BeautifulSoup for HTML parsing (no JS rendering needed)

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

### John Rylands Library
- Importer: `scripts/importers/john_rylands.py`
- Source: Biblissima discovery + MDC IIIF manifests
- 138 manuscripts (Latin, English, Hebrew, etc.)

### Harvard Houghton Library
- Importer: `scripts/importers/harvard.py`
- Source: Biblissima discovery + Harvard DRS manifests
- 238 manuscripts (Latin, Typographic, Greek, etc.)

---

## Future Repositories

Potential repositories for future expansion:

| Repository | Estimated MSS | Notes |
|------------|---------------|-------|
| Walters Art Museum | ~300 | IIIF compliant |
| Morgan Library | ~300 | Corsair collection |
| Bibliothèque nationale | ~200 | Gallica IIIF |
| Bayerische Staatsbibliothek | ~150 | BSB IIIF |

---

## Harvard Houghton Library (Detailed)

**Status:** Complete - imported 238 manuscripts (2026-02-02)

**Importer:** `scripts/importers/harvard.py`

### Technical Details

**Discovery:** Biblissima IIIF Collections search
- URL: `https://iiif.biblissima.fr/collections/search?q=houghton+harvard`
- 240 discovered, 238 imported (2 duplicates)

**Manifest URL pattern:**
```
https://iiif.lib.harvard.edu/manifests/drs:{DRS_ID}
```

**Manifest format:** IIIF Presentation API v2

### Implementation Notes

- Two-phase import: Biblissima discovery → Harvard DRS manifest fetch
- Shelfmark extraction from manifest labels (embedded in title strings)
- Patterns: MS Lat, MS Typ, MS Gr, MS Richardson, etc.
- Uses BeautifulSoup for HTML parsing (no JS rendering needed)

---

## Technical Patterns Summary

| Repository | Discovery Method | Manifest Format | Auth Required |
|------------|------------------|-----------------|---------------|
| Trinity Cambridge | Shelfmark enumeration | IIIF v2 | No (public) |
| John Rylands | Biblissima scrape | IIIF v2 | No |
| Harvard Houghton | Biblissima scrape | IIIF v2 | No |
| Yale Beinecke | JSON API | IIIF v3 | No |
| Parker Library | Manual HTML | IIIF v2 | No (bot blocked) |
| Bodleian | TEI XML files | IIIF v2 | No |
| CUL | IIIF Collection | IIIF v2 | No |
| British Library | Playwright | IIIF v2 | No |
| Durham | IIIF Collection | IIIF v2 | No |
| NLS | IIIF Collection | IIIF v2 | No |
| NLW | crawl4ai | IIIF v2 | No |
| Huntington | CONTENTdm API | IIIF v2 | No |
