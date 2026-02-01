# Ongoing Design Issues

**Status: RESOLVED** — UV replaced with OpenSeadragon direct integration. See `Viewer_Design_v3.md`.

---

## Historical Context (Archived)

This document describes UV integration issues that led to replacing Universal Viewer with OpenSeadragon.

## Original Goal

Make Compilatio's viewer page match the look and feel of the Digital Bodleian viewer (https://digital.bodleian.ox.ac.uk), while keeping Compilatio's own manuscript selector. Both sites use Universal Viewer v4.

## Reference

**Digital Bodleian viewer provides** (from screenshot analysis, Jan 28 2026):
- **Left thumbnail panel**: 2-column grid of clickable thumbnails with folio labels (e.g. "Inside Upper...", "fol. 1r", "fol. 2r")
- **Resizable panel divider**: Drag handle between thumbnail panel and main image area
- **Single-line header bar**: `|< < [fol. 1r text input] > >| Image 5 of 336` — all on one line
- **View mode buttons** on right side of header: single page, book view, gallery, fullscreen
- **OpenSeadragon controls** overlaid on image: vertical stack at top-left with zoom in, zoom out, home, rotate buttons
- **Footer bar**: zoom controls (zoom in, zoom out, rotate, fit-to-width, fullscreen)
- **No attribution watermark** over the image
- **No metadata sidebar** on the right — just thumbnails on left, image on right
- **Clean dark theme** on viewer chrome

**Compilatio should have:**
- Thumbnail panel with 2-column vertically-scrolling grid (like Bodleian)
- Header bar with folio text input, page nav arrows, view mode controls — all on one line
- Footer bar with zoom controls
- OpenSeadragon overlay controls (zoom, rotate) visible on the image
- No attribution watermark over the image
- Compilatio's own metadata (shelfmark, date, contents) accessible but not competing with the viewer
- Compact Compilatio header and manuscript selector above the viewer
- Resizable panel divider between thumbnails and image
- Viewer fills most of the viewport

---

## Current Status: Fundamental UV Layout Conflict (Jan 28 2026)

### The Core Problem

After two rounds of testing (6 test files), we have identified a **fundamental architectural conflict** between UV v4's internal layout system and Compilatio's page layout. This is not a CSS tweaking problem — it's a design-level incompatibility.

### What We Solved

| Issue | Status | Solution |
|-------|--------|----------|
| Header bar wrapping | RESOLVED | Convert UV's float-based `.centerOptions` to flexbox |
| White box artifact | RESOLVED | Correct config (`requiredStatementEnabled: false`) + dark backgrounds on UV containers |
| Attribution watermark | RESOLVED | `requiredStatementEnabled: false` under `modules.openSeadragonCenterPanel.options` (not the non-existent `attributionEnabled`) |
| Stray thumbnail minimap | RESOLVED | CSS hiding `.navigator`, `.openseadragon-navigator` |
| Compact header/selector | RESOLVED | Single-line flex layout, reduced padding |

### What We Cannot Solve Without Major Workarounds

**Issue 8: UV's Internal Panel Layout Breaks When Embedded in External Grid**

When `leftPanelEnabled: true` is set, UV's thumbnail panel appears at the **bottom** of the viewer instead of as a left sidebar. This was confirmed in the Test 1a screenshot.

**Root cause** (from UV v4 source code analysis):

UV v4 uses a **CSS Grid layout** on its internal `.mainPanel` element:
```css
.mainPanel {
    display: grid;
    grid-template-columns:
        [left] var(--uv-grid-left-width)
        [center] var(--uv-grid-main-width)
        [right] var(--uv-grid-right-width);
    grid-template-areas: "left center right";
}
```

This grid layout **only activates at `@media (min-width: 768px)`** — but critically, UV uses `window.innerWidth` for its metric breakpoints, NOT the container width. So even though the UV container may have plenty of space, UV's CSS media queries are based on the browser window width.

The real problem is that Compilatio's CSS overrides interfere with UV's internal sizing:

1. **`#uv-viewer > div { width: 100% !important; height: 100% !important; position: relative !important; }`** — This targets UV's wrapper div (created by `Init.ts`) and conflicts with UV's own positioning context. The `.uv` element is two levels deep (`#uv-viewer > div > div.uv`), and forcing `position: relative` on the intermediate div disrupts UV's layout calculations.

2. **UV's `Shell.ts` calculates `.mainPanel` height via JavaScript**: It reads `this.$element.height()` and subtracts header/footer heights. If the container doesn't have a concrete pixel height when UV initializes (e.g., `height: 100%` that resolves to 0), `.mainPanel` gets height 0 and panels stack vertically.

