# Additional Repositories Import Plan

## Overview

Integrate five new manuscript repositories into Compilatio, prioritised by technical feasibility. Each repository is implemented as an independent importer script following the existing pattern (`scripts/importers/*.py`), with dry-run and execute modes.

**Priority order:**
1. Cambridge University Library (CUDL IIIF collection, 304 MSS) — **imported**
2. Durham University Library (IIIF collection tree, 287 MSS) — **imported**
3. National Library of Scotland (IIIF collection tree, 104 MSS) — **imported**
4. National Library of Wales (249 MSS via crawl4ai) — **imported**
5. Lambeth Palace Library (CUDL subset, 2 MSS) — **imported**

**All repositories complete.** Total new manuscripts: 946. Grand total: 2,837.

Each repository is a self-contained chunk. Complete one before starting the next.

---

## Repository 1: Durham University Library

### Source Data
- **IIIF collection tree**: `https://iiif.durham.ac.uk/manifests/trifle/collection/index` (97 sub-collections)
- **Catalogue**: `https://reed.dur.ac.uk/xtf/search`
- **Viewer**: `https://iiif.durham.ac.uk/index.html` (Mirador)
- **ARK IDs**: `https://n2t.durham.ac.uk/ark:/32150/...`
- **Est. manuscripts**: ~300 medieval manuscripts, nearly all digitized

### Approach: IIIF Collection Tree Crawl (no browser needed)

The IIIF collection at `iiif.durham.ac.uk` is a JSON tree of sub-collections containing individual manifests. This can be crawled with plain HTTP requests.

### Steps

#### 1a. Probe the IIIF collection tree
- Fetch `https://iiif.durham.ac.uk/manifests/trifle/collection/index`
- Map the tree structure: how many sub-collections, how manifests are nested
- Identify which sub-collections contain medieval manuscripts vs. other material
- Document the manifest URL pattern and metadata available in manifests

#### 1b. Write Durham importer script
- `scripts/importers/durham.py`
- Crawl the IIIF collection tree recursively (JSON, no Playwright needed)
- For each manifest, extract: shelfmark (from `label`), thumbnail (from `thumbnail`), manifest URL
- For richer metadata: fetch each manifest and parse IIIF Presentation v2 `metadata` array
- Map IIIF metadata labels to Compilatio schema fields (date, contents, language, provenance)
- Extract collection name from shelfmark (e.g. "Durham Cathedral Library MS. A.I.3" -> "Cathedral A")
- Rate limit: 0.5s between manifest fetches
- Dry-run / --execute / --test modes matching existing importers

#### 1c. Run Durham import
- Dry-run to verify mapping
- Execute import
- Verify thumbnails load in browse page
- Spot-check viewer deep links

---

## Repository 2: National Library of Scotland

### Source Data
- **IIIF collection tree**: `https://view.nls.uk/collections/top.json` (47 items including sub-collections)
- **Relevant sub-collections**: "Early Scottish manuscripts", "Gaelic manuscripts of Scotland", "Manuscripts containing Middle English texts"
- **Viewer**: Universal Viewer on `digital.nls.uk`
- **Est. manuscripts**: ~240 digitized medieval manuscripts

### Approach: IIIF Collection Tree Crawl (no browser needed)

Similar to Durham. The top-level collection JSON contains sub-collections that can be recursively crawled.

### Steps

#### 2a. Probe the NLS IIIF collection tree
- Fetch `https://view.nls.uk/collections/top.json`
- Identify the manuscript-related sub-collections (filter out maps, printed books, etc.)
- Crawl into sub-collections to find individual manifests
- Document manifest URL pattern and available metadata
- **Revisit**: `https://digital.nls.uk/early-manuscripts/browse/archive/235248514` lists manuscripts with IIIF manifests — investigate whether this browse archive provides a more complete or alternative source of manuscript data than the IIIF collection tree alone

#### 2b. Write NLS importer script
- `scripts/importers/nls.py`
- Crawl IIIF collection tree, filtering to manuscript sub-collections only
- Extract metadata from manifest `metadata` array
- Map NLS shelfmarks to collection names (e.g. "MS Advocates 18.7.21" -> "Advocates")
- Handle IIIF Presentation v2 multi-value labels (`@value`, `@language` fields)
- Thumbnail extraction from manifest `thumbnail` property
- Standard dry-run / --execute / --test modes

