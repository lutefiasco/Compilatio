# Compilatio Project Status

## Phase 1: Foundation
**Status: Complete**

- [x] Fork Connundra repository → Compilatio
- [x] Simplified database schema (`database/schema.sql`)
- [x] Basic Starlette server (`server.py`)
- [x] Project structure established

## Phase 2: Viewer
**Status: Complete (v3 - OpenSeadragon)**

Replaced Universal Viewer with OpenSeadragon used directly. UV's internal CSS Grid layout was fundamentally incompatible with embedded use (see `docs/plans/Ongoing_Design_Issues.md`). Old UV-based viewer and test files archived to `src/archive/`.

- [x] Replace Mirador with Universal Viewer (v1-v2, archived)
- [x] Replace UV with OpenSeadragon direct integration (v3)
- [x] IIIF manifest parser (Presentation API v2 and v3)
- [x] Three-panel layout: metadata sidebar | thumbnail grid | OSD image
- [x] Resizable thumbnail panel (1-2 columns via drag handle)
- [x] Custom SVG overlay controls (zoom, rotate, fit)
- [x] Header bar with folio navigation centered over viewer pane
- [x] Manuscript selector from API (repository filter + manuscript dropdown)
- [x] Deep linking support (?ms=ID)
- [x] Dark theme with Compilatio design language

### Test URL
```
http://localhost:8000/viewer.html?manifest=https://iiif.bodleian.ox.ac.uk/iiif/manifest/03800c8f-a492-4efd-b13a-7a20c8c24b34.json
```

### Keyboard Shortcuts
- Left/Right arrows - Previous/next page
- Home/End - First/last page
- `f` - Toggle fullscreen

## Phase 3: Bodleian Import
**Status: Complete**

- [x] Create importer script (`scripts/importers/bodleian.py`)
- [x] TEI parser for Compilatio schema (shelfmark, date, contents, IIIF)
- [x] Filter to **Fully Digitized only** (excludes partial digitization)
- [x] Extract collection names from shelfmarks
- [x] Setup script for data clone (`scripts/setup_bodleian.sh`)
- [x] Clone Bodleian data and run import
- [x] Verify import results

### Import Results
- **1,713 manuscripts** imported (fully digitized only)
- Top collections: Greek (536), Laud Misc. (289), Barocci (235)

## Phase 4: Core UI
**Status: Complete**

- [x] Dark theme CSS (`src/css/styles.css`) - elegant serif design with ghosted manuscript border
- [x] Landing page with featured manuscript and repository cards (`src/index.html`)
- [x] Landing page JS fetches `/api/featured` and `/api/repositories` (`src/js/script.js`)
- [x] Browse page with repository → collection → manuscript navigation (`src/browse.html`)
- [x] Browse JS with SPA-style navigation and pagination (`src/js/browse.js`)
- [x] Viewer page with dark theme (`src/viewer.html`)
- [x] Metadata sidebar with attribution
- [x] API endpoints in server.py (`/api/repositories`, `/api/manuscripts`, `/api/featured`)
- [x] Mobile responsive with sidebar toggle

### Navigation Flow
1. Landing: Featured manuscript + repository cards with counts
2. Browse: Click repository → see collections → click collection → see manuscripts (shelfmark, title, date)
3. Viewer: Click manuscript → OpenSeadragon viewer with metadata sidebar

### Design
- **Fonts**: Cormorant Garamond (headings) + Inter (body) via Google Fonts
- **Background decoration**: Ghosted vine border from Bodleian MS. Ashmole 764 (top + right edges)
- **Color palette**: Elegant dark with ivory accent

| Element | Color |
|---------|-------|
| Background | `#1a1a1a` |
| Card/Panel | `#232323` |
| Heading text | `#f5f3ef` |
| Primary text | `#d8d8d8` |
| Secondary text | `#888` |
| Accent (ivory) | `#e8e4dc` |

### Decoration Assets
- `src/images/border-top.jpg` - Vine scrollwork from MS. Ashmole 764 (IIIF crop)
- `src/images/border-right.jpg` - Right margin decoration

## Phase 5: British Library
**Status: Complete**

See [British Library Import Plan](docs/plans/2026-01-27-British-Library-Import.md) for details.

- [x] Create BL importer script (`scripts/importers/british_library.py`)
- [x] Handle JavaScript rendering (uses Playwright)
- [x] Add digitized-only filter
- [x] Import Cotton Collection (on rabota)
- [x] Import Harley Collection (on rabota)
- [x] Import Royal Collection (on rabota)

### Import Results
- **178 manuscripts** imported (digitized only)
- Collections: Royal (81), Harley (56), Cotton (41)

## Phase 6: Polish
**Status: Partial**

- [ ] Search functionality
- [x] Responsive design (mobile sidebar, tablet layouts)
- [x] Featured manuscript rotation (random selection via `/api/featured`)
- [ ] Performance optimization

## Phase 7: Additional Repositories
**Status: Complete**

See [Additional Repositories Import Plan](docs/plans/2026-01-28-Additional-Repositories-Import.md) for full details.

Priority order (one at a time, each complete before starting next):

1. [x] **Cambridge University Library** (304 MSS) - CUDL IIIF API, no browser needed
2. [x] **Durham University Library** (287 MSS) - IIIF collection tree crawl, no browser needed
3. [x] **National Library of Scotland** (104 MSS) - IIIF collection tree crawl, no browser needed
4. [x] **National Library of Wales** (249 MSS) - crawl4ai discovery + IIIF manifest fetch
5. [x] **Lambeth Palace Library** (2 MSS) - CUDL IIIF subset only (LUNA portal is reCAPTCHA-blocked)

