# Security Review — February 2026

Review of the Compilatio PHP/MySQL production setup at `oldbooks.humspace.ucla.edu`.

## Summary

The codebase has strong fundamentals: PDO prepared statements prevent SQL injection, client-side escaping prevents XSS, and credentials are properly gitignored. This review addresses missing hardening layers.

## Deployment Pipeline & Rollback

Each fix below is implemented as a **separate git commit**. To roll back any individual change:

```bash
# 1. On the serving machine, identify the commit to revert
git log --oneline

# 2. Revert the specific commit
git revert <commit-hash>

# 3. Rebuild php_deploy/ from src/ (in case viewer.html was affected)
python3 scripts/build_php.py

# 4. Redeploy to production
./scripts/deploy_production.sh
# Choose "Files only" (option 1) — database is not affected by these changes
```

**How the pipeline handles these files:**
- `php_deploy/.htaccess` — synced directly via rsync to `public_html/.htaccess`
- `php_deploy/api/index.php` — synced directly via rsync to `public_html/api/index.php`
- `src/viewer.html` — built into `php_deploy/viewer.html` by `build_php.py`, then synced via rsync
- `includes/config.php` and `includes/.htaccess` — **excluded** from rsync, never overwritten on production

**Key detail:** The deploy script uses `rsync --delete`, so reverting a commit locally and redeploying will restore the previous version on production.

---

## What's Already Solid

| Area | Status | Details |
|------|--------|---------|
| SQL Injection | Protected | PDO prepared statements with `ATTR_EMULATE_PREPARES => false` throughout |
| XSS | Protected | DOM-based `escapeHtml()`/`esc()` using `textContent` in all JS files |
| Credentials in Git | Protected | `config.php` in `.gitignore`, never committed |
| Includes Directory | Protected | `includes/.htaccess` denies all direct access |
| Directory Listing | Disabled | `Options -Indexes` in root `.htaccess` |
| Error Disclosure | Handled | Generic "Database error" to client, details to `error_log` only |
| Pagination Limits | Capped | `limit` capped at 200 in `getManuscripts()` |

---

## Fix 1: HTTP Security Headers

**File:** `php_deploy/.htaccess`
**Commit message prefix:** `security: add HTTP security headers`
**Risk:** LOW — if `mod_headers` is not enabled on Humspace, Apache will return a 500 error.

**Change:** Add standard security headers:
- `X-Content-Type-Options: nosniff` — prevents MIME-type sniffing
- `X-Frame-Options: SAMEORIGIN` — prevents clickjacking
- `Referrer-Policy: strict-origin-when-cross-origin` — limits referrer leakage
- `Permissions-Policy` — disables unused browser APIs

**Also removes** the `<Files "config.php">` directive from root `.htaccess`. This directive only protects a `config.php` in the document root (which doesn't exist); the actual `includes/config.php` is protected by `includes/.htaccess`. Removing it eliminates false confidence.

**Rollback:** `git revert <hash>` restores the previous `.htaccess`. Redeploy.

**Verify after deploy:**
```bash
curl -sI https://oldbooks.humspace.ucla.edu/ | grep -iE 'x-content|x-frame|referrer|permissions'
```
If headers appear, the fix is working. If the site returns 500, `mod_headers` may not be available — revert immediately.

---

## Fix 2: Restrict CORS Origin

**File:** `php_deploy/api/index.php`
**Commit message prefix:** `security: restrict CORS to production origin`
**Risk:** LOW — only breaks if there's a legitimate cross-origin consumer of the API.

**Change:** Replace `Access-Control-Allow-Origin: *` with `Access-Control-Allow-Origin: https://oldbooks.humspace.ucla.edu`.

The open `*` CORS header allows any website to make API requests through a visitor's browser. Since the API is only consumed by the site's own frontend, restricting to the production origin is correct.

**Rollback:** `git revert <hash>` restores `*`. Redeploy.

**Verify after deploy:**
```bash
curl -sI https://oldbooks.humspace.ucla.edu/api/repositories | grep -i access-control
# Should show: Access-Control-Allow-Origin: https://oldbooks.humspace.ucla.edu
```

---

## Fix 3: Validate API Input Bounds

**File:** `php_deploy/api/index.php`
**Commit message prefix:** `security: validate limit/offset bounds`
**Risk:** MINIMAL — only changes behavior for invalid inputs (negative numbers).

**Change:** In `getManuscripts()`, enforce `limit >= 1` and `offset >= 0`:
```php
$limit = max(1, min((int)($params['limit'] ?? 50), 200));
$offset = max(0, (int)($params['offset'] ?? 0));
```

Previously, negative values would cause MySQL errors (caught by try/catch, but generating noise in error logs).

**Rollback:** `git revert <hash>`. Redeploy.

**Verify:** Existing API behavior for normal requests is unchanged. Test edge cases:
```bash
curl -s 'https://oldbooks.humspace.ucla.edu/api/manuscripts?limit=-1' | head
# Should return valid JSON with limit=1, not an error
```

---

## Fix 4: Subresource Integrity for CDN Scripts

**File:** `src/viewer.html` (propagates to `php_deploy/viewer.html` via `build_php.py`)
**Commit message prefix:** `security: add SRI for OpenSeadragon CDN`
**Risk:** MEDIUM — if jsDelivr changes the file (even a CDN edge issue), the script will be blocked and the viewer won't work. This is the intended security behavior.

**Change:** Add `integrity` and `crossorigin="anonymous"` attributes to the OpenSeadragon `<script>` tag. The SHA-384 hash is computed from the actual CDN file.

**Rollback:** `git revert <hash>`, then `python3 scripts/build_php.py`, then redeploy. The viewer will work again without SRI checking.

**Verify after deploy:** Open any manuscript in the viewer. If images load and zoom works, SRI passed. If the viewer is blank, check the browser console for an integrity mismatch — and revert.

---

## Deferred Items (Require Server Access)

These cannot be fixed via local file edits:

### MySQL User Privileges
The `oldbooks_compilatio_user` account should ideally have `SELECT`-only privileges, since the API is read-only. Check with:
```sql
SHOW GRANTS FOR 'oldbooks_compilatio_user'@'localhost';
```
If it has `INSERT`/`UPDATE`/`DELETE`/`DROP`, restrict to `SELECT` on the `oldbooks_compilatio` database.

### HSTS Header
`Strict-Transport-Security` should be added once HTTPS is confirmed as mandatory on Humspace. Adding HSTS on a site that sometimes serves HTTP can lock users out.

### Rate Limiting
No rate limiting exists on the API. Options depend on what Apache modules are available on Humspace (`mod_ratelimit`, `mod_evasive`). Low priority given the read-only nature and small dataset.

---

## Commit Log

After implementation, this section will list the exact commit hashes for each fix:

| Fix | Commit | Files |
|-----|--------|-------|
| 1. Security headers | `6ffbc34` | `php_deploy/.htaccess` |
| 2. CORS restriction | `91310bd` | `php_deploy/api/index.php` |
| 3. Input validation | `0396905` | `php_deploy/api/index.php` |
| 4. SRI for CDN | `d1f394c` | `src/viewer.html`, `php_deploy/viewer.html` |