#### 2c. Run NLS import
- Dry-run to verify mapping
- Execute import
- Verify browse page and viewer

---

## Repository 3: National Library of Wales

### Source Data
- **IIIF manifests**: `https://damsssl.llgc.org.uk/iiif/2.0/{PID}/manifest.json` (per-item, Fedora PIDs)
- **Catalogue**: `https://discover.library.wales` and `https://archives.library.wales` (AtoM)
- **Exhibitions**: `https://www.library.wales/discover-learn/digital-exhibitions/manuscripts/the-middle-ages`
- **Est. manuscripts**: ~300 medieval, ongoing digitisation

### Approach: Catalogue Scraping + IIIF Manifest Fetch

Unlike Durham and NLS, NLW does not have a top-level IIIF collection endpoint. Individual Fedora PIDs must be discovered from the catalogue or exhibition pages.

### Steps

#### 3a. Probe NLW catalogue and discover PID sources
- Explore `discover.library.wales` and `archives.library.wales` for manuscript listings
- Check if AtoM REST API is publicly enabled
- Scrape the exhibitions pages (`/manuscripts/the-middle-ages`) for links to digitised items
- Identify how IIIF manifest URLs / Fedora PIDs appear in page HTML
- Document the PID extraction pattern

#### 3b. Write NLW importer script
- `scripts/importers/nlw.py`
- If AtoM API available: use it to list manuscripts with IIIF links
- Otherwise: scrape catalogue/exhibition pages to extract Fedora PIDs
- For each PID, fetch the IIIF manifest at `damsssl.llgc.org.uk/iiif/2.0/{PID}/manifest.json`
- Extract metadata from manifest (shelfmark, date, contents, language)
- Map collection names from shelfmarks (Peniarth, Llanstephan, Mostyn, etc.)
- May need Playwright if catalogue pages require JS rendering
- Handle known HTTP/HTTPS mismatch in some manifests
- Standard dry-run / --execute / --test modes

#### 3c. Run NLW import
- Dry-run to verify mapping
- Execute import
- Verify browse page and viewer

---

## Repository 4: Lambeth Palace Library (CUDL subset)

### Source Data
- **CUDL IIIF**: `https://cudl.lib.cam.ac.uk/iiif/MS-LAMBETH-{number}`
- **CUDL collection page**: `https://cudl.lib.cam.ac.uk/collections/scriptorium`
- **Note**: Only a small subset of Lambeth manuscripts are on CUDL
- **LUNA portal** (`images.lambethpalacelibrary.org.uk`): blocked by reCAPTCHA, not used

### Approach: CUDL IIIF (no scraping)

Cambridge Digital Library provides clean IIIF manifests for the Scriptorium subset.

### Steps

#### 4a. Probe CUDL Scriptorium collection
- Fetch `https://cudl.lib.cam.ac.uk/collections/scriptorium` and identify Lambeth manuscripts
- Check if CUDL has a collection-level IIIF endpoint or API listing items
- Document available manifests and their URL pattern

#### 4b. Write Lambeth importer script
- `scripts/importers/lambeth.py`
- Discover Lambeth manuscripts from CUDL (scrape collection page or use API)
- For each manuscript, fetch IIIF manifest from `cudl.lib.cam.ac.uk/iiif/`
- Extract metadata (shelfmark, date, contents)
- Map shelfmarks to collection (likely all "Lambeth Palace")
- Standard dry-run / --execute / --test modes

#### 4c. Run Lambeth import
- Dry-run to verify
- Execute import
- Verify browse page and viewer

---

## Repository 5: Cambridge University Library

### Source Data
- **IIIF collection**: `https://cudl.lib.cam.ac.uk/iiif/collection/medieval` (Western Medieval Manuscripts, 324 manifests)
- **Viewer**: `https://cudl.lib.cam.ac.uk/view/{ID}`
- **Image service**: `https://images.lib.cam.ac.uk/iiif/`
- **Est. manuscripts**: ~324 (all digitized, IIIF Presentation v2)

### Approach: IIIF Collection Crawl (no browser needed)

