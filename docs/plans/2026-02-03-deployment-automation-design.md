# Deployment Automation Design

**Date:** 2026-02-03
**Status:** Approved

## Overview

Automated deployment pipeline for syncing local development to production at `oldbooks.humspace.ucla.edu`. Includes source conversion, database export with validation, pre-flight checks, and SSH-based deployment.

## Architecture

```
deploy_production.sh (orchestrator)
    │
    ├── verify_deploy.py (pre-flight checks)
    │   ├── git working tree clean?
    │   ├── git synced with origin?
    │   ├── build_php.py --check (php_deploy current?)
    │   ├── export_mysql.py --check (SQL export valid?)
    │   └── SSH connectivity OK?
    │
    ├── [if checks pass] Menu: files / database / both / cancel
    │
    ├── [files] rsync php_deploy/ → production
    └── [database] scp SQL + mysql import
```

## Scripts

### 1. build_php.py

**Purpose:** Convert `src/` (Python/dev) to `php_deploy/` (PHP/prod)

**Transformations:**

| File Type | Action |
|-----------|--------|
| `*.js` | Transform API URLs, inject `apiUrl()` helper |
| `*.html` | Copy as-is |
| `*.css` | Copy as-is |
| `images/*` | Copy as-is |

**API URL Mapping:**

| Development (src/) | Production (php_deploy/) |
|--------------------|--------------------------|
| `${API_BASE}/featured` | `apiUrl('featured')` |
| `${API_BASE}/repositories` | `apiUrl('repositories')` |
| `${API_BASE}/repositories/${id}` | `apiUrl('repository', id)` |
| `${API_BASE}/manuscripts` | `apiUrl('manuscripts')` |
| `${API_BASE}/manuscripts/${id}` | `apiUrl('manuscript', id)` |

**Modes:**
- `build_php.py` — Run conversion
- `build_php.py --check` — Verify php_deploy is in sync (exit 0=current, 1=stale)

### 2. export_mysql.py

**Purpose:** Export SQLite to MySQL-compatible SQL with validation

**Output Files:**
- `mysql_export/repositories.sql`
- `mysql_export/manuscripts.sql`

**Validation Checks:**

| Check | Purpose |
|-------|---------|
| No `unistr()` | SQLite function breaks MySQL |
| Quote escaping | Single quotes as `\'` |
| Newline escaping | `\n`, `\r`, `\t` escaped |
| NULL handling | Python None → SQL NULL |
| UTF-8 validation | No invalid characters |
| Row counts | Match source database |
| Syntax check | INSERT statements parseable |

**Modes:**
- `export_mysql.py` — Run export
- `export_mysql.py --check` — Validate existing export (exit 0=valid, 1=stale/invalid)

### 3. verify_deploy.py

**Purpose:** Pre-flight checks before deployment

**Checks (in order):**

1. Git working tree clean
2. Git branch synced with origin
3. `php_deploy/` in sync with `src/`
4. `mysql_export/` valid and current
5. SSH connectivity to production

**Output Example (success):**
```
=== Compilatio Deploy Verification ===

[✓] Git working tree clean
[✓] Git synced with origin (main)
[✓] php_deploy/ in sync with src/
[✓] MySQL export valid (14 repos, 4,728 manuscripts)
[✓] SSH connection OK

All checks passed. Ready to deploy.
```

**Output Example (failure):**
```
[✓] Git working tree clean
[✗] Git synced with origin (main)
    → Local is 2 commits ahead. Run: git push

Deployment blocked. Fix issues above.
```

### 4. deploy_production.sh

**Purpose:** Orchestrator script with interactive menu

**Flow:**
1. Run `verify_deploy.py`
2. If checks fail, exit
3. Present menu: files / database / both / cancel
4. Execute selected deployment

**File Deployment:**
```bash
rsync -avz --delete \
    --exclude='includes/config.php' \
    --exclude='includes/.htaccess' \
    php_deploy/ \
    oldbooks@oldbooks.humspace.ucla.edu:~/public_html/
```

**Database Deployment:**
```bash
scp mysql_export/*.sql oldbooks@oldbooks.humspace.ucla.edu:~/mysql_import/
ssh oldbooks@oldbooks.humspace.ucla.edu '
    mysql -e "SET FOREIGN_KEY_CHECKS=0; DELETE FROM manuscripts; DELETE FROM repositories; SET FOREIGN_KEY_CHECKS=1;"
    mysql < ~/mysql_import/repositories.sql
    mysql < ~/mysql_import/manuscripts.sql
    mysql -e "SELECT COUNT(*) as repos FROM repositories; SELECT COUNT(*) as manuscripts FROM manuscripts;"
'
```

## Server Configuration

**SSH Access:**
- Host: `oldbooks.humspace.ucla.edu`
- User: `oldbooks`
- Key: `~/.ssh/id_ed25519` (authorized via manual setup in `~/.ssh/authorized_keys`)

**MySQL Access:**
- Credentials stored in `~/.my.cnf` on server
- Database: `oldbooks_compilatio`
- User: `oldbooks_compilatio_user`

## Files Excluded from Sync

| File | Reason |
|------|--------|
| `includes/config.php` | Contains production DB credentials |
| `includes/.htaccess` | Security file, already on server |

## Usage

```bash
# Full deployment workflow
./scripts/deploy_production.sh

# Individual steps (for debugging)
python3 scripts/build_php.py          # Convert src → php_deploy
python3 scripts/build_php.py --check  # Verify conversion is current

python3 scripts/export_mysql.py          # Export database
python3 scripts/export_mysql.py --check  # Verify export is current

python3 scripts/verify_deploy.py      # Run all pre-flight checks
```

## Error Handling

All scripts exit with:
- `0` — Success / checks passed
- `1` — Failure / checks failed

Error messages are written to stderr with clear remediation steps.
