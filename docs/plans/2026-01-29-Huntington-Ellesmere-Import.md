# Huntington Library Ellesmere Manuscripts Import Plan

**Date:** 2026-01-29
**Status:** Planning
**Scope:** Ellesmere manuscripts only (mssEL shelfmarks)

## Overview

Import digitized Ellesmere manuscripts from the Huntington Digital Library into Compilatio. The Huntington uses CONTENTdm with IIIF support, allowing direct API access without browser automation.

## Source Analysis

### Platform
- **CONTENTdm** (OCLC digital collections platform)
- **Collection ID:** `p15150coll7`
- **IIIF enabled:** Yes (v2 manifests)

### API Endpoints

**Discovery (CONTENTdm Search API):**
```
https://hdl.huntington.org/digital/api/search/collection/p15150coll7/searchterm/mssEL/field/callid/mode/exact/conn/and/maxRecords/100
```

Returns JSON with:
- `totalResults`: count
- `items[]`: array with `collectionAlias`, `itemId`, `thumbnailUri`, `itemLink`, `metadataFields[]`
- Metadata fields include: `title`, `date`, `callid` (shelfmark)

**IIIF Manifest:**
```
https://hdl.huntington.org/iiif/2/p15150coll7:{itemId}/manifest.json
```

**Viewer URL:**
```
https://hdl.huntington.org/digital/collection/p15150coll7/id/{itemId}
```

### Collection Size
- **~27 Ellesmere manuscripts** (mssEL prefix)
- Small enough for single-phase import (no pagination needed)

## Import Strategy

### Single-Phase Approach (Recommended)

Given the small collection size (~27 items), a simple two-step process:

1. **Discovery:** Single API call to get all mssEL items
2. **Import:** Fetch each IIIF manifest, parse metadata, insert to database

No caching/resumability needed for this size, but we'll include it for:
- Future expansion to other Huntington collections (HM, etc.)
- Robustness against network failures
- 10-minute timeout safety

### Resumability Design

```
data/huntington_discovery.json    # Cached discovery results
data/huntington_progress.json     # Track which items have been imported
```

Progress file format:
```json
{
  "last_updated": "2026-01-29T12:00:00Z",
  "total_discovered": 27,
  "completed_ids": [1, 5, 23, ...],
  "failed_ids": [12],
  "phase": "import"
}
```

### Timeout Handling

The script will:
1. Save progress after each successful manifest fetch
2. On resume, skip already-completed items
3. Use `--resume` flag to continue from last checkpoint

## Data Mapping

| CONTENTdm Field | IIIF Manifest Field | Compilatio Field |
|-----------------|---------------------|------------------|
| `callid` | metadata "Call Number" | `shelfmark` |
| `title` | `label` | `contents` |
| `date` | metadata "Date" | `date_display`, `date_start`, `date_end` |
| - | metadata "Physical description" | `folios` |
| - | metadata "Language" | `language` |
| - | metadata "Provenance" | `provenance` |
| `thumbnailUri` | thumbnail | `thumbnail_url` |
| - | `@id` | `iiif_manifest_url` |
| `itemLink` | - | `source_url` |

### Collection Name

All Ellesmere manuscripts will be assigned to collection: **"Ellesmere"**

## Script Design

### Command-Line Interface

```bash
# Dry-run (default) - show what would be imported
python scripts/importers/huntington.py

# Execute import
python scripts/importers/huntington.py --execute

# Test mode - first 5 only
python scripts/importers/huntington.py --test

# Resume interrupted import
python scripts/importers/huntington.py --resume --execute

# Discover only (save to cache, don't import)
python scripts/importers/huntington.py --discover-only

# Skip discovery (use cached data)
python scripts/importers/huntington.py --skip-discovery --execute

# Verbose logging
python scripts/importers/huntington.py --verbose
```

### Script Structure

```python
#!/usr/bin/env python3
"""
Huntington Library Ellesmere Manuscript Import Script for Compilatio.

Imports digitized Ellesmere manuscripts from the Huntington Digital Library
via CONTENTdm API and IIIF manifests.

Two-phase process with checkpoint resumability:
  Phase 1 (Discovery): Query CONTENTdm API for mssEL items
  Phase 2 (Import): Fetch IIIF manifests, parse metadata, insert to database

Usage:
    python scripts/importers/huntington.py                # Dry-run
    python scripts/importers/huntington.py --execute      # Actually import
    python scripts/importers/huntington.py --resume       # Resume from checkpoint
    python scripts/importers/huntington.py --test         # First 5 only
"""

# Sections:
# 1. Constants and paths
# 2. HTTP helpers with retry logic
# 3. Phase 1: Discovery (CONTENTdm API)
# 4. Phase 2: IIIF manifest parsing
# 5. Progress/checkpoint management
# 6. Database operations
# 7. Main import logic
# 8. CLI
```

### Rate Limiting

- **0.5 seconds** between IIIF manifest fetches
- Respectful User-Agent header

### Error Handling

- HTTP errors: log warning, record in failed_ids, continue
- Parse errors: log warning, skip item, continue
- Database errors: log error, continue with other items

## Repository Setup

```sql
INSERT INTO repositories (name, short_name, logo_url, catalogue_url)
VALUES (
    'Huntington Library',
    'Huntington',
    NULL,
    'https://hdl.huntington.org/digital/collection/p15150coll7'
);
```

## Testing Checklist

- [ ] Dry-run shows correct count (~27 manuscripts)
- [ ] Test mode imports 5 items correctly
- [ ] Full import completes
- [ ] Resume works after interruption
- [ ] Viewer loads imported manuscripts
- [ ] Thumbnails display correctly
- [ ] Metadata fields populated correctly

## Future Expansion

Once Ellesmere import is validated, the script can be extended to:
- **HM collection** (~44 medieval manuscripts)
- Other Huntington manuscript collections

Add `--collection` flag:
```bash
python scripts/importers/huntington.py --collection EL    # Ellesmere (default)
python scripts/importers/huntington.py --collection HM    # Huntington manuscripts
python scripts/importers/huntington.py --collection all   # All manuscript collections
```

## Implementation Order

1. Create `scripts/importers/huntington.py` with basic structure
2. Implement discovery phase (CONTENTdm API)
3. Implement IIIF manifest parsing
4. Add checkpoint/progress tracking
5. Add database operations
6. Test with --test flag
7. Full dry-run
8. Execute import
9. Verify in viewer
