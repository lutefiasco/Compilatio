# Deployment

Production deployment for Compilatio at https://oldbooks.humspace.ucla.edu.

## Quick Reference

| Item | Value |
|------|-------|
| Production URL | https://oldbooks.humspace.ucla.edu |
| cPanel | https://oldbooks.humspace.ucla.edu/cpanel |
| Database | oldbooks_compilatio |
| DB User | oldbooks_compilatio_user |
| Password | (see DevonThink) |
| SSH | `oldbooks@oldbooks.humspace.ucla.edu` |

---

## Deploying

```bash
./scripts/deploy_production.sh          # interactive: choose files, db, or both
./scripts/deploy_production.sh both     # non-interactive full deploy
./scripts/deploy_production.sh files    # files only
./scripts/deploy_production.sh db       # database only
```

The script runs pre-flight checks, then deploys. Pre-requisites:
- SSH key authorized on server (`~/.ssh/id_ed25519`, added manually to `~/.ssh/authorized_keys` on server -- cPanel SSH key manager doesn't work)
- `~/.my.cnf` configured on server for passwordless MySQL access

---

## Architecture

```
deploy_production.sh (orchestrator)
    |
    +-- build_php.py         convert src/ -> php_deploy/
    +-- verify_deploy.py     pre-flight checks
    |     +-- git tracked files clean?       (untracked files ignored)
    |     +-- git synced with origin?
    |     +-- build_php.py --check           (php_deploy/ current?)
    |     +-- export_mysql.py --check        (SQL export valid?)
    |     +-- SSH connectivity?
    |
    +-- [files]  rsync php_deploy/ -> public_html/
    +-- [db]     scp SQL files + mysql import
```

### File deployment

```bash
rsync -avz --delete \
    --exclude='includes/config.php' \
    --exclude='includes/.htaccess' \
    php_deploy/ oldbooks@oldbooks.humspace.ucla.edu:~/public_html/
```

The `--delete` flag removes files on production that don't exist locally. Two files are excluded because they contain production credentials and security rules that are created on the server.

### Database deployment

Each SQL file is wrapped in `START TRANSACTION;` / `COMMIT;`, so a partial failure (network drop, encoding error) rolls back cleanly rather than leaving production with missing data.

The deploy script:
1. Uploads `mysql_export/repositories.sql` and `mysql_export/manuscripts.sql` to the server
2. Clears existing data (`DELETE FROM manuscripts; DELETE FROM repositories;`)
3. Imports repositories first, then manuscripts
4. Verifies counts

---

## Individual Scripts

### build_php.py

Syncs `src/` to `php_deploy/` for production deployment.

```bash
python3 scripts/build_php.py          # run sync
python3 scripts/build_php.py --check  # verify php_deploy/ is in sync
```

All files are copied as-is — no transformation. Production API routing is handled entirely by `.htaccess` mod_rewrite rules. The script skips PHP-only files (`api/index.php`, `includes/config.php`, `.htaccess`) that live only in `php_deploy/`.

### export_mysql.py

Exports SQLite database to MySQL-compatible SQL files.

```bash
python3 scripts/export_mysql.py          # run export
python3 scripts/export_mysql.py --check  # verify existing export is current
```

**Output:** `mysql_export/repositories.sql` and `mysql_export/manuscripts.sql`

**Format:**
- Batched INSERTs (100 rows per statement) for fast import
- Transaction-wrapped (`START TRANSACTION;` / `COMMIT;`)
- MySQL-compatible escaping (quotes, newlines, null bytes, backslashes, Unicode)

**Validation checks:**
- No SQLite-specific functions (`unistr()`, `julianday()`, etc.)
- Row counts match source database
- No broken lines inside value tuples

### verify_deploy.py

Pre-flight checks before deployment.

```bash
python3 scripts/verify_deploy.py
```

Checks (in order):
1. Git tracked files clean (untracked files are ignored and reported informatively)
2. Git branch synced with origin
3. `php_deploy/` in sync with `src/`
4. MySQL export valid and current
5. SSH connectivity to production

---

## src/ vs php_deploy/

| Directory | Backend | Database | API URLs |
|-----------|---------|----------|----------|
| `src/` | Python/Starlette | SQLite | REST-style (`/api/repositories`) |
| `php_deploy/` | PHP | MySQL | Mixed (see below) |

**NEVER edit php_deploy/ directly.** Always edit `src/` and run `python3 scripts/build_php.py`.

---

## Known Issues

### Dependency on mod_rewrite

All frontend files use REST-style API paths (`/api/repositories`, `${API_BASE}/manuscripts/123`). These are rewritten to `api/index.php?action=...` by `.htaccess` mod_rewrite rules. If mod_rewrite is ever disabled on Humspace, all API calls will fail. The `.htaccess` file is deployed via rsync and lives in `php_deploy/.htaccess`.

### Schema changes require manual MySQL ALTER

`export_mysql.py` exports data only (INSERT statements), not schema (CREATE TABLE). If a column is added to the SQLite schema, the corresponding MySQL table must be manually ALTERed before importing, or the INSERT will fail. A future improvement would be to add schema-diff checking (or schema export) to `export_mysql.py` so it warns when the two schemas diverge. Not yet needed — the schema hasn't changed since initial deployment.

### No automated rollback

The deploy script does a full wipe-and-reload for the database. If you need to roll back, you must have a backup. Before deploying, consider:

```bash
ssh oldbooks@oldbooks.humspace.ucla.edu 'mysqldump oldbooks_compilatio > ~/backup_$(date +%Y%m%d).sql'
```

---

## Server-Side Configuration

These files exist only on the server and are excluded from rsync:

**`public_html/includes/config.php`** (permissions: 640) -- MySQL credentials and PDO connection factory. See `php_deploy/includes/config.php.example` for the template.

**`public_html/includes/.htaccess`** (permissions: 644) -- Denies direct HTTP access to the includes directory.

**`~/.my.cnf`** -- MySQL credentials for passwordless CLI access (used by the deploy script's remote import).

---

## Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| `unistr does not exist` | Exported with SQLite's `.mode insert` | Use `python3 scripts/export_mysql.py` |
| `Cannot truncate a table referenced in a foreign key` | FK constraints | Use `DELETE FROM` instead of `TRUNCATE TABLE` |
| 500 Internal Server Error on all pages | `.htaccess` mod_rewrite issue | Temporarily rename `.htaccess` to restore site, then debug rules |
| "Unable to load" on landing page | API errors | Check browser console; verify mod_rewrite is active |
| `Duplicate entry for key PRIMARY` | Data not cleared before import | Run `DELETE FROM manuscripts; DELETE FROM repositories;` first |

---

## Historical Planning Documents

These dated documents record specific deployment events and design decisions:
- `docs/plans/2026-02-01-Database-Sync-to-Production.md` -- original manual sync plan (superseded by automation)
- `docs/plans/2026-02-03-deployment-automation-design.md` -- design spec for the automated scripts
- `docs/plans/Production-Deployment-Guide.md` -- earlier deployment guide (superseded by this file)
