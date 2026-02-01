# Parker Library Shelfmark Fix Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix 368 Parker Library manuscripts that have Stanford DRUID-based shelfmarks (e.g., "MS bc854fy5899") instead of proper MS numbers (e.g., "MS 296").

**Architecture:** Create a one-time fix script that fetches each affected manuscript's IIIF manifest, extracts the correct MS number from the `label` field, and updates the database. The manifest label format is "Cambridge, Corpus Christi College, MS NNN: Title".

**Tech Stack:** Python, SQLite, urllib (standard library only - no external dependencies)

---

## Background

- **Total Parker manuscripts:** 640
- **Correct shelfmarks:** 272 (MS 095 through MS 645)
- **Broken shelfmarks:** 368 (druid-based like "MS bc854fy5899")
- **Cause:** HTML discovery regex `MS\.?\s*(\d+[A-Za-z]?)` failed to extract MS numbers from catalog pages, falling back to druid

The IIIF manifest `label` field contains the correct shelfmark:
```
"Cambridge, Corpus Christi College, MS 001: Garnerius of Saint-Victor..."
```

---

### Task 1: Create the Fix Script

**Files:**
- Create: `scripts/fix_parker_shelfmarks.py`

**Step 1: Write the fix script**

```python
#!/usr/bin/env python3
"""
Fix Parker Library shelfmarks that incorrectly use Stanford DRUIDs.

Fetches the IIIF manifest for each affected manuscript and extracts
the correct MS number from the label field.

Usage:
    python scripts/fix_parker_shelfmarks.py           # Dry run
    python scripts/fix_parker_shelfmarks.py --execute # Apply changes
"""

import argparse
import json
import re
import sqlite3
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = PROJECT_ROOT / "database" / "compilatio.db"

USER_AGENT = "Compilatio/1.0 (Academic manuscript research; IIIF aggregator)"
MANIFEST_DELAY = 0.3  # seconds between requests


def fetch_manifest(url: str) -> dict | None:
    """Fetch IIIF manifest JSON."""
    try:
        req = Request(url, headers={"User-Agent": USER_AGENT})
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (HTTPError, URLError, json.JSONDecodeError) as e:
        print(f"  Error fetching {url}: {e}")
        return None


def extract_ms_number(label: str) -> str | None:
    """
    Extract MS number from manifest label.

    Expected format: "Cambridge, Corpus Christi College, MS 049: Title"
    Returns: "MS 049" or None if not found
    """
    if isinstance(label, dict):
        label = label.get("@value", "") or str(label)

    # Match "MS" followed by digits and optional letter suffix (e.g., MS 049, MS 098A)
    match = re.search(r"MS\s*(\d{3}[A-Za-z]?)", str(label))
    if match:
        return f"MS {match.group(1)}"
    return None


def get_affected_manuscripts(cursor) -> list[tuple]:
    """Get Parker manuscripts with druid-based shelfmarks."""
    cursor.execute("""
        SELECT id, shelfmark, iiif_manifest_url
        FROM manuscripts
        WHERE repository_id = (SELECT id FROM repositories WHERE short_name = 'Parker')
          AND shelfmark GLOB 'MS [a-z][a-z][0-9][0-9][0-9][a-z][a-z][0-9][0-9][0-9][0-9]'
        ORDER BY shelfmark
    """)
    return cursor.fetchall()


def main():
    parser = argparse.ArgumentParser(description="Fix Parker Library shelfmarks")
    parser.add_argument("--execute", action="store_true", help="Apply changes (default: dry run)")
    parser.add_argument("--limit", type=int, help="Limit number of manuscripts to process")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}")
        return 1

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    manuscripts = get_affected_manuscripts(cursor)
    print(f"Found {len(manuscripts)} manuscripts with druid-based shelfmarks")

    if args.limit:
        manuscripts = manuscripts[:args.limit]
        print(f"Limiting to {args.limit} manuscripts")

    stats = {"success": 0, "failed": 0, "skipped": 0}
    updates = []

    for i, (ms_id, old_shelfmark, manifest_url) in enumerate(manuscripts):
        print(f"[{i+1}/{len(manuscripts)}] {old_shelfmark}")

        manifest = fetch_manifest(manifest_url)
        if not manifest:
            stats["failed"] += 1
            continue

        label = manifest.get("label", "")
        new_shelfmark = extract_ms_number(label)

        if not new_shelfmark:
            print(f"  Could not extract MS number from label: {label[:80]}...")
            stats["failed"] += 1
            continue

        # Check if new shelfmark already exists
        cursor.execute(
            "SELECT id FROM manuscripts WHERE repository_id = 10 AND shelfmark = ? AND id != ?",
            (new_shelfmark, ms_id)
        )
        if cursor.fetchone():
            print(f"  Shelfmark {new_shelfmark} already exists, skipping")
            stats["skipped"] += 1
            continue

        print(f"  -> {new_shelfmark}")
        updates.append((new_shelfmark, ms_id, old_shelfmark))
        stats["success"] += 1

        if i < len(manuscripts) - 1:
            time.sleep(MANIFEST_DELAY)

    print(f"\n{'='*60}")
    print(f"{'DRY RUN - ' if not args.execute else ''}SUMMARY")
    print(f"{'='*60}")
    print(f"Successfully mapped: {stats['success']}")
    print(f"Failed to extract:   {stats['failed']}")
    print(f"Skipped (duplicate): {stats['skipped']}")

    if updates and args.execute:
        print(f"\nApplying {len(updates)} updates...")
        for new_shelfmark, ms_id, old_shelfmark in updates:
            cursor.execute(
                "UPDATE manuscripts SET shelfmark = ? WHERE id = ?",
                (new_shelfmark, ms_id)
            )
        conn.commit()
        print("Done!")
    elif updates:
        print(f"\nWould update {len(updates)} manuscripts.")
        print("Run with --execute to apply changes.")

    conn.close()
    return 0


if __name__ == "__main__":
    exit(main())
```

