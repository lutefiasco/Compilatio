# Fix Bodleian Thumbnails

**Date:** 2026-01-28
**Status:** Script enhanced with progress tracking, ready to run
**Issue:** Browse page shows "No image" for all Bodleian manuscripts

## Problem Analysis

The Bodleian importer (`scripts/importers/bodleian.py`) builds thumbnail URLs using the **manifest UUID**:

```python
def extract_thumbnail_url(iiif_manifest_url: str) -> str:
    # Extract UUID from manifest URL
    uuid_match = re.search(r'/manifest/([a-f0-9-]+)\.json', iiif_manifest_url)
    if uuid_match:
        uuid = uuid_match.group(1)
        return f"https://iiif.bodleian.ox.ac.uk/iiif/image/{uuid}/full/200,/0/default.jpg"
```

This is incorrect. The manifest UUID identifies the manifest itself, not any actual image. Each canvas in the manifest has a different image UUID.

### Evidence

The Bodleian IIIF server returns a **placeholder image** (9188 bytes, 200x300) for any non-existent image ID:

```bash
# Fake UUID returns same placeholder as manifest-UUID-based URLs
curl -s "https://iiif.bodleian.ox.ac.uk/iiif/image/00000000-0000-0000-0000-000000000000/full/200,/0/default.jpg" -o /tmp/fake.jpg
curl -s "https://iiif.bodleian.ox.ac.uk/iiif/image/{manifest-uuid}/full/200,/0/default.jpg" -o /tmp/manifest_uuid.jpg
cmp /tmp/fake.jpg /tmp/manifest_uuid.jpg  # SAME FILE
```

### Correct Thumbnail URL

Bodleian manifests include a `thumbnail` field with the correct URL:

```json
{
  "@id": "https://iiif.bodleian.ox.ac.uk/iiif/manifest/0b6e3c05-e1b1-447b-a50c-ce01e4e60c45.json",
  "thumbnail": {
    "@id": "https://iiif.bodleian.ox.ac.uk/iiif/image/ee9bceec-d378-4904-825d-c09a2524c4b2/full/256,/0/default.jpg"
  }
}
```

Note the **different UUID** (`ee9bceec-...` vs `0b6e3c05-...`).

## Fix Strategy

### Option A: Fetch thumbnails from manifests (recommended)

Similar to `scripts/fix_bl_thumbnails.py`, create a script that:
1. Queries all Bodleian manuscripts from the database
2. Fetches each IIIF manifest
3. Extracts the `thumbnail.@id` URL (IIIF v2) or `thumbnail[0].id` (IIIF v3)
4. Updates the database

**Pros:**
- Uses authoritative thumbnail from manifest
- One-time fix for existing data
- ~30-60 min runtime for 1,713 manuscripts at 0.5s/request

**Cons:**
- Requires network requests for each manuscript
- Could break if Bodleian changes manifest format

### Option B: Use first canvas image

Instead of fetching thumbnail field, extract first canvas image ID from manifest.

**Pros:**
- Works even if manifest lacks thumbnail field

**Cons:**
- First canvas might not be the best representative image
- More complex parsing (sequences → canvases → images)

### Recommendation

**Option A** - fetch `thumbnail` field from manifests. Bodleian manifests consistently include this field.

## Implementation Plan

### 1. Create fix script

Create `scripts/fix_bodleian_thumbnails.py`:

```python
#!/usr/bin/env python3
"""Fix Bodleian manuscript thumbnails by fetching from IIIF manifests."""

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path
from urllib.request import urlopen, Request

PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = PROJECT_ROOT / "database" / "compilatio.db"
REQUEST_DELAY = 0.5

def fetch_thumbnail_from_manifest(manifest_url: str) -> str | None:
    """Fetch thumbnail URL from Bodleian IIIF manifest."""
    try:
        req = Request(manifest_url, headers={
            "User-Agent": "Compilatio/1.0 (thumbnail fix)"
        })
        with urlopen(req, timeout=30) as response:
            manifest = json.loads(response.read().decode('utf-8'))

        # IIIF Presentation 2.x format
        thumb = manifest.get("thumbnail")
        if isinstance(thumb, dict):
            return thumb.get("@id")
        elif isinstance(thumb, list) and thumb:
            return thumb[0].get("@id") or thumb[0].get("id")

        return None
    except Exception as e:
        print(f"  Error: {e}")
        return None

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--limit', type=int, help='Limit manuscripts to process')
    parser.add_argument('--db', type=Path, default=DB_PATH)
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Get all Bodleian manuscripts
    query = """
        SELECT m.id, m.shelfmark, m.iiif_manifest_url
        FROM manuscripts m
        JOIN repositories r ON m.repository_id = r.id
        WHERE r.short_name = 'Bodleian'
          AND m.iiif_manifest_url IS NOT NULL
    """
    if args.limit:
        query += f" LIMIT {args.limit}"

    cursor.execute(query)
    manuscripts = cursor.fetchall()
    print(f"Processing {len(manuscripts)} Bodleian manuscripts")

    updated = 0
    for i, ms in enumerate(manuscripts):
        print(f"[{i+1}/{len(manuscripts)}] {ms['shelfmark']}")

        thumbnail_url = fetch_thumbnail_from_manifest(ms['iiif_manifest_url'])
        if thumbnail_url:
            print(f"  -> {thumbnail_url[:70]}...")
            if args.execute:
                cursor.execute(
                    "UPDATE manuscripts SET thumbnail_url = ? WHERE id = ?",
                    (thumbnail_url, ms['id'])
                )
            updated += 1

        time.sleep(REQUEST_DELAY)

    if args.execute:
        conn.commit()
        print(f"\nUpdated {updated} manuscripts")
    else:
        print(f"\nDRY RUN: Would update {updated} manuscripts")

    conn.close()

if __name__ == '__main__':
    main()
```

### 2. Update Bodleian importer

Modify `scripts/importers/bodleian.py` to fetch thumbnails properly for future imports:

1. Remove the `extract_thumbnail_url` function (lines 186-197)
2. Add a function to fetch thumbnail from manifest during import
3. Or, set `thumbnail_url = None` during import and rely on the fix script

### 3. Run the fix

Script created at `scripts/fix_bodleian_thumbnails.py`.

```bash
# Test with 10 manuscripts (dry run)
python scripts/fix_bodleian_thumbnails.py --limit 10

# Full dry run
python scripts/fix_bodleian_thumbnails.py

# Execute for real
python scripts/fix_bodleian_thumbnails.py --execute
```

Estimated runtime: ~15-30 minutes (1,713 manuscripts × 0.5s delay + request time)

## Testing

1. Before fix: Verify Bodleian thumbnails show placeholder
2. After fix: Verify real manuscript images appear
3. Check sample URLs manually in browser

## Rollback

If needed, the original thumbnail URLs can be regenerated by the importer logic (though they were broken anyway).
