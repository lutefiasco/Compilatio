# Design Issues Plan

## Overview

Fix visual/layout issues with the Universal Viewer integration in Compilatio's viewer page.

## Current Problems

Based on screenshot analysis (`screenshots/Screenshot 2026-01-27 at 8.40.10 PM.png`):

### 1. Duplicate Sidebars

**Problem**: Two sidebars are showing simultaneously:
- Compilatio's custom sidebar (left) with "INFO" tab showing shelfmark, repository, date
- UV's built-in left panel with its own "INFO" and "CONTENTS" tabs

**Cause**: `leftPanelEnabled: true` in UV config (viewer.js:611)

**Fix**: Disable UV's left panel - Compilatio's sidebar is better suited to our needs

### 2. Floating Title Watermark

**Problem**: "Bodleian Library MS. Add. A. 100" text floats over the manuscript image as a large watermark/attribution

**Cause**: UV displays manifest attribution as an overlay. This may be:
- UV's `attribution` display feature
- The manifest's `attribution` or `label` field being rendered as overlay

**Fix**: Configure UV to suppress attribution overlay, or style it to be less intrusive

### 3. Control Clutter

**Problem**: Too many UI elements competing for attention:
- Compilatio's manuscript selector (top)
- UV's header panel with navigation controls
- UV's footer panel with zoom/fullscreen controls
- UV's left panel tabs
- Compilatio's sidebar collapse button

**Cause**: Both Compilatio and UV are providing their own chrome

**Fix**: Disable UV's header panel, keep only essential controls (footer for zoom/navigation)

---

## Proposed Configuration

Update `src/js/viewer.js` UV initialization:

```javascript
uvInstance.on('configure', function({ config, cb }) {
    cb({
        options: {
            // Disable UV panels that duplicate Compilatio's UI
            headerPanelEnabled: false,
            leftPanelEnabled: false,
            rightPanelEnabled: false,

            // Keep footer for essential image controls
            footerPanelEnabled: true,

            // Suppress attribution overlay
            attributionEnabled: false
        }
    });
});
```

---

## Implementation Steps

### Step 1: Disable Redundant UV Panels
- [ ] Set `leftPanelEnabled: false` - removes duplicate sidebar
- [ ] Set `headerPanelEnabled: false` - removes top navigation bar
- [ ] Keep `footerPanelEnabled: true` - retains zoom/page controls

### Step 2: Suppress Attribution Overlay
- [ ] Try `attributionEnabled: false` in UV config
- [ ] If that doesn't work, investigate CSS override for `.attribution` or similar
- [ ] May need to check UV documentation for correct option name

### Step 3: CSS Cleanup
- [ ] Remove any Mirador-specific CSS that may still be present
- [ ] Ensure UV container fills available space correctly
- [ ] Verify dark theme applies properly to remaining UV elements

### Step 4: Test
- [ ] Test with Bodleian manuscript
- [ ] Test with British Library manuscript
- [ ] Verify sidebar collapse still works
- [ ] Verify keyboard shortcuts (`i` for info, `[` for sidebar toggle)
- [ ] Test mobile responsive layout

---

## UV Configuration Reference

From UV documentation, available options include:

| Option | Default | Purpose |
|--------|---------|---------|
| `headerPanelEnabled` | true | Top bar with title/navigation |
| `footerPanelEnabled` | true | Bottom bar with zoom/page controls |
| `leftPanelEnabled` | true | Left sidebar (index/info) |
| `rightPanelEnabled` | true | Right sidebar (more info) |
| `attributionEnabled` | true | Attribution overlay display |

---

## Success Criteria

- [ ] Only one sidebar visible (Compilatio's)
- [ ] No floating title/attribution text over manuscript image
- [ ] Clean, minimal chrome - manuscript is visual focus
- [ ] Footer controls visible for zoom/navigation
- [ ] Dark theme consistent throughout

---

## Resources

- UV Config docs: https://github.com/UniversalViewer/universalviewer/blob/dev/manual/CONFIG.md
- UV Events docs: https://github.com/UniversalViewer/universalviewer/blob/dev/manual/EVENTS.md
