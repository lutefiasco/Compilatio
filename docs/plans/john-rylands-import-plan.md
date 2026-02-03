# John Rylands Library Import Plan

**Date:** 2026-02-02
**Status:** Complete
**Scope:** 138 John Rylands Library manuscripts from Manchester Digital Collections (via Biblissima)

---

## Overview

**Discovery Source:** Biblissima IIIF Collections Search
- URL: `https://iiif.biblissima.fr/collections/search?collection=Manchester%20Digital%20Collections`
- 232 results, 20 per page (12 pages total)
- Pagination: `from=0`, `from=20`, `from=40`, ... `from=220`

**IIIF Manifest Source:** Manchester Digital Collections
- Manifest URL pattern: `https://www.digitalcollections.manchester.ac.uk/iiif/{MANUSCRIPT-ID}`
- Example IDs: `MS-LATIN-00006`, `MS-ENGLISH-00085`
- Manifests use IIIF Presentation API v2

---

## Technical Approach

### Phase 1: Discovery (Scrape Biblissima)

The Biblissima search results page contains:
1. Thumbnail images with URLs like: `https://image.digitalcollections.manchester.ac.uk/iiif/{ID}.jp2/full/,150/0/default.jpg`
2. Title format: `Manchester. The John Rylands Library, {Type} MS {Number}`
3. IIIF logo links pointing to: `https://www.digitalcollections.manchester.ac.uk/iiif/{MANUSCRIPT-ID}`
4. Metadata: Collection, Library, Language, Date

**Extraction Strategy:**
- Use `urllib` with BeautifulSoup (no bot protection observed)
- Parse each of 12 pages
- Extract IIIF manifest URLs from IIIF logo links or construct from thumbnail URLs
- Extract visible metadata (title, language, date) for fallback values

**Manuscript ID Pattern:**
From the thumbnail/manifest URLs, extract the ID pattern:
- `MS-LATIN-00006` -> Shelfmark: "Latin MS 6"
- `MS-ENGLISH-00085` -> Shelfmark: "English MS 85"
- Pattern: `MS-{TYPE}-{PADDED_NUMBER}`

### Phase 2: Import (Fetch Manifests)

For each discovered manuscript:
1. Fetch IIIF manifest from Manchester
2. Parse metadata from manifest
3. Insert/update database record

**Manifest Metadata Fields Available:**

| Manifest Field | Compilatio Field |
|----------------|------------------|
| `Classmark` | `shelfmark` |
| `label` | `contents` (fallback) |
| `Title` | `contents` |
| `Date of Creation` | `date_display`, `date_start`, `date_end` |
| `Extent` | `folios` |
| `Material(s)` | (not mapped) |
| `Origin` | `provenance` |
| `Provenance` | `provenance` (append) |
| `Script` | (not mapped) |
| Canvas count | `image_count` |
| First canvas image | `thumbnail_url` |

---

## Shelfmark Normalization

The manifest ID needs conversion to human-readable shelfmark:

```python
def normalize_shelfmark(ms_id: str) -> str:
    """Convert MS-LATIN-00006 to 'Latin MS 6'"""
    match = re.match(r"MS-(\w+)-(\d+)", ms_id)
    if match:
        ms_type = match.group(1).title()
        number = str(int(match.group(2)))  # Remove leading zeros
        return f"{ms_type} MS {number}"
    return ms_id
```

**Shelfmark Types Expected:**
- Latin MS
- English MS
- French MS
- Italian MS
- Greek MS
- Hebrew MS (Gaster Hebrew MS)
- Arabic MS
- Persian MS
- Special Collections
- Incunable Collection

---

## Collection Assignment

Group manuscripts by type for the `collection` field:
- "Latin Manuscripts" for Latin MS
- "English Manuscripts" for English MS
- "Gaster Hebrew Manuscripts" for Gaster Hebrew MS
- "Incunabula" for Incunable Collection
- "Special Collections" for Special Collections

---

## Script Structure

