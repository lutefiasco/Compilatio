# Compilatio Project Status

## Phase 1: Foundation
**Status: Complete**

- [x] Fork Connundra repository → Compilatio
- [x] Simplified database schema (`database/schema.sql`)
- [x] Basic Starlette server (`server.py`)
- [x] Project structure established

## Phase 2: Universal Viewer Migration
**Status: Complete**

Using Universal Viewer v4.2.1 via jsDelivr CDN.

- [x] Replace Mirador with Universal Viewer in `viewer.html`
- [x] Rewrite `src/js/viewer.js` for UV initialization and config
- [x] Update CSS for UV (selectors, containment styles)
- [x] Test with sample IIIF manifests (Bodleian)
- [x] Verify keyboard shortcuts and deep linking work with UV
- [x] Add standalone mode for direct manifest URL loading

### Test URL
```
http://localhost:8000/viewer.html?manifest=https://iiif.bodleian.ox.ac.uk/iiif/manifest/03800c8f-a492-4efd-b13a-7a20c8c24b34.json
```

### Keyboard Shortcuts
- `i` - Show info panel
- `[` - Toggle sidebar

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
2. Browse: Click repository → see collections → click collection → see manuscripts
3. Viewer: Click manuscript → Universal Viewer with metadata sidebar

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
**Status: In Progress**

See [British Library Import Plan](docs/plans/2026-01-27-British-Library-Import.md) for details.

- [x] Create BL importer script (`scripts/importers/british_library.py`)
- [x] Handle JavaScript rendering (uses Playwright)
- [x] Add digitized-only filter
- [ ] Import Cotton Collection (on rabota)
- [ ] Import Harley Collection (on rabota)
- [ ] Import Royal Collection (on rabota)

## Phase 6: Polish
**Status: Partial**

- [ ] Search functionality
- [x] Responsive design (mobile sidebar, tablet layouts)
- [x] Featured manuscript rotation (random selection via `/api/featured`)
- [ ] Performance optimization

## Deferred

- Cambridge University Library importer
- Huntington Library importer

---

## Things to Do on Rabota

After pushing to git and pulling on rabota:

```bash
# 1. Clone Bodleian TEI data and initialize database
./scripts/setup_bodleian.sh

# 2. Import fully digitized Bodleian manuscripts (1,713 manuscripts)
python scripts/importers/bodleian.py --execute

# 3. Setup for British Library import
python3 -m venv .venv
source .venv/bin/activate
pip install playwright beautifulsoup4
playwright install chromium

# 4. Import British Library collections (digitized only)
python scripts/importers/british_library.py --collection cotton --execute
python scripts/importers/british_library.py --collection harley --execute
python scripts/importers/british_library.py --collection royal --execute

# 5. Start the server
python server.py

# 6. Visit http://localhost:8000/ to see the dark-themed UI
```

The `data/` directory and `database/*.db` are in `.gitignore` - they must be generated on rabota.

---

## Next Steps

1. Run British Library imports on rabota (Cotton, Harley, Royal)
2. Search functionality
3. Performance optimization for large collections

---

## Current Gaps

1. **British Library** - Importer ready, needs to run on rabota
2. **Search** - No search functionality yet
