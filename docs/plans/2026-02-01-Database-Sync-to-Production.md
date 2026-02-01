# Database Sync to Production: oldbooks.humspace.ucla.edu

## Overview

Safely synchronize the updated local SQLite database to the production MySQL server at `oldbooks.humspace.ucla.edu`.

### Current State

| Environment | Repositories | Manuscripts | Notes |
|-------------|--------------|-------------|-------|
| Local (SQLite) | 12 | 4,352 | Includes TCC with thumbnails fixed |
| Production (MySQL) | 9 | 3,119 | Missing: TCC (534), Parker (560), Yale (139) |

### Changes to Deploy

1. **TCC thumbnails** - 534 manuscripts now have correct thumbnail URLs
2. **New repositories** - TCC, Parker, Yale added since last sync
3. **Net new manuscripts** - 1,233 manuscripts to add

---

## Pre-Deployment Checklist

- [ ] Verify local database integrity
- [ ] Export data from SQLite
- [ ] Create backup of production MySQL
- [ ] Test import on staging (if available)
- [ ] Schedule maintenance window (optional - site is low-traffic)

---

## Step 1: Verify Local Database

Run these checks before exporting:

```bash
cd /Users/rabota/Geekery/Compilatio

# Verify counts
sqlite3 database/compilatio.db "
SELECT 'Repositories' as type, COUNT(*) as count FROM repositories
UNION ALL
SELECT 'Manuscripts', COUNT(*) FROM manuscripts
UNION ALL
SELECT 'TCC with thumbnails', COUNT(*) FROM manuscripts m
  JOIN repositories r ON m.repository_id = r.id
  WHERE r.short_name = 'TCC' AND thumbnail_url IS NOT NULL;
"

# Verify no orphaned manuscripts
sqlite3 database/compilatio.db "
SELECT COUNT(*) as orphaned FROM manuscripts m
LEFT JOIN repositories r ON m.repository_id = r.id
WHERE r.id IS NULL;
"
# Expected: 0
```

---

## Step 2: Export SQLite to MySQL Format

**Note:** SQLite's `.mode insert` uses `unistr()` for Unicode escaping, which MySQL doesn't support. Use the Python script below for MySQL-compatible output.

```bash
cd /Users/rabota/Geekery/Compilatio
mkdir -p mysql_export

# Export repositories (simple table, SQLite export works fine)
sqlite3 database/compilatio.db ".mode insert repositories" \
  ".output mysql_export/repositories.sql" \
  "SELECT * FROM repositories;"

# Export manuscripts using Python for MySQL compatibility
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

print(f"Exported {len(rows)} manuscripts to manuscripts_mysql.sql")
conn.close()
EOF

# Verify export files exist and have content
wc -l mysql_export/*.sql
```

Expected output:
- `repositories.sql`: ~12 lines (one INSERT per repository)
- `manuscripts_mysql.sql`: ~4,352 lines (one INSERT per manuscript)

---

## Step 3: Backup Production Database

Before making any changes, create a backup.

**Option A: phpMyAdmin Export (Recommended)**

1. Log in to cPanel at `oldbooks.humspace.ucla.edu/cpanel`
2. Open **phpMyAdmin**
3. Select database `oldbooks_compilatio`
4. Go to **Export** tab
5. Choose **Quick** export, format **SQL**
6. Click **Export** and save the file locally as `oldbooks_backup_2026-02-01.sql`

**Option B: SSH (if available)**

```bash
ssh oldbooks@oldbooks.humspace.ucla.edu
mysqldump -u oldbooks_compilatio_user -p oldbooks_compilatio > ~/backup_2026-02-01.sql
```

---

## Step 4: Upload Export Files

**Option A: cPanel File Manager**

1. Log in to cPanel
2. Open **File Manager**
3. Navigate to home directory (not public_html)
4. Create folder `mysql_import` if it doesn't exist
5. Upload `repositories.sql` and `manuscripts_mysql.sql`

**Option B: SCP**

```bash
scp mysql_export/repositories.sql mysql_export/manuscripts_mysql.sql oldbooks@oldbooks.humspace.ucla.edu:~/mysql_import/
```

---

## Step 5: Import to Production MySQL

**IMPORTANT:** This will replace all existing data. The production site will show stale data briefly during import.

### 5.1 Clear Existing Data

In phpMyAdmin, run all statements together as a single block:

```sql
SET FOREIGN_KEY_CHECKS = 0;
DELETE FROM manuscripts;
DELETE FROM repositories;
SET FOREIGN_KEY_CHECKS = 1;
```

**Note:** Use `DELETE` instead of `TRUNCATE`. TRUNCATE fails with FK constraint errors even with `FOREIGN_KEY_CHECKS = 0` on some MySQL configurations.

### 5.2 Import Repositories

1. Go to **Import** tab
2. Choose file: `repositories.sql`
3. Click **Import**
4. Verify: `SELECT COUNT(*) FROM repositories;` → Should return 12

### 5.3 Import Manuscripts

1. Go to **Import** tab
2. Choose file: `manuscripts_mysql.sql`
3. Click **Import**
4. Verify: `SELECT COUNT(*) FROM manuscripts;` → Should return 4,352

**Note:** Large imports may timeout. If `manuscripts_mysql.sql` fails:
- Split the file into chunks of 1000 INSERT statements each
- Import each chunk separately
- Or use command line: `mysql -u user -p database < manuscripts_mysql.sql`

---

## Step 6: Verify Production

### 6.1 Database Checks