```
scripts/importers/john_rylands.py
scripts/importers/cache/
    john_rylands_discovery.json     # Discovery cache
    john_rylands_progress.json      # Checkpoint file
```

**CLI Arguments:**

```bash
python scripts/importers/john_rylands.py                    # Dry-run
python scripts/importers/john_rylands.py --execute          # Import
python scripts/importers/john_rylands.py --resume --execute # Resume
python scripts/importers/john_rylands.py --test             # First 5
python scripts/importers/john_rylands.py --verbose          # Detailed logs
python scripts/importers/john_rylands.py --discover-only    # Discovery only
python scripts/importers/john_rylands.py --skip-discovery   # Use cache
```

---

## Progress File Structure

```json
{
  "last_updated": "2026-02-02T10:00:00Z",
  "total_discovered": 232,
  "completed_ids": ["MS-LATIN-00006", "MS-ENGLISH-00085"],
  "failed_ids": [],
  "phase": "import"
}
```

---

## Rate Limiting

- Discovery: 1.0 second between Biblissima page requests (12 requests total)
- Import: 0.5 seconds between Manchester manifest fetches (232 requests)

---

## Timing Estimates

- Discovery phase: ~15 seconds (12 pages x 1s delay)
- Import phase: ~3 minutes (232 manifests x 0.5s delay + fetch time)
- Total: ~4-5 minutes

---

## Repository Setup

```sql
INSERT INTO repositories (name, short_name, logo_url, catalogue_url)
VALUES (
    'John Rylands Library',
    'Rylands',
    NULL,
    'https://www.digitalcollections.manchester.ac.uk/'
);
```

---

## Error Handling

1. **Biblissima page errors:** Retry 3 times, then log and continue to next page
2. **Manifest fetch failures:** Mark as failed in progress file, continue
3. **Parse errors:** Log warning with manuscript ID, skip, continue
4. **Database errors:** Log error, continue with remaining items

---

## Testing Workflow

```bash
# 1. Dry-run discovery
python scripts/importers/john_rylands.py --discover-only

# 2. Verify discovery cache
cat scripts/importers/cache/john_rylands_discovery.json | python -m json.tool | head -50

# 3. Test mode (5 manuscripts)
python scripts/importers/john_rylands.py --skip-discovery --test --verbose

# 4. Full dry-run
python scripts/importers/john_rylands.py --skip-discovery

# 5. Execute import
python scripts/importers/john_rylands.py --skip-discovery --execute

# 6. Verify database
sqlite3 database/compilatio.db "SELECT shelfmark, collection, date_display FROM manuscripts WHERE repository_id = (SELECT id FROM repositories WHERE short_name = 'Rylands') LIMIT 10;"
```

---

## Validation Checklist

- [ ] Discovery finds ~232 manuscripts
- [ ] Shelfmarks correctly normalized (no padded zeros)
- [ ] Collection groupings are sensible
- [ ] IIIF manifest URLs are valid
- [ ] Thumbnails load correctly
- [ ] Date parsing produces reasonable values
- [ ] Checkpoint/resume works (test with Ctrl+C)
- [ ] No duplicate records
- [ ] Viewer loads imported manuscripts

---

## Implementation Order

1. Create `scripts/importers/john_rylands.py` with boilerplate from template
2. Implement Biblissima HTML parsing (discover_from_biblissima)
3. Implement manifest URL extraction
4. Implement shelfmark normalization
5. Implement IIIF manifest parsing (reuse from other importers)
6. Add checkpoint/progress tracking
7. Add database operations
8. Test discovery phase
9. Test import with --test flag
10. Full dry-run
11. Execute import
12. Verify in viewer

---

## Reference Files

- `scripts/importers/huntington.py` - Best template: has discovery/import phases, checkpoint support, IIIF manifest parsing
- `scripts/importers/parker.py` - Pattern for HTML scraping with BeautifulSoup
- `scripts/importers/nlw.py` - Example of pagination handling
- `Compilatio_Expansions.md` - Project guidelines and required script structure
