# Ongoing Design Issues

## Goal

Make Compilatio's viewer page match the look and feel of the Digital Bodleian viewer (https://digital.bodleian.ox.ac.uk), while keeping Compilatio's own sidebar and manuscript selector. Both sites use Universal Viewer v4.

## Reference

**Digital Bodleian viewer provides:**
- Thumbnail strip on the left
- Folio/page selector dropdown in header bar (e.g. "upper board", "Image 1 of 336")
- Navigation arrows (|< < > >|) on a single line with the selector
- View mode buttons (single page, book view, gallery)
- Zoom controls in footer
- Metadata panel on the right
- Clean single-line header bar, nothing wraps

**Compilatio should have:**
- Compilatio's own metadata sidebar on the left (instead of UV thumbnails)
- UV header bar with folio selector, page nav, view controls — all on one line
- UV footer bar with zoom controls
- No attribution watermark over the image
- No stray thumbnail minimap
- No white box artifact
- Compact Compilatio header and manuscript selector above the viewer
- Viewer fills most of the viewport

---

## Current Issues

### Issue 1: UV Header Bar Wrapping (div.search)

**Problem**: UV's header panel renders its controls inside a `div.search` element. The content wraps across 4 lines:
1. Left navigation arrows
2. Folio selector bar (e.g. "188Go")
3. Right navigation arrows
4. View/rendering controls

**What we tried:**
1. CSS `display: flex; flex-wrap: nowrap` on `#uv-viewer .search` — did not prevent wrapping
2. CSS `white-space: nowrap; overflow: hidden` on `.search` — did not work
3. CSS on `#uv-viewer [class*="headerPanel"]` with max-height and flex — did not work

**Possible next steps:**
- Inspect the actual DOM structure more carefully in Safari DevTools to find exact element hierarchy inside `.search`
- UV may use absolute positioning or fixed widths internally that override flex layout
- Try `#uv-viewer .search * { display: inline !important; float: none !important; }` to flatten layout
- Check if UV v4 applies inline styles that override CSS class rules (use `!important` on all properties)
- Check if `.search` has child divs that each contain a group of controls — may need to target those specifically
- Consider whether the issue is the viewer panel width — if the UV container is too narrow, the header will wrap regardless of CSS. The sidebar (260px) reduces available width
- Try reducing sidebar width or making it collapsible by default on load

### Issue 2: White Box Artifact

**Problem**: A white/light rectangle appears in the upper area of the viewer. Inspect Element shows it as the `body` tag.

**What we tried:**
1. CSS `body:has(.viewer-container)::before, body:has(.viewer-container)::after { display: none }` — `:has()` not supported in user's Safari version
2. Inline `<style>` in viewer.html: `body::before, body::after { display: none !important; }` — white box returned after this change

**Analysis:**
- The ghosted border decoration uses `body::before` (top) and `body::after` (right) with `filter: invert(0.72) sepia(0.55)` and fixed positioning
- The inline style in viewer.html should hide these, but the white box persists
- This suggests the white box may NOT be the pseudo-elements, despite initially appearing to be
- It could be:
  - UV rendering an empty panel or container with a white/light background
  - A UV iframe or shadow DOM element
  - An OpenSeadragon container before an image loads
  - A CSS stacking context issue where a UV element has `background: white` by default

**Possible next steps:**
- User needs to inspect the white box more carefully: right-click directly on the white area → Inspect Element, then walk up the DOM tree to find which element has the white background
- Check if UV uses an iframe (would not be targetable with parent CSS)
- Add blanket dark background: `#uv-viewer, #uv-viewer * { background-color: #141414 !important; }` (aggressive, may break UV controls)
- Try `#uv-viewer > div { background: #141414 !important; }`
- Check if the white box appears before a manuscript is loaded (could be the placeholder state)

### Issue 3: Attribution Watermark Still Showing

**Problem**: Large text like "Bodleian Library MS. Ashmole 304" overlays the manuscript image as a watermark.

**What we tried:**
1. UV config `attributionEnabled: false` — did not suppress the watermark
2. CSS hiding `[class*="overlay"]`, `[class*="attribution"]` — partially effective but watermark persists in some views

**Analysis:**
- UV v4 may use different option names than documented
- The watermark text may come from the IIIF manifest's `label` field, not the `attribution` field
- UV may render this as part of the center panel, not as a separate overlay element

