# Compilatio Enhancement Plans

Four enhancements planned for the next development phase.

---

## 1. About Page
**Status: Complete**

Created `src/about.html` with:
- Dynamic totals (repositories and manuscripts from API)
- Sources list with links to catalogues
- Changelog section
- Contact section
- Footer link added to index.html and browse.html

---

## 2. Page Jump Navigation
**Status: Complete**

Added page input field to browse pagination:
- Type page number and press Enter to jump
- Input validates and clamps to valid range
- Previous/Next buttons still work
- URL updates with new offset (bookmarkable)

Files modified:
- `src/browse.html` - pagination HTML
- `src/js/browse.js` - goToPage function, event listeners
- `src/css/styles.css` - page input styling

---

## 3. Trinity College Cambridge Thumbnail Script
**Status: Ready**

TCC manuscripts currently show without thumbnails. Root cause: importer looked for thumbnails in canvas, but TCC manifests have them at manifest level.

Implementation:
- Created `scripts/fix_tcc_thumbnails.py` based on Bodleian fixer template
- Extracts manifest-level `thumbnail` field (TCC uses string URLs, not objects)
- Features: --execute, --limit, --status, --reset, --batch-size
- Progress tracking with resume capability (`.tcc_thumbnail_progress.json`)
- 534 manuscripts need updating

Usage:
```bash
python3 scripts/fix_tcc_thumbnails.py              # Dry-run
python3 scripts/fix_tcc_thumbnails.py --execute    # Apply changes
python3 scripts/fix_tcc_thumbnails.py --status     # Check progress
```

---

## 4. Viewer Dropdown Fix for Single/No Collection Repositories
**Status: Complete**

Fixed viewer page for TCC manuscripts (and any repository with no collections):
- Added `loadManuscriptsForRepo()` function
- When repository has 0 collections, loads manuscripts directly
- Collection dropdown shows "(no collections)" and stays disabled
- Manuscript dropdown populates immediately

Files modified:
- `src/viewer.html` - handleRepoChange function with fallback logic

---

## Summary

| Enhancement | Status |
|-------------|--------|
| About Page | Complete |
| Page Jump | Complete |
| TCC Thumbnails | Ready |
| Viewer Dropdown Fix | Complete |
