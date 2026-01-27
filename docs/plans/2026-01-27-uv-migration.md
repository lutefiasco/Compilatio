# Universal Viewer Migration Plan

## Overview

Replace Mirador with Universal Viewer (UV) v4.2.1 in the manuscript viewer.

## Key Differences

| Aspect | Mirador | Universal Viewer |
|--------|---------|------------------|
| Init | `Mirador.viewer({ id, ... })` | `UV.init("id", { manifest, embedded: true })` |
| Load manifest | `dispatch(Mirador.actions.addWindow({ manifestId }))` | `uv.set({ manifest: url })` |
| Events | Redux store subscriptions | `uv.on("eventName", callback)` |
| CDN CSS | `unpkg.com/mirador@3.3.0/dist/mirador.min.css` | `cdn.jsdelivr.net/npm/universalviewer@4.2.1/dist/uv.css` |
| CDN JS | `unpkg.com/mirador@3.3.0/dist/mirador.min.js` | `cdn.jsdelivr.net/npm/universalviewer@4.2.1/dist/umd/UV.js` |

## UV Key Events

- `CONFIGURE` - customize config before extension loads
- `CREATED` - viewer ready
- `EXTERNAL_RESOURCE_OPENED` - content loaded
- `CANVAS_INDEX_CHANGE` - page changed (from IIIFEvents)

## Implementation Steps

### Step 1: Update viewer.html ✓
- [x] Replace Mirador CDN links with UV links
- [x] Rename viewer container div (mirador-viewer → uv-viewer)

### Step 2: Rewrite viewer.js initialization ✓
- [x] Replace `initMirador()` with `initUniversalViewer()`
- [x] Update `loadManifest()` to use `uv.set()`
- [x] Remove Mirador-specific code (store, dispatch, actions)
- [x] Update DOM element references (miradorViewer → uvViewer)
- [x] Update state variables (miradorInstance → uvInstance)

### Step 3: Update event handling ✓
- [x] Add UV event listeners for CONFIGURE, CREATED, ERROR
- [ ] Test deep linking with URL parameters (needs running server)

### Step 4: Style adjustments ✓
- [x] Update CSS selectors (#mirador-viewer → #uv-viewer)
- [x] Remove Mirador-specific overrides (MUI classes)
- [x] Dark background for UV container

### Step 5: Testing
- [ ] Test with Bodleian manifest
- [ ] Test with British Library manifest
- [ ] Verify keyboard shortcuts still work
- [ ] Verify sidebar integration

## Progress Summary

**Completed 2026-01-27:**
- viewer.html: Mirador CDN → UV v4.2.1 CDN
- viewer.js: Full rewrite of initialization and manifest loading
- styles.css: Updated selectors, removed Mirador-specific overrides
- index.html: Updated viewer description text

**Remaining:**
- Live testing with IIIF manifests (requires server + API)

## Resources

- GitHub: https://github.com/universalviewer/universalviewer
- Manual: https://github.com/UniversalViewer/universalviewer/blob/dev/manual/index.md
- Config: https://github.com/UniversalViewer/universalviewer/blob/dev/manual/CONFIG.md
- Events: https://github.com/UniversalViewer/universalviewer/blob/dev/manual/EVENTS.md
