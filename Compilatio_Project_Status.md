# Compilatio Project Status

## Phase 1: Foundation
**Status: Complete**

- [x] Fork Connundra repository → Compilatio
- [x] Simplified database schema (`database/schema.sql`)
- [x] Basic Starlette server (`server.py`)
- [x] Project structure established

## Phase 2: Universal Viewer Migration
**Status: In Progress**

Using Universal Viewer v4.2.1 via jsDelivr CDN.

- [x] Replace Mirador with Universal Viewer in `viewer.html`
- [x] Rewrite `src/js/viewer.js` for UV initialization and config
- [x] Update CSS for UV (selectors, containment styles)
- [ ] Test with sample IIIF manifests (Bodleian, BL)
- [ ] Verify keyboard shortcuts and deep linking work with UV

## Phase 3: Bodleian Import
**Status: Not Started**

- [ ] Adapt TEI parser for Compilatio schema
- [ ] Import from existing XML files
- [ ] Filter manuscripts (image_count >= 2)
- [ ] Extract collection names from shelfmarks

## Phase 4: Core UI
**Status: Partial**

- [x] Dark theme CSS (`src/css/styles.css`)
- [x] Landing page structure (`src/index.html`)
- [x] Viewer page structure (`src/viewer.html`)
- [x] Metadata sidebar with attribution
- [ ] Browse page (repository → collection → manuscript)
- [ ] API endpoints in server.py
- [ ] Connect UI to database

## Phase 5: British Library
**Status: Not Started**

- [ ] Adapt BL scraper/importer
- [ ] Handle bot-access restrictions
- [ ] Map BL collections (Cotton, Harley, Royal, Additional)

## Phase 6: Polish
**Status: Not Started**

- [ ] Search functionality
- [ ] Responsive design refinement
- [ ] Featured manuscript rotation
- [ ] Performance optimization

## Deferred

- Cambridge University Library importer
- Huntington Library importer

---

## Current Gaps

1. **UV integration needs testing** - Universal Viewer v4.2.1 integrated, needs live test with manifests
2. **No data importers** - Scripts for Bodleian/BL not yet created
3. **No API routes** - server.py serves static files only
4. **No database** - schema exists but no `compilatio.db`

## Next Steps

1. Test UV migration with sample IIIF manifests
2. Create `scripts/importers/bodleian.py`
3. Add API endpoints to `server.py` (`/api/manuscripts`, `/api/repositories`)
4. Create browse page with collection navigation
5. Populate database with Bodleian TEI data
