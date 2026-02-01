# Production Deployment Guide

## Quick Reference

| Item | Value |
|------|-------|
| Production URL | https://oldbooks.humspace.ucla.edu |
| cPanel | https://oldbooks.humspace.ucla.edu/cpanel |
| Database | oldbooks_compilatio |
| DB User | oldbooks_compilatio_user |
| Password | (see DevonThink) |

---

## Pre-Deployment Checklist

Before deploying, verify ALL JavaScript files use production API URLs:

```bash
cd /Users/rabota/Geekery/Compilatio

# Check for problematic patterns (should return NO results)
grep -rn "'/api/" php_deploy/ --include="*.js" --include="*.html" | grep -v "index.php"

# If any results appear, those files need fixing before upload
```

**Valid patterns:**
- `/api/index.php?action=repositories` ✓
- `apiUrl('repositories')` ✓

**Invalid patterns (will break on production):**
- `/api/repositories` ✗
- `${API_BASE}/manuscripts` ✗

---

## Step 1: Export Database (if data changed)

### 1.1 Verify Local Data

```bash
cd /Users/rabota/Geekery/Compilatio

sqlite3 database/compilatio.db "
SELECT 'Repositories' as type, COUNT(*) as count FROM repositories
UNION ALL
SELECT 'Manuscripts', COUNT(*) FROM manuscripts;
"
```

### 1.2 Export for MySQL

```bash
mkdir -p mysql_export

# Repositories (simple export works)
sqlite3 database/compilatio.db ".mode insert repositories" \
  ".output mysql_export/repositories.sql" \
  "SELECT * FROM repositories;"

# Manuscripts (MUST use Python - SQLite's unistr() breaks MySQL)
python3 << 'EOF'
import sqlite3

conn = sqlite3.connect('database/compilatio.db')
cursor = conn.cursor()

def escape_mysql(val):
    if val is None:
        return 'NULL'
    if isinstance(val, (int, float)):
        return str(val)
    s = str(val)
    s = s.replace('\\', '\\\\')
    s = s.replace("'", "\\'")
    s = s.replace('\n', '\\n')
    s = s.replace('\r', '\\r')
    s = s.replace('\t', '\\t')
    return f"'{s}'"

cursor.execute("SELECT * FROM manuscripts")
rows = cursor.fetchall()

with open('mysql_export/manuscripts_mysql.sql', 'w') as f:
    for row in rows:
        values = ','.join(escape_mysql(v) for v in row)
        f.write(f"INSERT INTO manuscripts VALUES({values});\n")

print(f"Exported {len(rows)} manuscripts")
conn.close()
EOF

# Verify
wc -l mysql_export/*.sql
```

---

## Step 2: Upload Files

### 2.1 Files to Upload

Upload from `php_deploy/` to `public_html/` via cPanel File Manager:

| Local File | Remote Location |
|------------|-----------------|
| `index.html` | `public_html/index.html` |
| `browse.html` | `public_html/browse.html` |
| `about.html` | `public_html/about.html` |
| `viewer.html` | `public_html/viewer.html` |
| `css/styles.css` | `public_html/css/styles.css` |
| `js/script.js` | `public_html/js/script.js` |
| `js/browse.js` | `public_html/js/browse.js` |
| `images/border-top.jpg` | `public_html/images/border-top.jpg` |
| `images/border-right.jpg` | `public_html/images/border-right.jpg` |
| `api/index.php` | `public_html/api/index.php` |

### 2.2 Files to Create on Server (do NOT upload)

These contain credentials - create directly on server:

**`public_html/includes/config.php`** (permissions: 640)
```php
<?php
define('DB_HOST', 'localhost');
define('DB_NAME', 'oldbooks_compilatio');
define('DB_USER', 'oldbooks_compilatio_user');
define('DB_PASS', 'PASSWORD_FROM_DEVONTHINK');
define('DB_CHARSET', 'utf8mb4');

function getDbConnection() {
    static $pdo = null;
    if ($pdo === null) {
        $dsn = sprintf('mysql:host=%s;dbname=%s;charset=%s', DB_HOST, DB_NAME, DB_CHARSET);
        $options = [
            PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
            PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
            PDO::ATTR_EMULATE_PREPARES => false,
        ];
        $pdo = new PDO($dsn, DB_USER, DB_PASS, $options);
    }
    return $pdo;
}
```

**`public_html/includes/.htaccess`** (permissions: 644)
```apache
Order Allow,Deny
Deny from all
```

### 2.3 Do NOT Upload

- `.htaccess` at root level (mod_rewrite breaks the site)
- `includes/config.php` (create on server with production credentials)
- Anything from `src/` directory (wrong API URLs)

---

## Step 3: Import Database (if data changed)

### 3.1 Backup Production First

In phpMyAdmin:
1. Select database `oldbooks_compilatio`
2. Export → Quick → SQL
3. Save as `backup_YYYY-MM-DD.sql`

### 3.2 Clear Existing Data

Run in phpMyAdmin (all at once):

```sql
SET FOREIGN_KEY_CHECKS = 0;
DELETE FROM manuscripts;
DELETE FROM repositories;
SET FOREIGN_KEY_CHECKS = 1;
```

### 3.3 Import Data

1. Import `repositories.sql` first
2. Import `manuscripts_mysql.sql` second
3. Verify counts match local

---

## Step 4: Verify Deployment

### 4.1 Test URLs

| URL | Expected |
|-----|----------|
| https://oldbooks.humspace.ucla.edu/ | Landing page with featured manuscript |
| https://oldbooks.humspace.ucla.edu/browse.html | Repository list with counts |
| https://oldbooks.humspace.ucla.edu/about.html | About page with totals |
| https://oldbooks.humspace.ucla.edu/viewer.html?ms=1 | Viewer loads manuscript |
| https://oldbooks.humspace.ucla.edu/api/index.php?action=repositories | JSON array |
| https://oldbooks.humspace.ucla.edu/includes/config.php | 403 Forbidden |

### 4.2 Database Verification

In phpMyAdmin:
```sql
SELECT 'repositories' as tbl, COUNT(*) as cnt FROM repositories
UNION ALL
SELECT 'manuscripts', COUNT(*) FROM manuscripts;
```

---

## Troubleshooting

### "unistr does not exist"
You exported manuscripts with SQLite's `.mode insert`. Use the Python script instead.

### "Cannot truncate a table referenced in a foreign key"
Use `DELETE FROM` instead of `TRUNCATE TABLE`.

### 500 Internal Server Error on all pages
Delete or rename `.htaccess` in `public_html/`. The hosting doesn't support mod_rewrite.

### "Unable to load" on landing page
JavaScript is using wrong API URLs. Run the pre-deployment check and fix any files using `/api/repositories` instead of `/api/index.php?action=repositories`.

### Duplicate entry for key PRIMARY
Run `DELETE FROM manuscripts;` before importing again.

---

## Important: src/ vs php_deploy/

| Directory | Purpose | API URLs |
|-----------|---------|----------|
| `src/` | Local development (Python server) | `/api/repositories` |
| `php_deploy/` | Production (PHP/MySQL) | `/api/index.php?action=repositories` |

**NEVER copy directly from `src/` to `php_deploy/`** without updating API calls.

If you modify files in `src/`, manually port changes to `php_deploy/` and update all fetch calls to use the `apiUrl()` helper or direct `/api/index.php?action=...` URLs.

---

## Version History

| Date | Notes |
|------|-------|
| 2026-02-01 | Initial guide based on deployment lessons learned |