3. **UV uses `window.addEventListener("resize")`, not ResizeObserver** — If the container changes size (e.g., Compilatio sidebar collapses), UV doesn't know. You must manually call `uvInstance.resize()`.

4. **UV's panel DOM structure** is: `.uv > .headerPanel + .mainPanel > (.leftPanel + .centerPanel + .rightPanel) + .footerPanel`. The panels are children of `.mainPanel`, not siblings. External CSS that targets `#uv-viewer > div` hits the wrong level.

**Why fixing this is fragile**: Even if we get the panels positioned correctly by carefully avoiding CSS conflicts and ensuring pixel heights, UV's layout is JavaScript-driven. Any change to Compilatio's page structure, viewport size handling, or initialization timing can re-break it. We'd be maintaining a fragile integration indefinitely.

---

## Options for Next Steps

### Option A: Fix UV Integration (One More Attempt)

Try to make UV's internal grid work by:
1. Removing all `#uv-viewer > div` CSS overrides — let UV size its own wrapper
2. Setting a concrete pixel height on `#uv-viewer` before calling `UV.init()` (via JS: `uvViewer.style.height = (window.innerHeight - 120) + 'px'`)
3. Calling `uvInstance.resize()` after initialization and on window resize
4. Keeping the float-to-flex header fix and dark theme CSS

**Pros**: Minimal new code, builds on existing work
**Cons**: Fragile, still fighting UV's assumptions, may break on different screen sizes or when Compilatio's layout changes

### Option B: OpenSeadragon Direct (Recommended)

Replace UV with OpenSeadragon used directly. Build a custom viewer UI that matches the Bodleian layout exactly.

**What OSD provides natively:**
- Deep zoom image display with IIIF Image API support
- Zoom in/out/home controls (overlay buttons)
- Pan and pinch-zoom
- Rotation
- Multi-image sequences
- Navigator minimap (optional)

**What we'd build (~200-300 lines of JS):**
- IIIF Manifest parser (manifests are straightforward JSON — extract canvas list, image URLs, labels)
- Thumbnail sidebar with 2-column grid, vertical scroll, click-to-navigate
- Folio selector text input + "Image X of Y" counter
- Navigation arrows (first, prev, next, last)
- View mode toggle (single page vs. book opening)
- Resizable sidebar (CSS resize or a simple drag handle — ~30 lines)

