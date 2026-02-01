# Parker Library Import — Completed

**Status:** Complete (2026-02-01)
**Final count:** 560 manuscripts

---

## Background: The DRUID Problem

Parker Library manuscripts are hosted by Stanford University Libraries. Each manuscript has two identifiers:

1. **Proper shelfmark:** `MS 049` (the standard scholarly citation)
2. **Stanford DRUID:** `qy662bj1544` (Stanford's internal Digital Repository Unique ID)

The IIIF manifests are accessed via DRUID URLs:
```
https://purl.stanford.edu/qy662bj1544/iiif/manifest
```

But the manifest's `label` field contains the proper shelfmark:
```
"Cambridge, Corpus Christi College, MS 049: Bible"
```

## The Anti-Bot Problem

Stanford's Parker Library website (`parker.stanford.edu`) has aggressive bot protection that blocks all automated access:

- **Playwright:** Blocked
- **crawl4ai:** Blocked
- **curl/wget:** Blocked
- **Any programmatic access:** Blocked

**Workaround:** Manually save HTML page source from browser, then parse locally.

The HTML parsing regex `MS\.?\s*(\d+[A-Za-z]?)` failed to extract MS numbers from the catalog pages because the HTML structure didn't reliably contain them in a parseable format. When parsing failed, the importer fell back to using the DRUID as the shelfmark:

```python
if not shelfmark:
    shelfmark = f"MS {druid}"  # Fallback: "MS qy662bj1544"
```

This resulted in 368 manuscripts with DRUID-based shelfmarks instead of proper MS numbers.

## The Fix

**Script:** `scripts/fix_parker_shelfmarks.py`

1. Query database for Parker manuscripts with DRUID-pattern shelfmarks
2. Fetch each manuscript's IIIF manifest (manifests are accessible, unlike the catalog)
3. Extract proper MS number from manifest `label` field
4. Update database

**Results:**
- 288 shelfmarks fixed (DRUID → proper MS number)
- 80 duplicates removed (same manuscript existed twice: once with correct shelfmark from later import phase, once with DRUID from earlier phase)
- Final count: 560 manuscripts

## Lessons Learned

1. **IIIF manifests are the authoritative source** — The catalog HTML is unreliable and heavily protected; manifests have clean structured data

2. **Anti-bot measures make discovery hard** — Manual HTML download was required, leading to incomplete/inconsistent data

3. **Two-phase imports create duplicates** — When shelfmark extraction fails in phase 1 but succeeds in phase 2, you get duplicate records

4. **Scripts must be resumable** — Long-running scripts need checkpoint files and `--resume` support

## Import Commands

```bash
# Discovery (requires manual HTML download due to bot protection)
# Save pages from parker.stanford.edu to scripts/importers/resources/parker_html/
python scripts/importers/parker.py --from-html scripts/importers/resources/parker_html/ --discover-only

# Import
python scripts/importers/parker.py --skip-discovery --execute

# Fix shelfmarks (if needed)
python scripts/fix_parker_shelfmarks.py --execute

# Remove duplicates (if needed)
sqlite3 database/compilatio.db "DELETE FROM manuscripts WHERE repository_id = 10 AND shelfmark GLOB 'MS [a-z][a-z][0-9][0-9][0-9][a-z][a-z][0-9][0-9][0-9][0-9]';"
```