CUDL provides a clean IIIF Presentation 2.0 collection endpoint listing all Western Medieval Manuscripts. Each manifest contains rich metadata including classmark, title, date, language, provenance, extent, and more.

### Manifest Metadata Mapping

| CUDL Metadata Field | Compilatio Field |
|---|---|
| `Classmark` (strip "Cambridge, University Library, " prefix) | `shelfmark` |
| Derived from shelfmark prefix | `collection` |
| `Title` | `contents` |
| `Date of Creation` | `date_display` (+ parsed `date_start`/`date_end`) |
| `Language(s)` | `language` |
| `Provenance` / `Origin Place` | `provenance` |
| `Extent` | `folios` |
| First canvas image service + `/full/200,/0/default.jpg` | `thumbnail_url` |
| `https://cudl.lib.cam.ac.uk/view/{ID}` | `source_url` |

### Collection Breakdown (from IIIF IDs)

| Prefix | Collection | Count |
|---|---|---|
| MS-ADD- | Additional | ~122 |
| MS-DD- | Dd | ~50 |
| MS-FF- | Ff | ~32 |
| MS-KK- | Kk | ~29 |
| MS-II- | Ii | ~22 |
| MS-NN- | Nn | ~20 |
| MS-GG- | Gg | ~17 |
| MS-EE- | Ee | ~12 |
| MS-MM- | Mm | ~8 |
| MS-LL- | Ll | ~7 |
| MS-HH- | Hh | ~4 |
| MS-PETERBOROUGH- | Peterborough | 1 |

### Steps

#### 5a. Importer script — **Complete**
- `scripts/importers/cambridge.py`
- Fetches IIIF collection, iterates manifests, parses metadata
- Pure HTTP/JSON (no Playwright needed)
- Rate limit: 0.5s between manifest fetches
- Handles multi-part manuscripts (e.g. MS Add. 1879.1–1879.24)
- Handles deposited collections (Peterborough Cathedral)
- Standard dry-run / --execute / --test / --limit modes

#### 5b. Run CUL import
- Dry-run to verify mapping
- Execute import
- Verify browse page thumbnails and viewer deep links

### Notes
- Some manifests return HTTP 500 (importer handles gracefully, skips and continues)
- Repository registered as short_name "CUL"
- Classmark prefixes Dd–Nn correspond to CUL's traditional shelf-location system

## Common Patterns Across All Importers

Each importer follows the established pattern from `bodleian.py` and `british_library.py`:

- **CLI interface**: `--execute`, `--test`, `--verbose`, `--db` flags
- **Dry-run by default**: Shows what would be imported without modifying database
- **Test mode**: Limits to first 5 manuscripts for quick validation
- **`ensure_repository()`**: Creates repository record if needed
- **`manuscript_exists()`**: Upsert logic (insert or update)
- **Rate limiting**: Configurable delay between requests
- **Logging**: Standard Python logging with progress indicators
- **Thumbnail extraction**: From IIIF manifest `thumbnail` property

### Database Fields Mapping (Compilatio Schema)

| Compilatio Field | IIIF Manifest Source |
|---|---|
| `shelfmark` | `label` (top-level) |
| `collection` | Derived from shelfmark |
| `date_display` | `metadata` array: "Date" / "Date Range" |
| `contents` | `metadata` array: "Title" / "Description" / "Scope" |
| `language` | `metadata` array: "Language" |
| `provenance` | `metadata` array: "Provenance" / "Origin" |
| `folios` | `metadata` array: "Extent" / "Folios" |
| `iiif_manifest_url` | Manifest `@id` / `id` |
| `thumbnail_url` | `thumbnail[0].id` |
| `source_url` | Derived from catalogue URL + identifier |

---

## Results

| Repository | Manuscripts | Method | Status |
|---|---|---|---|
| Cambridge University Library | 304 | CUDL IIIF collection crawl | Complete |
| Durham University Library | 287 | IIIF collection tree crawl | Complete |
| National Library of Scotland | 104 | IIIF collection tree crawl | Complete |
| National Library of Wales | 249 | crawl4ai discovery + IIIF fetch | Complete |
| Lambeth Palace Library | 2 | CUDL IIIF subset | Complete |
| **Total new** | **946** | | |
| **Grand total** (with existing 1,891) | **2,837** | | |
