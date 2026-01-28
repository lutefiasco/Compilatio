# Additional Repositories Import Plan

## Overview

Integrate four new manuscript repositories into Compilatio, prioritised by technical feasibility. Each repository is implemented as an independent importer script following the existing pattern (`scripts/importers/*.py`), with dry-run and execute modes.

**Priority order:**
1. Durham University Library (best IIIF infrastructure)
2. National Library of Scotland (clean IIIF collection tree)
3. National Library of Wales (large IIIF estate, PID discovery needed)
4. Lambeth Palace Library (CUDL subset only)

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

## Expected Results

| Repository | Est. Manuscripts | Method |
|---|---|---|
| Durham University Library | ~300 | IIIF collection tree crawl |
| National Library of Scotland | ~240 | IIIF collection tree crawl |
| National Library of Wales | ~200-300 | Catalogue scrape + IIIF fetch |
| Lambeth Palace Library | ~20-50 | CUDL IIIF subset |
| **Total new** | **~760-890** | |
| **Grand total** (with existing 1,891) | **~2,650-2,780** | |