**Pros:**
- Full control over layout — our CSS grid, our DOM, no conflicts
- Matches Compilatio's vanilla JS stack perfectly
- OSD is lightweight (~200KB) vs UV (~1.5MB)
- No more config guessing or CSS override battles
- Dark theme is trivial (it's our own HTML/CSS)
- Can match Bodleian layout pixel-for-pixel

**Cons:**
- Upfront implementation work
- Need to handle IIIF Presentation API v2 and v3 manifest formats
- Gallery view mode would need custom implementation

### Option C: Mirador 3

Replace UV with Mirador 3, a React-based IIIF viewer with plugin architecture and theming.

**Pros:**
- Full-featured IIIF viewer with thumbnail panel, metadata, zoom, etc.
- Good theming/customization support via Material UI
- Plugin system for extensibility
- Was used in the original Connundra project this was forked from

**Cons:**
- React dependency — adds significant bundle size and complexity to a vanilla JS project
- Embedding React in a non-React app requires careful integration
- Mirador's opinions about layout may create similar (though likely fewer) conflicts
- Heavier than both UV and OSD

### Option D: Custom UV Build

Fork UV v4, modify the source CSS and JS to work correctly when embedded in an external layout.

**Pros:** Complete control over UV's behavior
**Cons:** Maintenance burden — must merge upstream UV updates, requires understanding UV's full codebase

### Important Observation: Digital Bodleian May Not Use UV's Panel System

The user observed that Digital Bodleian's viewer page has `<div>` elements with "splitpanes" classes. This suggests that Digital Bodleian may **NOT** be using UV's built-in left/right panel system at all. Instead, they likely:

1. Use UV only for its **center panel** (OpenSeadragon viewer + header bar + footer)
2. Build their own thumbnail sidebar **outside** UV, in a splitpane container
3. Use a splitpane library (e.g., [splitpanes](https://antoniandre.github.io/splitpanes/) for Vue, or a vanilla JS equivalent) to provide the resizable divider between thumbnails and the UV viewer

This would explain:
- Why their layout works cleanly — they're not fighting UV's internal CSS Grid
- Why they have a proper resizable handle — it's their own splitpane, not UV's
- Why UV's `leftPanelEnabled` would be set to `false` in their config — they replaced it

**If this is the case**, the correct approach for Compilatio would be similar: use UV (or OSD directly) for the image viewer only, and build the thumbnail sidebar and resizable layout externally. This reinforces Options B and E below.

### Option E: UV Center Panel Only + External Thumbnail Sidebar (Bodleian Approach)

Keep UV but disable its left panel. Build the thumbnail sidebar outside UV using a splitpane layout, parsing the IIIF manifest to generate thumbnail URLs and handling click-to-navigate by calling UV's `set()` method.

**Pros:**
- Keeps UV for what it's good at (OSD + header + footer)
- Full control over thumbnail layout and resize behavior
- Matches what Digital Bodleian appears to do
- Less new code than Option B (reuse UV for viewer chrome)

**Cons:**
- Still dependent on UV for header bar (float wrapping fix still needed)
- Still need to parse IIIF manifests for thumbnail URLs
- UV's `set()` API for navigating to a specific canvas may be limited

### Recommendation

**Option B (OpenSeadragon direct)** or **Option E (UV center only + external thumbnails)** are the recommended paths. The viewer layout issues stem from UV being designed as a standalone full-viewport application. Every fix we've attempted for panel layout has revealed another layer of UV's assumptions about owning the entire page.

Option E is the lower-risk path — keep UV for the viewer chrome (header bar, footer, OSD integration) but handle the thumbnail panel externally, similar to what Digital Bodleian does with splitpanes. Option B gives the most control but requires more upfront work.

---

## Round 2 Issues (identified Jan 28 2026)

### Issue 4: No Thumbnail Panel

**Problem**: UV's left panel (with thumbnails) was disabled in Round 1 to fix the duplicate sidebar issue. But the Bodleian viewer has a left thumbnail panel that is essential for navigation.

**Root cause**: We set `leftPanelEnabled: false` to avoid UV's left panel conflicting with Compilatio's metadata sidebar. But this also removed the thumbnail strip.

**What we tried in Round 2:**
- Re-enabled `leftPanelEnabled: true` with `contentLeftPanel.options.panelOpen: true`
- Set `defaultToTreeEnabled: false` to show thumbnails instead of tree
- Result: thumbnails appeared at the BOTTOM of the viewer, not as a left sidebar (see Issue 8 above)

### Issue 5: Missing OpenSeadragon Overlay Controls

**Problem**: Zoom in, zoom out, home, and rotate buttons that normally overlay the image (top-left vertical stack) are not visible.

**What we tried in Round 2:**
- Set `autoHideControls: false`, `showHomeControl: true`, `controlsFadeAfterInactive: false`
- Result: OSD controls DID appear correctly in Test 1a screenshot (visible at top-left of image). This fix works.

### Issue 6: Folio Text Input Not Functional

**Problem**: No text input box where you can type a folio number to jump to it.

**What we tried in Round 2:**
- Added explicit CSS for `.searchText` and `.autocompleteText` inputs (width: 80px, dark styling)
- Not yet confirmed whether the input accepts typed text

### Issue 7: Panel Resize Handles

**Problem**: Bodleian has draggable resize handles between panels.

**Status**: UV provides these natively when `leftPanelEnabled: true`, but since the panel layout is broken (Issue 8), resize handles are moot until panel positioning is fixed.

### Issue 8: UV Panel Layout Breaks in Embedded Container — BLOCKING

**Problem**: UV's thumbnail panel appears at the bottom instead of as a left sidebar.

**Root cause**: UV's internal CSS Grid on `.mainPanel` conflicts with Compilatio's external CSS Grid. UV's JavaScript-based height calculation in `Shell.ts` returns incorrect values when the container uses `height: 100%` instead of concrete pixel heights. See "Current Status" section above for full analysis.

---

## Round 1 Issues (status after Test1/Test2/Test3)

### Issue 1: UV Header Bar Wrapping — RESOLVED

**Root cause**: UV uses `float: left` for all children of `.centerOptions`.

**Fix**: Convert to flexbox:
```css
#uv-viewer .headerPanel .centerOptions {
    display: flex !important;
    align-items: center !important;
    flex-wrap: nowrap !important;
    position: static !important;
}
#uv-viewer .headerPanel .centerOptions > * {
    float: none !important;
    flex-shrink: 0 !important;
}
```

### Issue 2: White Box Artifact — RESOLVED

**Fix**: `requiredStatementEnabled: false` + dark backgrounds on `.centerPanel`, `.overlays`, `.attribution`

### Issue 3: Attribution Watermark — RESOLVED

**Fix**: `requiredStatementEnabled: false`, `titleEnabled: false`, `subtitleEnabled: false` under `modules.openSeadragonCenterPanel.options`

---

## Other Known Issues (Not Design)

### Duplicate Shelfmarks in British Library Data
- BL manuscripts show doubled shelfmarks: "Royal MS 1 D III\n\nRoyal MS 1 D III"
- Data import bug in `scripts/importers/british_library.py`

### Missing Thumbnails in Browse Page
- All thumbnails display "No image" placeholder in browse manuscript grid

### favicon.ico 404
- No favicon configured

---

## Architecture Notes

### Key Discovery: UV v4 Internal DOM Structure

**Header panel** (from `PagingHeaderPanel.ts`) uses float-based layout:
```
.headerPanel
  .options (40px height)
    .centerOptions (position: absolute)
      .prevOptions (float: left) → |< < buttons
      .mode (float: left) → Image/Page radio
      .search (float: left) → text input + "of X" + Go button
      .nextOptions (float: left) → > >| buttons
    .rightOptions (float: right)
      .pagingToggleButtons → 1-up/2-up buttons
      gallery button
```

**Main panel** (from `Shell.ts` and `styles.less`) uses CSS Grid at md+ breakpoints:
```
.uv (position: relative)
  .headerPanel
  .mainPanel (display: grid at @media min-width: 768px)
    grid-template-columns:
      [left] var(--uv-grid-left-width)        → 30px collapsed, 271px open
      [center] var(--uv-grid-main-width)       → minmax(0, 1fr)
      [right] var(--uv-grid-right-width)       → 30px collapsed, 271px open
    grid-template-areas: "left center right"
    .leftPanel (grid-area: left)
    .centerPanel (grid-area: center)
    .rightPanel (grid-area: right)
  .footerPanel
  .mobileFooterPanel
  .overlays
```

**Shell.ts `resize()` calculates mainPanel height via JavaScript:**
```javascript
const mainHeight =
    this.$element.height() -
    parseInt(this.$mainPanel.css("paddingTop")) -
    (isVisible(this.$headerPanel) ? this.$headerPanel.height() : 0) -
    (isVisible(this.$footerPanel) ? this.$footerPanel.height() : 0) -
    (isVisible(this.$mobileFooterPanel) ? this.$mobileFooterPanel.height() : 0);
this.$mainPanel.height(mainHeight);
```

**Init.ts container setup:**
```javascript
const resize = () => {
    parent.style.width = container.offsetWidth + "px";
    parent.style.height = container.offsetHeight + "px";
    uv.resize();
};
window.addEventListener("resize", resize);  // window only, no ResizeObserver
```

### Key Discovery: Config Structure

**Critical**: `attributionEnabled` does NOT exist in UV v4. Use `requiredStatementEnabled` under `modules.openSeadragonCenterPanel.options`.

**Critical**: `contentLeftPanel` and `contentRightPanel` go under `modules`, NOT under top-level `options`.

### Current Production Config (viewer.js) — NEEDS UPDATE

```javascript
// BROKEN - these options are wrong or misplaced:
attributionEnabled: false,          // does not exist in UV v4
contentLeftPanel: { panelOpen: false },  // wrong location (should be under modules)
contentRightPanel: { panelOpen: false }  // wrong location (should be under modules)
```

### Test Files Created

**Round 1:**

| File | Approach | Result |
|------|----------|--------|
| `Viewer_Test1.html` | Aggressive CSS overrides (float→flex header) | Best header bar, no white box, no watermark |
| `Viewer_Test2.html` | External uv-config.json | Config alone doesn't fix float wrapping |
| `Viewer_Test3.html` | No sidebar, full width | Full width helps but still needs flex CSS |

**Round 2:**

| File | Approach | Result |
|------|----------|--------|
| `Viewer_Test1a.html` | Compilatio sidebar + UV thumbnails + image | Thumbnails appear at BOTTOM, not as left sidebar (Issue 8) |
| `Viewer_Test1b.html` | Bodleian-style (no Compilatio sidebar) | Not yet tested |
| `Viewer_Test1c.html` | Compilatio sidebar + collapsed UV thumbnails | Not yet tested |

**Supporting files:**
- `uv-config.json` — External UV config file (used by Test 2)
