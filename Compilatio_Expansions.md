# Compilatio Repository Expansion Plan

This document provides a robust, repeatable process for adding new repositories to Compilatio. It covers exploration, import script development, testing, and database synchronization to production.

---

## Table of Contents

1. [Overview](#overview)
2. [Repository Exploration Process](#repository-exploration-process)
3. [Import Script Development](#import-script-development)
4. [Testing and Validation](#testing-and-validation)
5. [Database Synchronization](#database-synchronization)
6. [Priority Repositories](#priority-repositories)

---

## Overview

### Current State

| Repository | Manuscripts | Import Method |
|------------|-------------|---------------|
| Bodleian Library | 1,713 | TEI/XML parsing from git clone |
| Cambridge University Library | 304 | IIIF collection crawl |
| Durham University Library | 287 | IIIF collection tree |
| National Library of Wales | 226 | crawl4ai + IIIF manifests |
| Huntington Library | 190 | CONTENTdm API + IIIF |
| British Library | 178 | Playwright + HTML scraping |
| Parker Library | 640 | Manual HTML + IIIF manifests |
| Yale (Takamiya) | 139 | Direct IIIF |
| UCLA | 115 | Direct IIIF |
| National Library of Scotland | 104 | IIIF collection tree |
| Trinity College Cambridge | 10 | Playwright + IIIF manifests |
| Lambeth Palace Library | 2 | CUDL IIIF subset |
| **Total** | **3,908** | |

### Import Methods Overview

| Method | When to Use | Dependencies |
|--------|-------------|--------------|
| **IIIF Collection** | Repository publishes IIIF collection manifest | Standard library only |
| **API + IIIF** | Repository has search API (CONTENTdm, Blacklight, etc.) | Standard library only |
| **crawl4ai** | JavaScript-rendered pages with bot protection, CAPTCHA sites | Python 3.12, crawl4ai |
| **Playwright** | Heavy JavaScript without bot protection | Playwright, beautifulsoup4 |
| **TEI/XML** | Repository publishes TEI catalog data | lxml or standard library |
| **Manual + IIIF** | Aggressive bot protection blocks all automation | Standard library only |

### Choosing Between crawl4ai and Playwright

**Prefer crawl4ai** for sites with:
- Cloudflare protection
- CAPTCHA challenges
- Bot detection (e.g., Akamai, PerimeterX)
- Rate limiting based on browser fingerprinting

crawl4ai includes anti-detection features that Playwright lacks. Use the Python 3.12 venv:
```bash
source .venv-crawl4ai/bin/activate
```

**Use Playwright** only for:
- Simple JavaScript-rendered pages without bot protection
- Sites where crawl4ai fails for other reasons

**Fallback to Manual** when:
- Even crawl4ai is blocked (e.g., Stanford Parker Library)
- Site requires human verification
- No API alternatives exist

---

## Repository Exploration Process

Before writing any code, explore the target repository to understand its technical infrastructure.

### Phase 1: Initial Assessment

Use a subagent to investigate the repository. Key questions:

1. **Does it have IIIF support?**
   - Look for IIIF logo/links on viewer pages
   - Check if manifests are accessible (usually `/iiif/` or `/manifest.json` in URLs)
   - Search for IIIF collection endpoints

2. **Is there an API?**
   - Look for `/api/`, `/search/`, or query parameters in URLs
   - Check for Blacklight, CONTENTdm, Luna, or other known platforms
   - Inspect network requests in browser developer tools

3. **What catalog metadata is available?**
   - Shelfmarks/call numbers
   - Dates
   - Contents/titles
   - Provenance
   - Language

4. **Are there access restrictions?**
   - Rate limiting
   - Authentication requirements
   - CAPTCHA/bot protection

### Phase 2: Technical Deep Dive

Once the basic structure is understood, gather specifics:

```markdown
## [Repository Name] Technical Assessment

### Platform
- [ ] Blacklight (Ruby)
- [ ] CONTENTdm
- [ ] Luna Imaging
- [ ] Custom platform
- [ ] Spotlight Exhibits (Stanford)

### IIIF Support
- [ ] Presentation API v2
- [ ] Presentation API v3
- [ ] Image API
- Collection manifest URL: _______________
- Manifest URL pattern: _______________

### API Endpoints
- Search: _______________
- Item details: _______________
- Collection listing: _______________

### Metadata Mapping
| Field | Source Label | IIIF metadata key |
|-------|--------------|-------------------|
| shelfmark | | |
| date_display | | |
| contents | | |
| language | | |
| provenance | | |

### Technical Notes
- Rate limiting observed: _______________
- JavaScript required: Yes / No
- Pagination method: _______________
- Total manuscripts estimated: _______________
```

### Exploration Subagent Prompt Template

```
Explore [Repository Name] at [URL] for IIIF manuscript integration.

Tasks:
1. Identify the catalog platform (Blacklight, CONTENTdm, etc.)
2. Find IIIF endpoints:
   - Collection manifest URLs
   - Individual manifest URL patterns
3. Document available metadata fields
4. Check for API endpoints or search functionality
5. Note any access restrictions or rate limiting
6. Estimate total manuscript count

Return a technical assessment with:
- Platform identification
- IIIF support details
- API endpoints found
- Metadata field mapping
- Recommended import approach
```

---

## Import Script Development

### Standard Script Structure

All importers follow a consistent pattern. Create new scripts in `scripts/importers/`:

**CRITICAL REQUIREMENTS:**
- ✅ **Two-phase operation** (discovery → import)
- ✅ **Checkpoint/resume support** (save progress after each item)
- ✅ **Interruptible** (can be stopped and resumed safely)
- ✅ **Progress logging** (show X/Y completed)
- ✅ **Background-ready** (imports >10 minutes must support this)

```python
#!/usr/bin/env python3
"""
[Repository Name] Manuscript Import Script for Compilatio.

[Brief description of data source and import method]

Two-phase process with checkpoint resumability:
  Phase 1 (Discovery): [Description of how manuscripts are discovered]
  Phase 2 (Import): [Description of manifest fetching and database insertion]

Usage:
    python scripts/importers/[repo].py                    # Dry-run mode
    python scripts/importers/[repo].py --execute          # Actually import
    python scripts/importers/[repo].py --resume --execute # Resume interrupted import
    python scripts/importers/[repo].py --test             # First 5 only
    python scripts/importers/[repo].py --verbose          # Detailed logging
    python scripts/importers/[repo].py --discover-only    # Discovery phase only
    python scripts/importers/[repo].py --skip-discovery   # Use cached discovery data

Note: Full import takes ~[X] minutes. Use --resume to continue if interrupted.
"""

import argparse
import json
import logging
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
DB_PATH = PROJECT_ROOT / "database" / "compilatio.db"
CACHE_DIR = PROJECT_ROOT / "scripts" / "importers" / "cache"
DISCOVERY_CACHE = CACHE_DIR / "[repo]_discovery.json"
PROGRESS_FILE = CACHE_DIR / "[repo]_progress.json"

# Repository-specific constants
REPO_NAME = "[Full Repository Name]"
REPO_SHORT = "[Short Code]"
COLLECTION_URL = "[IIIF collection or API endpoint]"
VIEWER_BASE = "[Base URL for source links]"

# Rate limiting
REQUEST_DELAY = 0.5  # seconds between requests

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)

USER_AGENT = "Compilatio/1.0 (Academic manuscript research; IIIF aggregator)"
```

### Required Functions

Every importer must implement:

```python
# Progress/Checkpoint Management (REQUIRED)
def load_progress(progress_path: Path) -> dict:
    """Load progress from checkpoint file."""
    pass

def save_progress(progress: dict, progress_path: Path):
    """Save progress to checkpoint file."""
    pass

def mark_completed(progress: dict, item_id: str, progress_path: Path):
    """Mark an item as completed and save checkpoint."""
    pass

def mark_failed(progress: dict, item_id: str, progress_path: Path):
    """Mark an item as failed and save checkpoint."""
    pass

# Data Fetching
def fetch_json(url: str) -> Optional[dict]:
    """Fetch URL and parse as JSON with error handling."""
    pass

def discover_manuscripts() -> list[dict]:
    """Phase 1: Get list of manuscript items to import."""
    pass

def parse_manifest(manifest_data: dict, manifest_url: str) -> Optional[dict]:
    """Phase 2: Parse IIIF manifest into database record."""
    pass

# Database Operations
def ensure_repository(cursor) -> int:
    """Create or get repository ID in database."""
    pass

def manuscript_exists(cursor, shelfmark: str, repo_id: int) -> Optional[int]:
    """Check if manuscript already exists."""
    pass

# Main Functions
def import_[repo](db_path, dry_run=True, test_mode=False, verbose=False, resume=False):
    """Main import function with checkpoint support."""
    pass

def main():
    """CLI entry point."""
    pass
```

**Progress File Structure:**

```json
{
  "last_updated": "2026-01-31T22:30:00Z",
  "total_discovered": 850,
  "completed_ids": ["B.1.1", "B.1.2", ...],
  "failed_ids": ["B.2.5"],
  "phase": "import"
}
```

### Database Record Fields

Each manuscript record must include:

| Field | Required | Description |
|-------|----------|-------------|
| `shelfmark` | Yes | Unique identifier within repository |
| `collection` | No | Sub-collection grouping |
| `iiif_manifest_url` | Yes | Full URL to IIIF manifest |
| `thumbnail_url` | No | URL to thumbnail image |
| `source_url` | No | Link to original catalog page |
| `date_display` | No | Human-readable date string |
| `date_start` | No | Start year as integer |
| `date_end` | No | End year as integer |
| `contents` | No | Title or contents description |
| `language` | No | Language(s) |
| `provenance` | No | Origin/provenance notes |
| `folios` | No | Physical extent |
| `image_count` | No | Number of pages/images |

### CLI Arguments

**Required arguments for all importers:**

```python
parser.add_argument('--execute', action='store_true',
    help='Actually execute the import (default is dry-run)')
parser.add_argument('--test', action='store_true',
    help='Test mode: limit to first page of results')
parser.add_argument('--verbose', '-v', action='store_true',
    help='Show detailed logging')
parser.add_argument('--db', type=Path, default=DB_PATH,
    help='Path to database')
parser.add_argument('--limit', type=int, default=None,
    help='Limit number of manuscripts to process')

# Checkpoint/resume support (REQUIRED for all importers)
parser.add_argument('--resume', action='store_true',
    help='Resume from last checkpoint')
parser.add_argument('--discover-only', action='store_true',
    help='Only run discovery phase')
parser.add_argument('--skip-discovery', action='store_true',
    help='Use cached discovery data')
```

**Optional arguments for specific needs:**

```python
# For multi-collection repositories
parser.add_argument('--collection', '-c', type=str,
    help='Specific collection to import')
```

---

## Testing and Validation

### Test Workflow

1. **Dry run first** (always):
   ```bash
   python scripts/importers/[repo].py
   ```

2. **Test mode** (first page only):
   ```bash
   python scripts/importers/[repo].py --test --verbose
   ```

3. **Limited run** (verify at scale):
   ```bash
   python scripts/importers/[repo].py --limit 50 --verbose
   ```

4. **Discovery only** (cache shelfmarks):
   ```bash
   python scripts/importers/[repo].py --discover-only
   ```

5. **Full dry run** (verify all records):
   ```bash
   python scripts/importers/[repo].py --skip-discovery --verbose
   ```

6. **Execute** (write to database):
   ```bash
   python scripts/importers/[repo].py --skip-discovery --execute
   ```

7. **Resume if interrupted**:
   ```bash
   python scripts/importers/[repo].py --resume --execute
   ```

### Checkpoint/Resume Testing

Always test checkpoint functionality:

```bash
# Start an import
python scripts/importers/[repo].py --execute --limit 10

# Interrupt with Ctrl+C after 5 complete

# Resume - should skip first 5
python scripts/importers/[repo].py --resume --execute

# Check progress file
cat scripts/importers/cache/[repo]_progress.json
```

### Validation Checklist

Before considering an import complete:

- [ ] All expected manuscripts discovered
- [ ] Shelfmarks are unique and correctly formatted
- [ ] IIIF manifest URLs are valid and accessible
- [ ] Thumbnail URLs load correctly
- [ ] Source URLs link to correct catalog pages
- [ ] Date parsing produces reasonable values
- [ ] No duplicate records created
- [ ] Collection groupings are sensible
- [ ] **Checkpoint/resume works** (test interruption and resumption)
- [ ] **Progress file updates** after each successful import
- [ ] **Failed items tracked** in progress file
- [ ] **Dry-run mode works** without creating checkpoint files

### Quick Database Checks

```bash
# Count by repository
sqlite3 database/compilatio.db "SELECT r.short_name, COUNT(*)
FROM manuscripts m
JOIN repositories r ON m.repository_id = r.id
GROUP BY r.id;"

# Check for duplicate shelfmarks
sqlite3 database/compilatio.db "SELECT shelfmark, COUNT(*) as cnt
FROM manuscripts
WHERE repository_id = [ID]
GROUP BY shelfmark
HAVING cnt > 1;"

# Sample records from new repository
sqlite3 database/compilatio.db -header "SELECT * FROM manuscripts
WHERE repository_id = [ID]
LIMIT 5;"
```

---

## Database Synchronization

### Architecture

```
┌─────────────────┐         ┌──────────────────┐         ┌─────────────────────────┐
│   server       │         │   laptop         │         │ oldbooks.humspace.ucla  │
│   (primary)     │◄───────►│   (dev)          │────────►│ (production)            │
│   SQLite        │  rsync  │   SQLite         │ export  │ MySQL                   │
└─────────────────┘         └──────────────────┘         └─────────────────────────┘
```

### Step 1: Sync SQLite Between server and laptop

After running imports on server:

```bash
# On laptop - pull latest database from server
rsync -avz server:/Users/rabota/Geekery/Compilatio/database/compilatio.db ./database/

# Or push laptop changes to server
rsync -avz ./database/compilatio.db server:/Users/rabota/Geekery/Compilatio/database/
```

### Step 2: Export SQLite to MySQL Format

Create export files for phpMyAdmin import:

```bash
cd /Users/rabota/Geekery/Compilatio

# Create export directory
mkdir -p mysql_export

# Export repositories table
sqlite3 database/compilatio.db ".mode insert repositories" \
  ".output mysql_export/repositories.sql" \
  "SELECT * FROM repositories;"

# Export manuscripts table
sqlite3 database/compilatio.db ".mode insert manuscripts" \
  ".output mysql_export/manuscripts.sql" \
  "SELECT * FROM manuscripts;"

# Verify counts
echo "Repositories: $(sqlite3 database/compilatio.db 'SELECT COUNT(*) FROM repositories;')"
echo "Manuscripts: $(sqlite3 database/compilatio.db 'SELECT COUNT(*) FROM manuscripts;')"
```

### Step 3: Upload Export Files to oldbooks

**Option A: FTP**

1. Connect to `oldbooks.humspace.ucla.edu` with FTP client
2. Upload `mysql_export/*.sql` to a working directory (e.g., `~/mysql_import/`)

**Option B: cPanel File Manager**

1. Log in to cPanel at `oldbooks.humspace.ucla.edu/cpanel`
2. Open File Manager
3. Navigate to home directory
4. Create `mysql_import` folder
5. Upload the SQL files

**Option C: SCP (if SSH available)**

```bash
scp mysql_export/*.sql oldbooks:~/mysql_import/
```

### Step 4: Import to MySQL via phpMyAdmin

1. Log in to cPanel → phpMyAdmin
2. Select the `compilatio` database
3. Go to the **SQL** tab

**For full refresh** (recommended when adding new repositories):

```sql
-- Disable foreign key checks temporarily
SET FOREIGN_KEY_CHECKS = 0;

-- Clear existing data
TRUNCATE TABLE manuscripts;
TRUNCATE TABLE repositories;

-- Re-enable foreign key checks
SET FOREIGN_KEY_CHECKS = 1;
```

4. Go to **Import** tab
5. Import `repositories.sql` first
6. Import `manuscripts.sql` second

**For manuscript-only updates** (when repositories unchanged):

```sql
SET FOREIGN_KEY_CHECKS = 0;
TRUNCATE TABLE manuscripts;
SET FOREIGN_KEY_CHECKS = 1;
```

Then import only `manuscripts.sql`.

### Step 5: Verify Import

In phpMyAdmin SQL tab:

```sql
-- Check counts
SELECT 'repositories' as tbl, COUNT(*) as cnt FROM repositories
UNION ALL
SELECT 'manuscripts', COUNT(*) FROM manuscripts;

-- Verify new repository
SELECT r.short_name, COUNT(*) as manuscripts
FROM manuscripts m
JOIN repositories r ON m.repository_id = r.id
GROUP BY r.id
ORDER BY manuscripts DESC;
```

### Automation Script

Create `scripts/sync_to_production.sh`:

```bash
#!/bin/bash
# Sync Compilatio database to oldbooks.humspace.ucla.edu
# Run from project root after completing imports

set -e

echo "=== Compilatio Database Sync ==="

# Export
echo "Exporting SQLite to MySQL format..."
mkdir -p mysql_export

sqlite3 database/compilatio.db ".mode insert repositories" \
  ".output mysql_export/repositories.sql" \
  "SELECT * FROM repositories;"

sqlite3 database/compilatio.db ".mode insert manuscripts" \
  ".output mysql_export/manuscripts.sql" \
  "SELECT * FROM manuscripts;"

REPO_COUNT=$(sqlite3 database/compilatio.db "SELECT COUNT(*) FROM repositories;")
MS_COUNT=$(sqlite3 database/compilatio.db "SELECT COUNT(*) FROM manuscripts;")

echo "Exported: $REPO_COUNT repositories, $MS_COUNT manuscripts"
echo "Files in mysql_export/"

echo ""
echo "=== Next Steps ==="
echo "1. Upload mysql_export/*.sql to oldbooks via FTP or cPanel"
echo "2. In phpMyAdmin, run:"
echo "   SET FOREIGN_KEY_CHECKS = 0;"
echo "   TRUNCATE TABLE manuscripts;"
echo "   TRUNCATE TABLE repositories;"
echo "   SET FOREIGN_KEY_CHECKS = 1;"
echo "3. Import repositories.sql first, then manuscripts.sql"
echo "4. Verify counts match: $REPO_COUNT repos, $MS_COUNT manuscripts"
```

---

## Priority Repositories

### 1. Parker Library (Corpus Christi College, Cambridge)

**Status:** ✅ Complete (2026-01-31)

**Technical Details:**
- **Platform:** Stanford Spotlight Exhibits (Blacklight)
- **IIIF Support:** Yes, via Stanford PURL service
- **Manifest URL Pattern:** `https://purl.stanford.edu/{druid}/iiif/manifest`
- **Website:** [parker.stanford.edu](https://parker.stanford.edu/parker/)
- **Bot Protection:** Aggressive (blocks Playwright, crawl4ai, and direct requests)

**Import Results:**
- **Discovered:** 560 manuscripts from 6 HTML pages
- **Imported:** 640 manuscripts (464 new + 176 existing updated)
- **Errors:** 0

**Import Method:**
Due to Stanford's bot protection, manual HTML download was required:
1. HTML pages saved from browser to `scripts/importers/resources/parker_html/`
2. Importer parses HTML to extract druids and shelfmarks
3. IIIF manifests fetched directly (not blocked)

**Import Script:** `scripts/importers/parker.py --from-html`

```bash
python scripts/importers/parker.py --from-html scripts/importers/resources/parker_html/ --discover-only
python scripts/importers/parker.py --skip-discovery --execute
```

### 2. Trinity College Cambridge (Wren Library)

**Status:** In Progress - Enumeration Approach

**Technical Details:**
- **Platform:** Custom catalog (James Catalogue of Western Manuscripts)
- **Collection:** ~850 digitized medieval manuscripts
- **IIIF Support:** Yes, Presentation API v2
- **Website:** [mss-cat.trin.cam.ac.uk](https://mss-cat.trin.cam.ac.uk)
- **Manifest URL Pattern:** `https://mss-cat.trin.cam.ac.uk/manuscripts/{shelfmark}.json`
- **Viewer URL Pattern:** `https://mss-cat.trin.cam.ac.uk/manuscripts/uv/view.php?n={shelfmark}`

**Import Script:** `scripts/importers/trinity_cambridge.py`

**Current Status (2026-01-31):**
- **Imported:** 10 manuscripts (from initial Playwright test)
- **Approach:** Switched to shelfmark enumeration (Playwright discovery failed)

**Shelfmark Ranges (Known Digitized):**

Pattern: `{Letter}.{Number}.{Number}` with occasional suffixes (e.g., B.1.30A)

| Series | Ranges | Est. Count |
|--------|--------|------------|
| B.1 | B.1.1 to B.1.46 (+ B.1.30A) | ~47 |
| B.2 | B.2.1 to B.2.36 | 36 |
| B.3 | B.3.1 to B.3.35 | 35 |
| B.4 | B.4.1 to B.4.32 | 32 |
| B.5 | B.5.1 to B.5.28 | 28 |
| B.7 | B.7.1 to B.7.7 | 7 |
| B.8 | B.8.1 to B.8.12 | 12 |
| B.9 | B.9.1 to B.9.15 | 15 |
| B.10 | B.10.1 to B.10.27 | 27 |
| B.11 | B.11.1 to B.11.34 | 34 |
| B.13 | B.13.1 to B.13.30 | 30 |
| B.14 | B.14.1 to B.14.55 | 55 |
| B.15 | B.15.1 to B.15.42 | 42 |
| B.16 | B.16.1 to B.16.47 | 47 |
| B.17 | B.17.1 to B.17.42 | 42 |
| F.12 | F.12.40 to F.12.44 | 5 |
| O.1 | O.1.1 to O.1.79 | 79 |
| O.2 | O.2.1 to O.2.68 | 68 |
| O.3 | O.3.1 to O.3.63 | 63 |
| O.4 | O.4.1 to O.4.52 | 52 |
| O.5 | O.5.2 to O.5.54 | 53 |
| O.7 | O.7.1 to O.7.47 | 47 |
| O.8 | O.8.1 to O.8.37 | 37 |
| O.9 | O.9.1 to O.9.40 | 40 |
| O.10 | O.10.2 to O.10.34 | 33 |
| O.11 | O.11.2 to O.11.19 | 18 |
| R.1 | R.1.2 to R.1.92 | 91 |
| R.2 | R.2.4 to R.2.98 | 95 |
| R.3 | R.3.1 to R.3.68 | 68 |
| R.4 | R.4.1 to R.4.52 | 52 |
| R.5 | R.5.3 to R.5.46 | 44 |
| R.7 | R.7.1 to R.7.51 | 51 |
| R.8 | R.8.3 to R.8.35 | 33 |
| R.9 | R.9.8 to R.9.39 | 32 |
| R.10 | R.10.5 to R.10.15 | 11 |
| R.11 | R.11.1 to R.11.2 | 2 |
| R.13 | R.13.8 to R.13.74 | 67 |
| R.14 | R.14.1 to R.14.16 | 16 |
| R.15 | R.15.1 to R.15.55 | 55 |
| R.16 | R.16.2 to R.16.40 | 39 |
| R.17 | R.17.1 to R.17.23 | 23 |

**Total candidates:** ~1,663 (B + F + O + R series)

**Script Behavior (`scripts/importers/trinity_cambridge.py`):**
- Enumeration-based: generates all 1,663 candidates from known ranges
- Tests each shelfmark via HTTP request to manifest URL
- Rate limiting: 0.5s delay between requests
- Timeout: 30s per manifest fetch
- Checkpoint: saves progress after each item to `cache/trinity_progress.json`
- Resume: `--resume` flag skips completed and not-found shelfmarks
- No special dependencies - uses standard library `urllib`

**Usage:**
```bash
python3 scripts/importers/trinity_cambridge.py --execute           # Full run
python3 scripts/importers/trinity_cambridge.py --resume --execute  # Resume if interrupted
python3 scripts/importers/trinity_cambridge.py --test              # First 10 only
```

**Next Steps:**
1. Run full import (~1,663 candidates, ~15-20 min estimated)

### 3. John Rylands Library (University of Manchester)

**Status:** High Priority - Next Target

**Technical Details:**
- **Collection:** Major medieval manuscript collection
- **Website:** [luna.manchester.ac.uk](https://luna.manchester.ac.uk/) / [digitalcollections.manchester.ac.uk](https://www.digitalcollections.manchester.ac.uk/)
- **Platform:** Luna Imaging / Digital Collections

**Exploration Needed:**
- IIIF manifest availability
- Luna API endpoints
- Metadata field mapping
- Medieval manuscript scope

**Notable Holdings:**
- Crawford Collection of medieval manuscripts
- Latin, Greek, and vernacular manuscripts
- Significant Anglo-Saxon and Middle English texts

### 4. Trinity College Dublin

**Status:** Candidate

**Technical Details:**
- **Collection:** Digital Collections including Book of Kells
- **Website:** [digitalcollections.tcd.ie](https://digitalcollections.tcd.ie/)
- **Platform:** Custom/Luna

**Exploration Needed:**
- IIIF support confirmation
- API availability
- Manuscript scope vs. all collections

### 5. Bibliothèque nationale de France (Gallica)

**Status:** Future Consideration

**Technical Details:**
- **Collection:** Massive digitized manuscript collection
- **IIIF:** Yes, extensive support
- **API:** IIIF and SRU/OAI-PMH

**Note:** Very large collection, would need scoping to medieval manuscripts only.

### 6. e-codices (Virtual Manuscript Library of Switzerland)

**Status:** Future Consideration

**Technical Details:**
- **Collection:** Swiss manuscript libraries
- **IIIF:** Full support
- **API:** IIIF collection endpoints

---

## Workflow Summary

### Adding a New Repository (Subagent-Driven)

1. **Exploration Phase** (use Explore subagent)
   - Investigate repository website
   - Document IIIF/API infrastructure
   - Map metadata fields
   - Create technical assessment
   - **Estimate total import time** (>10 min = needs background support)

2. **Development Phase** (use general-purpose subagent)
   - Create importer script in `scripts/importers/`
   - Follow standard patterns from existing importers (e.g., `huntington.py`, `trinity_cambridge.py`)
   - **REQUIRED: Implement checkpoint/resume support**
   - **REQUIRED: Two-phase operation** (discovery → import)
   - **REQUIRED: Progress tracking** after each item
   - Implement discovery and parsing functions

3. **Testing Phase**
   - Dry-run validation
   - Test mode with verbose logging
   - **Test checkpoint/resume** (interrupt and resume)
   - Limited run verification
   - Full execution with `--execute`

4. **Sync Phase**
   - Export SQLite to MySQL format
   - Upload to oldbooks via FTP/cPanel
   - Import via phpMyAdmin
   - Verify production counts

### Background Execution (for imports >10 minutes)

For long-running imports:

```bash
# Start in background
python scripts/importers/[repo].py --execute > import_[repo].log 2>&1 &

# Monitor progress
tail -f import_[repo].log

# Or check progress file
watch -n 5 'cat scripts/importers/cache/[repo]_progress.json | jq'

# If process dies, resume
python scripts/importers/[repo].py --resume --execute
```

### Parallel Subagent Pattern

For large imports with independent sub-collections:

```
Main Agent
    ├── Subagent 1: Import Collection A
    ├── Subagent 2: Import Collection B
    └── Subagent 3: Import Collection C
```

Each subagent handles:
- Discovery for its collection
- Manifest fetching with rate limiting
- Database writes with proper locking

Coordinate via:
- Separate checkpoint files per collection
- Repository ID established before parallel work
- Final count verification after all complete

---

## Appendix: Quick Commands

### Start a new import exploration

```bash
# Explore repository (replace with actual URL)
# Use Explore subagent in Claude Code
```

### Create new importer from template

```bash
cp scripts/importers/cambridge.py scripts/importers/[newrepo].py
# Edit constants and parsing logic
```

### Full import cycle

```bash
# 1. Dry run
python scripts/importers/[repo].py

# 2. Test
python scripts/importers/[repo].py --test --verbose

# 3. Discovery only
python scripts/importers/[repo].py --discover-only

# 4. Execute (with checkpoints)
python scripts/importers/[repo].py --skip-discovery --execute

# 5. If interrupted, resume
python scripts/importers/[repo].py --resume --execute

# 6. Export
./scripts/sync_to_production.sh

# 7. Upload and import via phpMyAdmin
```

### Database verification

```bash
# Quick count by repo
sqlite3 database/compilatio.db "SELECT r.short_name, COUNT(*) FROM manuscripts m JOIN repositories r ON m.repository_id = r.id GROUP BY r.id ORDER BY COUNT(*) DESC;"
```

---

## Version History

| Date | Changes |
|------|---------|
| 2026-01-31 | Initial expansion plan created |
