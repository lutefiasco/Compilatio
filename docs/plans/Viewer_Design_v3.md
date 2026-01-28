# Viewer Design v3: OpenSeadragon Direct

## Approach

Replace Universal Viewer with OpenSeadragon used directly. UV's internal CSS Grid layout is fundamentally incompatible with embedded use (thumbnails appear at bottom, not as left sidebar - see Issue 8 in Ongoing_Design_Issues.md). Digital Bodleian itself uses `openseadragon-canvas` and `splitpanes_pane` divs, suggesting they build around OSD rather than relying on UV's panel system.

## Reference: Digital Bodleian Layout

From screenshot analysis (Jan 28 2026):
```
┌─────────────────────────────────────────────────────────┐
│ Site header: Logo, Search, Browse, About, Login         │
├─────────────────────────────────────────────────────────┤
│ Manuscript title: "Balliol College MS 238E"             │
├─────────────────────────────────────────────────────────┤
│ ⏮ ◀ [fol. 1r    ] ▶ ⏭  Image 5 of 336  □ ⊞ ▦ ⛶     │
├──────────┬─┬────────────────────────────────────────────┤
│ Thumb    │↔│                                            │
│ Grid     │ │     Deep zoom manuscript image             │
│ (2-col)  │ │                                            │
│          │ │     [OSD zoom/rotate overlaid top-left]    │
│ labeled  │ │                                            │
│ folios   │ │                                            │
├──────────┴─┴────────────────────────────────────────────┤
│ (no visible footer in screenshot)                       │
└─────────────────────────────────────────────────────────┘
```

## Compilatio Target Layout

Three-panel layout: Compilatio metadata sidebar + thumbnail grid + OSD image viewer.
Thumbnail panel is resizable via drag handle; grid switches between 1 and 2 columns based on panel width.

```
┌─────────────────────────────────────────────────────────┐
│ Compilatio                              ← Back to Browse│
├─────────────────────────────────────────────────────────┤
│ [All repositories ▼] [-- Choose manuscript -- ▼] (N)    │
├─────────────────────────────────────────────────────────┤
│ ⏮ ◀ [folio input ] ▶ ⏭  Image X of Y     □ ⊞ ⛶      │
├──────┬──────────┬─┬─────────────────────────────────────┤
│ Meta │ Thumbnail│↔│                                     │
│ data │ Grid     │ │     OpenSeadragon deep zoom image   │
│      │ (1-2col) │ │                                     │
│ Shelf│ Click to │ │     [zoom/rotate overlaid top-left] │
│ Repo │ navigate │ │                                     │
│ Date │          │ │                                     │
│      │ Resizable│ │                                     │
│ [src]│ width    │ │                                     │
└──────┴──────────┴─┴─────────────────────────────────────┘
```

**Metadata sidebar** (fixed 200px): Shelfmark, repository, date, physical description, contents, provenance, source link.
**Thumbnail panel** (resizable 90-400px): Uses `grid-template-columns: repeat(auto-fill, minmax(80px, 1fr))` to automatically switch between 1 and 2 columns based on available width.
**Divider** (6px): Draggable handle with visual indicator.

---

## Implementation Phases

### Phase 1: Core Viewer (Viewer_Test2a.html)
**Status: COMPLETE**

- [x] OpenSeadragon deep zoom viewer
- [x] IIIF manifest parser (Presentation API v2 and v3)
- [x] Thumbnail sidebar with 2-column grid
- [x] Click thumbnail to navigate
- [x] Current page highlight in thumbnail grid
- [x] Header bar with prev/next/first/last navigation
- [x] Folio text input with jump-to
- [x] "Image X of Y" counter
- [x] Resizable divider between thumbnails and image
- [x] Manuscript selector from Compilatio API
- [x] Dark theme matching Compilatio design
- [x] Keyboard shortcuts (left/right arrows, Home/End)
- [x] OSD overlay controls (zoom, rotate, home)

### Phase 2: Enhanced Controls
**Status: PENDING**

- [ ] View mode toggles (single page, book opening)
- [ ] Gallery view
- [ ] Fullscreen mode
- [ ] Footer bar with zoom/rotate buttons
- [ ] Thumbnail lazy loading for large manifests

### Phase 3: Compilatio Integration
**Status: COMPLETE (merged into Phase 1)**

- [x] Metadata panel with physical description, contents, provenance, source link
- [x] URL deep linking (?ms=ID)
- [x] Back to browse link
- [x] Manuscript selector from API

### Phase 4: Production Replacement
**Status: COMPLETE**

- [x] Promoted Viewer_Test2a.html to src/viewer.html
- [x] Archived old UV viewer and all test files to src/archive/
- [x] Updated CLAUDE.md and project status docs
- [ ] Test with all repositories (Bodleian, BL, CUL, Durham, NLS, Lambeth)
- [ ] Performance testing with large manifests (300+ canvases)
- [ ] Mobile responsive layout

---

## Technical Decisions

### OpenSeadragon Configuration
- **CDN**: `https://cdn.jsdelivr.net/npm/openseadragon@4.1.1/build/openseadragon/openseadragon.min.js`
- **Tile source**: IIIF Image API info.json URLs extracted from manifest
- **Controls**: Custom SVG overlay buttons (zoom in/out, home, rotate) - vertically stacked at top-left of image
- **No navigator minimap** (matches Bodleian, saves space)

### IIIF Manifest Parsing
Both IIIF Presentation API v2 and v3 must be supported:

**v2 canvas structure:**
```
sequences[0].canvases[i].images[0].resource.service['@id'] → image service URL
```

**v3 canvas structure:**
```
items[i].items[0].items[0].body.service[0].id → image service URL
```

Thumbnail URLs: Use canvas `thumbnail` if available, otherwise construct from image service: `{service_id}/full/,120/0/default.jpg`

### Resizable Divider
Vanilla JS mousedown/mousemove/mouseup drag handler. No external library needed. Min width 120px, max width 400px.

### Why Not UV
See `Ongoing_Design_Issues.md` Issue 8 for full analysis. Summary: UV v4's internal CSS Grid layout uses `window.innerWidth` for breakpoints and JavaScript-based height calculations that break when UV is embedded in an external layout. The thumbnail panel appears at the bottom instead of as a left sidebar. This is a fundamental architectural conflict, not a CSS tweaking problem.

---

## Issues and Solutions Log

### Phase 1 Issues

| # | Issue | Status | Notes |
|---|-------|--------|-------|
| 1 | CORS on manifest fetch | MONITORING | Major IIIF providers (Bodleian, BL, NLS, CUL) allow CORS. If issues arise, will need server-side proxy. |
| 2 | OSD default button images dated look | RESOLVED | Replaced with custom SVG overlay buttons, vertically stacked at top-left of image. |
| 3 | Large manifests (300+ canvases) | DEFERRED | All thumbnails loaded eagerly. Add IntersectionObserver lazy loading in Phase 2. |
| 4 | Book opening (2-up) view | DEFERRED | OSD doesn't natively support side-by-side. Requires custom multi-image arrangement. Phase 2. |
| 5 | Manifest label formats vary | HANDLED | Parser handles string, {`@value`}, and {lang: [text]} formats. |

---

## Files

| File | Purpose |
|------|---------|
| `src/viewer.html` | Production OpenSeadragon viewer (self-contained) |
| `src/archive/` | Old UV-based viewer and test files |
| `docs/plans/Viewer_Design_v3.md` | This design document |
| `docs/plans/Ongoing_Design_Issues.md` | UV integration issues (historical reference) |