**Step 2: Make the script executable**

Run: `chmod +x scripts/fix_parker_shelfmarks.py`

---

### Task 2: Test Dry Run

**Step 1: Run the script in dry-run mode with limit**

Run: `python scripts/fix_parker_shelfmarks.py --limit 5`

Expected output:
```
Found 368 manuscripts with druid-based shelfmarks
Limiting to 5 manuscripts
[1/5] MS bc854fy5899
  -> MS 296
[2/5] MS bg021sq9590
  -> MS XXX
...
```

Verify each extracted MS number looks reasonable (3 digits, possibly with letter suffix).

---

### Task 3: Execute Full Fix

**Step 1: Run the fix script**

Run: `python scripts/fix_parker_shelfmarks.py --execute`

Expected:
- ~368 manuscripts processed
- Most should succeed (manifest URLs are working)
- Small number may fail if manifests are unavailable

**Step 2: Verify results**

Run: `sqlite3 database/compilatio.db "SELECT COUNT(*) FROM manuscripts WHERE repository_id = 10 AND shelfmark GLOB 'MS [a-z]*';"`

Expected: `0` (no more druid-based shelfmarks)

Run: `sqlite3 database/compilatio.db "SELECT COUNT(*) FROM manuscripts WHERE repository_id = 10;"`

Expected: `640` (total unchanged)

**Step 3: Spot check a few records**

Run: `sqlite3 database/compilatio.db "SELECT shelfmark, contents FROM manuscripts WHERE repository_id = 10 ORDER BY shelfmark LIMIT 10;"`

Expected: Proper MS numbers like "MS 001", "MS 002", etc.

---

### Task 4: Commit Changes

**Step 1: Commit the fix script**

```bash
git add scripts/fix_parker_shelfmarks.py
git commit -m "Add script to fix Parker Library shelfmarks

368/640 Parker manuscripts had Stanford DRUID-based shelfmarks
(e.g., 'MS bc854fy5899') instead of proper MS numbers.

Script fetches IIIF manifest and extracts correct shelfmark
from label field.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Notes

- The fix script can be deleted after running, or kept for reference
- Rate limiting (0.3s) keeps us polite to Stanford servers
- Script handles edge cases: duplicate shelfmarks, missing manifests, malformed labels