**Possible next steps:**
- Check UV v4 source code on GitHub for the actual config option names: https://github.com/UniversalViewer/universalviewer
- Try these UV config options: `pagingEnabled: false`, `preserveViewport: true`
- Try `modules: { footerPanel: { options: { ... } } }` style nested config
- Inspect the watermark element in DevTools to get its exact class/ID
- May need to target it with a very specific CSS selector based on the actual DOM
- Check if Digital Bodleian's UV instance also shows this watermark (it appears not to — they may have a custom UV build or specific config)

---

## Completed Fixes

### Fixed: Duplicate Sidebars
- Set `leftPanelEnabled: false` in UV config
- UV's built-in left panel (with its own INFO/CONTENTS tabs) no longer appears

### Fixed: UV Header Panel (disabled → re-enabled)
- Initially disabled `headerPanelEnabled` to reduce clutter
- Re-enabled it because the folio selector and page navigation are essential
- Header panel now shows but has wrapping issues (see Issue 1)

### Fixed: Stray Thumbnail Minimap
- CSS `#uv-viewer .navigator, .openseadragon-navigator { display: none }` works
- OpenSeadragon's overview minimap in bottom-right no longer shows

### Fixed: Compact Compilatio Header
- Replaced multi-line header (h1 + subtitle + nav) with single-line flex layout
- Title "Compilatio" and "← Browse" on one line

### Fixed: Compact Selector Bar
- Reduced padding from 1.25rem to 0.5rem
- Removed labels (using aria-label instead)
- Removed helper text
- Selector bar is now thinner

### Fixed: Viewer Height
- Changed `height: calc(100vh - 280px)` to `calc(100vh - 140px)`
- Viewer fills more of the viewport

---

## Other Known Issues (Not Design)

### Duplicate Shelfmarks in British Library Data
- BL manuscripts show doubled shelfmarks: "Royal MS 1 D III\n\nRoyal MS 1 D III"
- This is a data import bug in `scripts/importers/british_library.py`
- Needs fix in the importer, then re-import

### Missing Thumbnails in Browse Page
- All thumbnails display "No image" placeholder in browse manuscript grid
- May be a data issue (thumbnail_url null or invalid) or an image loading problem

### favicon.ico 404
- No favicon configured, causes 404 in console

---

## Architecture Notes

### Current UV Configuration (viewer.js)
```javascript
uvInstance.on('configure', function({ config, cb }) {
    cb({
        options: {
            headerPanelEnabled: true,
            footerPanelEnabled: true,
            leftPanelEnabled: false,
            rightPanelEnabled: false,
            attributionEnabled: false,
            contentLeftPanel: { panelOpen: false },
            contentRightPanel: { panelOpen: false }
        }
    });
});
```

### Current UV CSS Overrides (styles.css)
```css
#uv-viewer [class*="overlay"], [class*="Overlay"],
  [class*="attribution"], [class*="Attribution"] { display: none }
#uv-viewer .navigator, .openseadragon-navigator { display: none }
#uv-viewer [class*="credit"], [class*="rights"] { display: none }
#uv-viewer [class*="headerPanel"] { background: #1a1a1a }
#uv-viewer .search { display: flex; flex-wrap: nowrap }
#uv-viewer [class*="footerPanel"] { background: #1a1a1a }
```

### Viewer Page Inline Style (viewer.html)
```css
body::before, body::after { display: none !important; }
```

### Possible Alternative Approaches

1. **Use a different UV version** — v4.2.1 may have bugs. Check if a newer version (v4.x) has better config support.

2. **Use UV's `data` config instead of `configure` event** — Some UV v4 docs show config passed directly to `UV.init()`:
   ```javascript
   UV.init('uv-viewer', {
       manifest: url,
       embedded: true,
       config: '/uv-config.json'
   });
   ```
   A JSON config file may give more control.

3. **Use a custom UV config JSON file** — Create a local `uv-config.json` with all options. UV v4 supports loading config from a URL.

4. **Inspect Digital Bodleian's UV config** — Their viewer works correctly. Check their page source or network requests for a UV config file that could be adapted.

5. **Replace UV with OpenSeadragon directly** — UV is a wrapper around OpenSeadragon. If UV's chrome is causing more problems than it solves, consider using OpenSeadragon directly with a custom folio selector. This gives full control but requires building the navigation UI manually.

6. **Use Mirador instead** — Mirador 3 is another mature IIIF viewer with good theming support. It was the original viewer in the Connundra project this was forked from. However, it's heavier and React-based.