```sql
-- Total counts
SELECT 'repositories' as tbl, COUNT(*) FROM repositories
UNION ALL
SELECT 'manuscripts', COUNT(*) FROM manuscripts;

-- TCC thumbnails populated
SELECT COUNT(*) as tcc_with_thumbs
FROM manuscripts m
JOIN repositories r ON m.repository_id = r.id
WHERE r.short_name = 'TCC' AND thumbnail_url IS NOT NULL;
-- Expected: 534

-- Sample TCC manuscript
SELECT shelfmark, thumbnail_url
FROM manuscripts m
JOIN repositories r ON m.repository_id = r.id
WHERE r.short_name = 'TCC'
LIMIT 1;
```

### 6.2 Frontend Checks

Test in browser:

1. **Landing page** - https://oldbooks.humspace.ucla.edu/
   - Featured manuscript loads
   - Repository count shows 12

2. **Browse page** - https://oldbooks.humspace.ucla.edu/browse.html
   - All 12 repositories visible
   - TCC shows 534 manuscripts

3. **TCC manuscripts** - Click Trinity College Cambridge
   - Thumbnails display correctly
   - Viewer loads for any manuscript

4. **API endpoints**
   ```bash
   curl https://oldbooks.humspace.ucla.edu/api/repositories | jq length
   # Expected: 12

   curl "https://oldbooks.humspace.ucla.edu/api/manuscripts?repository_id=11&limit=1" | jq '.manuscripts[0].thumbnail_url'
   # Expected: non-null URL for TCC
   ```

---

## Rollback Plan

If something goes wrong:

1. **Restore from backup:**
   ```sql
   SET FOREIGN_KEY_CHECKS = 0;
   TRUNCATE TABLE manuscripts;
   TRUNCATE TABLE repositories;
   SET FOREIGN_KEY_CHECKS = 1;
   ```
   Then import `oldbooks_backup_2026-02-01.sql`

2. **Verify restoration:**
   ```sql
   SELECT COUNT(*) FROM repositories;  -- Should be 9
   SELECT COUNT(*) FROM manuscripts;   -- Should be 3,119
   ```

---

---

## Step 7: Deploy PHP Files and Resources

### 7.1 Prepare Local Files

Ensure `php_deploy/` is up to date with `src/`:

```bash
cd /Users/rabota/Geekery/Compilatio

# Sync HTML/CSS/JS from src to php_deploy (if needed)
cp src/index.html php_deploy/
cp src/browse.html php_deploy/
cp src/viewer.html php_deploy/
cp src/css/styles.css php_deploy/css/
cp src/js/*.js php_deploy/js/
```

### 7.2 Upload Files via cPanel File Manager

1. Log in to cPanel at `oldbooks.humspace.ucla.edu/cpanel`
2. Open **File Manager**
3. Navigate to `public_html`

**Upload structure:**

| Local Path | Remote Path (in public_html) |
|------------|------------------------------|
| `php_deploy/.htaccess` | `.htaccess` |
| `php_deploy/index.html` | `index.html` |
| `php_deploy/browse.html` | `browse.html` |
| `php_deploy/about.html` | `about.html` |
| `php_deploy/viewer.html` | `viewer.html` |
| `php_deploy/css/styles.css` | `css/styles.css` |
| `php_deploy/js/script.js` | `js/script.js` |
| `php_deploy/js/browse.js` | `js/browse.js` |
| `php_deploy/images/border-top.jpg` | `images/border-top.jpg` |
| `php_deploy/images/border-right.jpg` | `images/border-right.jpg` |
| `php_deploy/api/index.php` | `api/index.php` |
| `php_deploy/includes/.htaccess` | `includes/.htaccess` |

### 7.3 Create config.php on Server

**Do NOT upload config.php from local** - create it directly on the server with production credentials.

1. In File Manager, navigate to `public_html/includes/`
2. Click **+ File** → name it `config.php`
3. Right-click → **Edit** and paste:

```php
<?php
define('DB_HOST', 'localhost');
define('DB_NAME', 'oldbooks_compilatio');
define('DB_USER', 'oldbooks_compilatio_user');
define('DB_PASS', 'YOUR_PASSWORD_HERE');  // See DevonThink
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

4. Save the file

### 7.4 Set File Permissions

In File Manager, right-click each item → **Change Permissions**:

| Path | Permissions |
|------|-------------|
| `includes/config.php` | 640 (owner read/write, group read) |
| `includes/.htaccess` | 644 |
| All other files | 644 |
| All directories | 755 |

### 7.5 Verify Deployment

Test in browser:

1. https://oldbooks.humspace.ucla.edu/ - Landing page loads
2. https://oldbooks.humspace.ucla.edu/browse.html - Browse page loads
3. https://oldbooks.humspace.ucla.edu/api/repositories - Returns JSON array
4. https://oldbooks.humspace.ucla.edu/includes/config.php - Should return 403 Forbidden (protected)

---

## Post-Deployment

- [ ] Delete uploaded SQL files from server: `rm ~/mysql_import/*.sql`
- [ ] Update `Oldbooks_Migration_Plan.md` with new counts
- [ ] Update `Compilatio_Project_Status.md` if needed
- [ ] Delete local backup file after confirming success

---

## Quick Reference

| Server | oldbooks.humspace.ucla.edu |
|--------|---------------------------|
| cPanel | /cpanel |
| Database | oldbooks_compilatio |
| User | oldbooks_compilatio_user |
| Password | (see DevonThink) |

---

## Version

| Date | Notes |
|------|-------|
| 2026-02-01 | Initial plan for TCC thumbnail sync + new repository data |
| 2026-02-01 | Updated counts: 4,352 manuscripts (80 Parker duplicates removed) |
| 2026-02-01 | Fixed export: Python script for MySQL-compatible SQL (SQLite unistr() not supported); use DELETE instead of TRUNCATE |
| 2026-02-01 | Added Step 7: PHP and resource file deployment instructions |