### Import Results
- **Cambridge University Library**: 304 manuscripts (324 manifests, 20 HTTP errors)
- **Durham University Library**: 287 manuscripts (298 manifests, 11 parse errors)
- **National Library of Scotland**: 104 manuscripts (3 collections: Gaelic 93, Early Scottish 8, Middle English 3)
- **Lambeth Palace Library**: 2 manuscripts (CUDL Scriptorium subset only)
- **National Library of Wales**: 226 manuscripts (249 discovered, 226 new inserts, 23 updates)

## Phase 8: Huntington Library
**Status: Complete**

See [Huntington Ellesmere Import Plan](docs/plans/2026-01-29-Huntington-Ellesmere-Import.md) for details.

- [x] Create Huntington importer script (`scripts/importers/huntington.py`)
- [x] CONTENTdm API integration (no browser needed)
- [x] IIIF manifest parsing
- [x] Checkpoint/resumability support
- [x] Shelfmark range filtering
- [x] Import Ellesmere collection (mssEL)
- [x] Import Huntington Manuscripts collection (mssHM 1-946)

### Import Results
- **Ellesmere (mssEL)**: 27 manuscripts
- **Huntington Manuscripts (mssHM 1-946)**: 164 manuscripts (163 new, 1 updated)

---

## Data Import Summary

All imports completed on rabota:

| Repository | Manuscripts | Collections |
|------------|-------------|-------------|
| Bodleian Library | 1,713 | Greek (536), Laud Misc. (289), Barocci (235), ... |
| Cambridge University Library | 304 | Additional (122), Dd (50), Ff (32), Kk (29), ... |
| Durham University Library | 287 | Cathedral A/B/C, Cosin, Hunter, Bamburgh, ... |
| National Library of Wales | 249 | Peniarth |
| Huntington Library | 190 | Ellesmere (27), Huntington Manuscripts (163) |
| British Library | 178 | Royal (81), Harley (56), Cotton (41) |
| National Library of Scotland | 104 | Gaelic (93), Early Scottish (8), Middle English (3) |
| Lambeth Palace Library | 2 | Lambeth Palace |
| UCLA | 115 | (various) |
| **Total** | **3,119** | |

### To Recreate Database

The `data/` directory and `database/*.db` are in `.gitignore`. To regenerate:

```bash
# Bodleian
./scripts/setup_bodleian.sh
python scripts/importers/bodleian.py --execute

# British Library (requires Playwright)
python3 -m venv .venv && source .venv/bin/activate
pip install playwright beautifulsoup4 && playwright install chromium
python scripts/importers/british_library.py --collection cotton --execute
python scripts/importers/british_library.py --collection harley --execute
python scripts/importers/british_library.py --collection royal --execute

# Cambridge University Library
python scripts/importers/cambridge.py --execute

# Durham University Library
python scripts/importers/durham.py --execute

# National Library of Scotland
python scripts/importers/nls.py --execute

# Lambeth Palace Library
python scripts/importers/lambeth.py --execute

# National Library of Wales (requires crawl4ai — Python 3.12)
python3.12 -m venv .venv-crawl4ai && source .venv-crawl4ai/bin/activate
pip install crawl4ai beautifulsoup4 && crawl4ai-setup
python scripts/importers/nlw.py --discover-only          # slow: ~40 min crawl
python scripts/importers/nlw.py --skip-discovery --execute  # fast: uses cached PIDs

# Huntington Library (no special dependencies)
python scripts/importers/huntington.py --collection EL --execute
python scripts/importers/huntington.py --collection HM --min-shelfmark 1 --max-shelfmark 946 --execute

# Start server
python server.py
```

---

## Viewer Design Issues

**Status: RESOLVED — UV replaced with OpenSeadragon**

All UV integration issues (header wrapping, white box, attribution watermark, thumbnail panel at bottom) were resolved by replacing UV entirely with OpenSeadragon used directly. See `docs/plans/Viewer_Design_v3.md` for the design document and `docs/plans/Ongoing_Design_Issues.md` for historical UV issues.

### Viewer Navigation

**Cascading dropdown selectors**: The viewer uses Repository → Collection → Manuscript dropdowns, each loading only when the previous is selected. This avoids loading all 2800+ manuscripts at once. Deep linking via `?ms=ID` remains supported and auto-populates the dropdowns.

---

## Next Steps

1. Search functionality
2. Performance optimization for large collections

## Future Repositories

- [ ] **Harvard** (Houghton Library)
- [ ] **Yale** (Beinecke Rare Book & Manuscript Library)

---

## Current Gaps

1. **Search** - No search functionality yet
2. **Additional repositories** - Phase 7 complete: CUL, Durham, NLS, NLW, Lambeth all imported

## Known Bugs

1. ~~**Duplicate BL shelfmarks**~~ — Fixed: removed "Reference (shelfmark)" from importer field mapping
2. ~~**Missing Bodleian thumbnails**~~ — Fixed: ran `scripts/fix_bodleian_thumbnails.py` to fetch correct thumbnail URLs from manifests (1,713 updated)
3. **favicon.ico 404** — No favicon configured
4. ~~**Dropdown selector shows only CUL**~~ — Fixed: viewer now uses cascading Repository → Collection → Manuscript dropdowns