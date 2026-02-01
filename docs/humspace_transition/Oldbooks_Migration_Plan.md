# Compilatio Migration Plan: oldbooks.humspace.ucla.edu

## Overview

This document details the migration of Compilatio from a local Python/Starlette development environment to UCLA's Humspace cPanel shared hosting at `oldbooks.humspace.ucla.edu`.

### Current Stack
| Component | Technology |
|-----------|------------|
| Backend | Python 3.x / Starlette / Uvicorn |
| Database | SQLite 3 |
| Frontend | Vanilla HTML/CSS/JavaScript |
| Viewer | OpenSeadragon 4.1.1 (CDN) |

### Target Stack
| Component | Technology |
|-----------|------------|
| Backend | PHP 8.x (via Apache PHP-FPM) |
| Database | MySQL 8.0.45 |
| Frontend | Vanilla HTML/CSS/JavaScript (unchanged) |
| Viewer | OpenSeadragon 4.1.1 (CDN, unchanged) |

### Data Summary
- **Repositories:** 9 (Bodleian, CUL, Durham, NLW, BL, UCLA, NLS, Lambeth, Huntington)
- **Manuscripts:** 3,119
- **Database size:** ~2 MB
- **Thumbnails:** All repositories have correct thumbnail URLs (Bodleian thumbnails fixed 2026-01-28)

---

## Server Information

| Property | Value |
|----------|-------|
| Server Name | ucla01 |
| Hosting Package | Humspace |
| cPanel Version | 132.0 (build 21) |
| Apache Version | 2.4.66 |
| PHP | Available (PHP-FPM) |
| MySQL Version | 8.0.45 |
| Python | Not available |
| SSH Access | Available (sshd running) |
| FTP Access | Available (ftpd running) |

---

## Phase 1: Database Setup in cPanel

### 1.1 Create MySQL Database

1. Log in to cPanel at `oldbooks.humspace.ucla.edu/cpanel` (or via Humspace dashboard)

2. Navigate to **Databases → MySQL Databases**

3. Under "Create New Database":
   - Enter database name: `compilatio`
   - Click "Create Database"
   - Note: The full name will be prefixed with your username (e.g., `username_compilatio`)
   - **oldbooks_compilatio**
   
4. Under "MySQL Users → Add New User":
   - Username: `compilatio_user` (will become `username_compilatio_user`)
   - **oldbooks_compilatio_user**
   - Password: Generate a strong password and **save it securely**
   - See DevonThink
   - Click "Create User"
   
5. Under "Add User To Database":
   - Select the user you created
   - Select the database you created
   - Click "Add"
   - On the privileges page, check **ALL PRIVILEGES**
   - Click "Make Changes"

### 1.2 Record Database Credentials

Create a secure note with these values (you'll need them for `config.php`):

```
DB_HOST=localhost
DB_NAME=username_compilatio
DB_USER=username_compilatio_user
DB_PASS=your_secure_password
```

---

## Phase 2: Database Schema Migration

### 2.1 SQLite to MySQL Schema Differences

| SQLite | MySQL Equivalent |
|--------|------------------|
| `INTEGER PRIMARY KEY AUTOINCREMENT` | `INT AUTO_INCREMENT PRIMARY KEY` |
| `TEXT` | `TEXT` or `VARCHAR(n)` |
| `DATETIME DEFAULT CURRENT_TIMESTAMP` | `TIMESTAMP DEFAULT CURRENT_TIMESTAMP` |
| `UNIQUE(col1, col2)` | `UNIQUE KEY key_name (col1, col2)` |
| No `ENGINE` specification | `ENGINE=InnoDB DEFAULT CHARSET=utf8mb4` |

### 2.2 MySQL Schema

Create the following schema in phpMyAdmin (or via SQL file import):

```sql
-- Compilatio MySQL Schema
-- Converted from SQLite for cPanel hosting

-- Drop tables if they exist (for clean reinstall)
DROP TABLE IF EXISTS manuscripts;
DROP TABLE IF EXISTS repositories;

-- Repositories table
CREATE TABLE repositories (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    short_name VARCHAR(100),
    logo_url TEXT,
    catalogue_url TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Manuscripts table
CREATE TABLE manuscripts (
    id INT AUTO_INCREMENT PRIMARY KEY,
    repository_id INT NOT NULL,
    shelfmark VARCHAR(255) NOT NULL,
    collection VARCHAR(255),
    date_display VARCHAR(255),
    date_start INT,
    date_end INT,
    contents TEXT,
    provenance TEXT,
    language VARCHAR(100),
    folios VARCHAR(100),
    iiif_manifest_url TEXT NOT NULL,
    thumbnail_url TEXT,
    source_url TEXT,
    image_count INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (repository_id) REFERENCES repositories(id) ON DELETE CASCADE,
    UNIQUE KEY unique_repo_shelfmark (repository_id, shelfmark),
    INDEX idx_repository_id (repository_id),
    INDEX idx_shelfmark (shelfmark),
    INDEX idx_collection (collection)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

**MNF COMPLETE**

### 2.3 Export Data from SQLite

Run these commands locally to export data as MySQL-compatible INSERT statements:

```bash
# Export repositories
sqlite3 database/compilatio.db <<EOF
.mode insert repositories
SELECT * FROM repositories;
EOF > mysql_repositories.sql

# Export manuscripts
sqlite3 database/compilatio.db <<EOF
.mode insert manuscripts
SELECT * FROM manuscripts;
EOF > mysql_manuscripts.sql
```

**Note:** SQLite's `.mode insert` output may need minor adjustments:
- Replace `NULL` values if they appear as empty strings
- Ensure proper escaping of special characters in TEXT fields
- The INSERT statements should be compatible with MySQL
- Thumbnail URLs are already correct in the database (no post-migration fixes needed)

### 2.4 Import Data to MySQL

1. Open **phpMyAdmin** from cPanel

2. Select your database (`username_compilatio`)

3. Go to the **Import** tab

4. Import in this order:
   1. First: `mysql_schema.sql` (creates tables)
   2. Second: `mysql_repositories.sql` (8 rows)
   3. Third: `mysql_manuscripts.sql` (3,119 rows)

5. Verify import:
   ```sql
   SELECT COUNT(*) FROM repositories;  -- Should return 9
   SELECT COUNT(*) FROM manuscripts;   -- Should return 3119
   ```

---

## Phase 3: PHP Backend Development

### 3.1 File Structure

```
public_html/                          # Web root (or subdomain root)
│
├── .htaccess                         # URL rewriting rules
├── index.html                        # Landing page
├── browse.html                       # Browse page
├── viewer.html                       # Manuscript viewer
│
├── api/
│   └── index.php                     # All API endpoints
│
├── includes/
│   └── config.php                    # Database configuration
│
├── css/
│   └── styles.css                    # Main stylesheet
│
├── js/
│   ├── script.js                     # Landing page JS
│   └── browse.js                     # Browse page JS
│
└── images/
    ├── border-top.jpg                # Decorative border
    └── border-right.jpg              # Decorative border
```

### 3.2 Configuration File

**File: `includes/config.php`**

```php
<?php
/**
 * Compilatio Database Configuration
 *
 * SECURITY: This file should be placed outside public_html if possible,
 * or protected via .htaccess to prevent direct access.
 */

define('DB_HOST', 'localhost');
define('DB_NAME', 'username_compilatio');      // Replace with actual
define('DB_USER', 'username_compilatio_user'); // Replace with actual
define('DB_PASS', 'your_secure_password');     // Replace with actual
define('DB_CHARSET', 'utf8mb4');

/**
 * Get PDO database connection
 */
function getDbConnection() {
    static $pdo = null;

    if ($pdo === null) {
        $dsn = sprintf(
            'mysql:host=%s;dbname=%s;charset=%s',
            DB_HOST,
            DB_NAME,
            DB_CHARSET
        );

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

### 3.3 API Endpoint Handler

**File: `api/index.php`**

```php
<?php
/**
 * Compilatio API
 *
 * Endpoints:
 *   GET /api/repositories          - List all repositories with counts
 *   GET /api/repositories/{id}     - Single repository with collections
 *   GET /api/manuscripts           - List manuscripts (with filtering)
 *   GET /api/manuscripts/{id}      - Single manuscript details
 *   GET /api/featured              - Random featured manuscript
 */

header('Content-Type: application/json; charset=utf-8');
header('Access-Control-Allow-Origin: *');

require_once __DIR__ . '/../includes/config.php';

// Get action from rewritten URL or query param
$action = $_GET['action'] ?? 'unknown';
$id = isset($_GET['id']) ? (int)$_GET['id'] : null;

try {
    $pdo = getDbConnection();

    switch ($action) {
        case 'repositories':
            echo json_encode(getRepositories($pdo));
            break;

        case 'repository':
            if (!$id) {
                http_response_code(400);
                echo json_encode(['error' => 'Repository ID required']);
                break;
            }
            $result = getRepository($pdo, $id);
            if (!$result) {
                http_response_code(404);
                echo json_encode(['error' => 'Repository not found']);
            } else {
                echo json_encode($result);
            }
            break;

        case 'manuscripts':
            echo json_encode(getManuscripts($pdo, $_GET));
            break;

        case 'manuscript':
            if (!$id) {
                http_response_code(400);
                echo json_encode(['error' => 'Manuscript ID required']);
                break;
            }
            $result = getManuscript($pdo, $id);
            if (!$result) {
                http_response_code(404);
                echo json_encode(['error' => 'Manuscript not found']);
            } else {
                echo json_encode($result);
            }
            break;

        case 'featured':
            $result = getFeatured($pdo);
            if (!$result) {
                http_response_code(404);
                echo json_encode(['error' => 'No manuscripts available']);
            } else {
                echo json_encode($result);
            }
            break;

        default:
            http_response_code(404);
            echo json_encode(['error' => 'Unknown endpoint']);
    }

} catch (PDOException $e) {
    http_response_code(500);
    echo json_encode(['error' => 'Database error']);
    // Log error for debugging (don't expose to client)
    error_log('Compilatio API Error: ' . $e->getMessage());
}

/**
 * List all repositories with manuscript counts
 */
function getRepositories(PDO $pdo): array {
    $stmt = $pdo->query("
        SELECT
            r.id, r.name, r.short_name, r.logo_url, r.catalogue_url,
            COUNT(m.id) as manuscript_count
        FROM repositories r
        LEFT JOIN manuscripts m ON m.repository_id = r.id
        GROUP BY r.id
        ORDER BY r.name
    ");
    return $stmt->fetchAll();
}

/**
 * Get single repository with its collections
 */
function getRepository(PDO $pdo, int $id): ?array {
    // Get repository
    $stmt = $pdo->prepare("SELECT * FROM repositories WHERE id = ?");
    $stmt->execute([$id]);
    $repo = $stmt->fetch();

    if (!$repo) {
        return null;
    }

    // Get collections with counts
    $stmt = $pdo->prepare("
        SELECT collection, COUNT(*) as count
        FROM manuscripts
        WHERE repository_id = ? AND collection IS NOT NULL
        GROUP BY collection
        ORDER BY collection
    ");
    $stmt->execute([$id]);

    $repo['collections'] = [];
    while ($row = $stmt->fetch()) {
        $repo['collections'][] = [
            'name' => $row['collection'],
            'count' => (int)$row['count']
        ];
    }

    return $repo;
}

/**
 * List manuscripts with optional filtering
 */
function getManuscripts(PDO $pdo, array $params): array {
    $repoId = isset($params['repository_id']) ? (int)$params['repository_id'] : null;
    $collection = $params['collection'] ?? null;
    $limit = min((int)($params['limit'] ?? 50), 200);
    $offset = (int)($params['offset'] ?? 0);

    // Build WHERE clause
    $where = [];
    $bindings = [];

    if ($repoId) {
        $where[] = 'm.repository_id = ?';
        $bindings[] = $repoId;
    }

    if ($collection !== null) {
        $where[] = 'm.collection = ?';
        $bindings[] = $collection;
    }

    $whereSQL = $where ? 'WHERE ' . implode(' AND ', $where) : '';

    // Get total count
    $countSQL = "SELECT COUNT(*) as total FROM manuscripts m $whereSQL";
    $stmt = $pdo->prepare($countSQL);
    $stmt->execute($bindings);
    $total = (int)$stmt->fetch()['total'];

    // Get manuscripts
    $sql = "
        SELECT
            m.id, m.shelfmark, m.collection, m.date_display,
            m.contents, m.thumbnail_url, m.iiif_manifest_url,
            r.short_name as repository
        FROM manuscripts m
        JOIN repositories r ON r.id = m.repository_id
        $whereSQL
        ORDER BY m.collection, m.shelfmark
        LIMIT ? OFFSET ?
    ";

    $stmt = $pdo->prepare($sql);
    $stmt->execute(array_merge($bindings, [$limit, $offset]));
    $manuscripts = $stmt->fetchAll();

    return [
        'total' => $total,
        'limit' => $limit,
        'offset' => $offset,
        'manuscripts' => $manuscripts
    ];
}

/**
 * Get single manuscript with full details
 */
function getManuscript(PDO $pdo, int $id): ?array {
    $stmt = $pdo->prepare("
        SELECT
            m.*,
            r.name as repository_name,
            r.short_name as repository_short,
            r.logo_url as repository_logo,
            r.catalogue_url as repository_catalogue
        FROM manuscripts m
        JOIN repositories r ON r.id = m.repository_id
        WHERE m.id = ?
    ");
    $stmt->execute([$id]);
    return $stmt->fetch() ?: null;
}

/**
 * Get a random featured manuscript
 */
function getFeatured(PDO $pdo): ?array {
    $stmt = $pdo->query("
        SELECT
            m.id, m.shelfmark, m.collection, m.date_display,
            m.contents, m.thumbnail_url, m.iiif_manifest_url,
            r.short_name as repository
        FROM manuscripts m
        JOIN repositories r ON r.id = m.repository_id
        WHERE m.thumbnail_url IS NOT NULL
        ORDER BY RAND()
        LIMIT 1
    ");
    return $stmt->fetch() ?: null;
}
```

### 3.4 URL Rewriting

**File: `.htaccess`** (in web root)

```apache
# Compilatio .htaccess
# URL rewriting for clean API URLs

RewriteEngine On

# Prevent direct access to config file
<Files "config.php">
    Order Allow,Deny
    Deny from all
</Files>

# API URL Rewriting
# /api/repositories -> api/index.php?action=repositories
RewriteRule ^api/repositories$ api/index.php?action=repositories [L,QSA]

# /api/repositories/123 -> api/index.php?action=repository&id=123
RewriteRule ^api/repositories/([0-9]+)$ api/index.php?action=repository&id=$1 [L,QSA]

# /api/manuscripts -> api/index.php?action=manuscripts
RewriteRule ^api/manuscripts$ api/index.php?action=manuscripts [L,QSA]

# /api/manuscripts/123 -> api/index.php?action=manuscript&id=$1
RewriteRule ^api/manuscripts/([0-9]+)$ api/index.php?action=manuscript&id=$1 [L,QSA]

# /api/featured -> api/index.php?action=featured
RewriteRule ^api/featured$ api/index.php?action=featured [L,QSA]

# Prevent directory listing
Options -Indexes

# Default charset
AddDefaultCharset UTF-8
```

### 3.5 Protect Includes Directory

**File: `includes/.htaccess`**

```apache
# Deny all direct access to this directory
Order Allow,Deny
Deny from all
```

---

## Phase 4: Frontend Files

### 4.1 Files to Upload

No modifications needed to the frontend files. The API URLs remain the same (`/api/*`).

Upload these files from `src/` to the web root:

| Local Path | Server Path |
|------------|-------------|
| `src/index.html` | `public_html/index.html` |
| `src/browse.html` | `public_html/browse.html` |
| `src/viewer.html` | `public_html/viewer.html` |
| `src/css/styles.css` | `public_html/css/styles.css` |
| `src/js/script.js` | `public_html/js/script.js` |
| `src/js/browse.js` | `public_html/js/browse.js` |
| `src/images/border-top.jpg` | `public_html/images/border-top.jpg` |
| `src/images/border-right.jpg` | `public_html/images/border-right.jpg` |

### 4.2 Directory Structure Verification

After upload, the server should have:

```
public_html/
├── .htaccess              ← NEW (URL rewriting)
├── index.html             ← FROM src/
├── browse.html            ← FROM src/
├── viewer.html            ← FROM src/
├── api/
│   └── index.php          ← NEW (PHP API)
├── includes/
│   ├── .htaccess          ← NEW (protect directory)
│   └── config.php         ← NEW (database config)
├── css/
│   └── styles.css         ← FROM src/css/
├── js/
│   ├── script.js          ← FROM src/js/
│   └── browse.js          ← FROM src/js/
└── images/
    ├── border-top.jpg     ← FROM src/images/
    └── border-right.jpg   ← FROM src/images/
```

---

## Phase 5: Deployment Process

### 5.1 Pre-Deployment Checklist

- [x] MySQL database created in cPanel (`oldbooks_compilatio`)
- [x] Database user created and granted privileges (`oldbooks_compilatio_user`)
- [x] Database credentials recorded securely
- [x] MySQL schema file prepared (`mysql_schema.sql`)
- [x] Data export from SQLite completed (`mysql_repositories.sql`, `mysql_manuscripts.sql`)
- [x] Data imported to MySQL (9 repositories, 3,119 manuscripts)
- [x] PHP files created (`php_deploy/` directory)
- [x] Files uploaded to server (via cPanel File Manager zip upload)
- [x] Site tested and verified working (2026-01-29)

### 5.2 Upload Files

All deployment files are prepared in `php_deploy/` directory locally.

**Option A: cPanel File Manager with Zip (RECOMMENDED)**

1. Create zip file locally:
   ```bash
   cd php_deploy && zip -r ../compilatio_deploy.zip . && cd ..
   ```
2. Log in to cPanel → **File Manager**
3. Navigate to `public_html`
4. Upload `compilatio_deploy.zip`
5. Select the zip file → click **Extract**
6. Delete the zip file after extraction

**Option B: cPanel File Manager (Manual)**

1. Log in to cPanel → **File Manager**
2. Navigate to `public_html`
3. Create directories: `api/`, `includes/`, `css/`, `js/`, `images/`
4. Upload files to appropriate directories from `php_deploy/`
5. Ensure `.htaccess` files are uploaded (may need to enable "Show Hidden Files")

**Option C: FTP Client**

1. Connect using FTP credentials from cPanel
2. Host: `oldbooks.humspace.ucla.edu` or server IP
3. Port: 21
4. Upload contents of `php_deploy/` to `public_html/`

**Option D: Terminal (SSH)**

Note: SSH access on Humspace may be restricted or use non-standard ports.

```bash
scp -r php_deploy/* oldbooks@oldbooks.humspace.ucla.edu:~/public_html/
```

### 5.3 Import Database

1. Open **phpMyAdmin** from cPanel
2. Select your database
3. Go to **Import** tab
4. Upload and execute:
   - `mysql_schema.sql` first
   - `mysql_repositories.sql` second
   - `mysql_manuscripts.sql` third
5. Verify with: `SELECT COUNT(*) FROM manuscripts;`

### 5.4 Configure Database Connection

1. Edit `includes/config.php`
2. Replace placeholder values with actual credentials:
   ```php
   define('DB_NAME', 'actualuser_compilatio');
   define('DB_USER', 'actualuser_compilatio_user');
   define('DB_PASS', 'actual_password_here');
   ```

### 5.5 Set File Permissions

In cPanel File Manager (right-click → Change Permissions) or via SSH:

| File/Directory | Permission |
|----------------|------------|
| All directories | 755 |
| `.php` files | 644 |
| `.html` files | 644 |
| `.css` files | 644 |
| `.js` files | 644 |
| `includes/config.php` | 600 or 640 |
| `images/*` | 644 |

---

## Phase 6: Testing

**Status: COMPLETE (2026-01-29)**
- API endpoints verified working
- Landing page loads (200 OK)
- Browse page loads (200 OK)
- config.php protected (403 Forbidden)

### 6.1 API Endpoint Tests

Test each endpoint in a browser or with `curl`:

```bash
# List repositories
curl https://oldbooks.humspace.ucla.edu/api/repositories

# Single repository (replace 1 with actual ID)
curl https://oldbooks.humspace.ucla.edu/api/repositories/1

# List manuscripts
curl https://oldbooks.humspace.ucla.edu/api/manuscripts

# Manuscripts filtered by repository
curl "https://oldbooks.humspace.ucla.edu/api/manuscripts?repository_id=1&limit=10"

# Single manuscript
curl https://oldbooks.humspace.ucla.edu/api/manuscripts/1

# Featured manuscript
curl https://oldbooks.humspace.ucla.edu/api/featured
```

Expected responses:
- 200 OK with JSON data
- Proper `Content-Type: application/json` header
- No PHP errors or warnings in response

### 6.2 Frontend Functional Tests

| Test | Steps | Expected Result |
|------|-------|-----------------|
| Landing page loads | Visit `/` | See featured manuscript, repository cards, stats |
| Featured manuscript | Refresh landing page | Different manuscript each time |
| Repository list | Click "Browse" or visit `/browse.html` | See 8 repositories with counts |
| Collections view | Click a repository | See list of collections |
| Manuscripts view | Click a collection | See manuscript grid with thumbnails |
| Manuscript viewer | Click a manuscript | OpenSeadragon viewer loads IIIF manifest |
| Pagination | Navigate to collection with >24 items | Prev/Next buttons work |
| Browser navigation | Use back/forward buttons | State preserved correctly |
| Deep linking | Direct link to `/browse.html?repo=1&collection=Name` | Correct view loads |

### 6.3 Error Handling Tests

| Test | Steps | Expected Result |
|------|-------|-----------------|
| Invalid repository | Visit `/api/repositories/99999` | 404 with JSON error |
| Invalid manuscript | Visit `/api/manuscripts/99999` | 404 with JSON error |
| Unknown endpoint | Visit `/api/unknown` | 404 with JSON error |

### 6.4 Performance Checks

- [ ] Landing page loads in <3 seconds
- [ ] Browse page loads in <2 seconds
- [ ] API responses return in <500ms
- [ ] IIIF manifests load from external sources
- [ ] Thumbnails load from source institution IIIF servers

---

## Phase 7: Troubleshooting

### 7.1 Common Issues

**Issue: 500 Internal Server Error**

Causes:
- PHP syntax error
- Database connection failure
- `.htaccess` syntax error

Solutions:
1. Check cPanel → Error Logs
2. Temporarily rename `.htaccess` to test
3. Test `api/index.php` directly: `/api/index.php?action=repositories`
4. Verify database credentials in `config.php`

**Issue: 404 on API endpoints**

Causes:
- `.htaccess` not processed
- `mod_rewrite` not enabled

Solutions:
1. Verify `.htaccess` is in web root
2. Check if `AllowOverride` is enabled (contact hosting if needed)
3. Test direct PHP URL: `/api/index.php?action=repositories`

**Issue: Database connection refused**

Causes:
- Wrong credentials
- Wrong database name (forgot username prefix)
- User not granted privileges

Solutions:
1. Verify full database name includes username prefix
2. Re-check privileges in cPanel MySQL section
3. Test connection via phpMyAdmin

**Issue: Blank page / No JSON response**

Causes:
- PHP errors being suppressed
- Output buffering issues

Solutions:
1. Add to top of `api/index.php` temporarily:
   ```php
   ini_set('display_errors', 1);
   error_reporting(E_ALL);
   ```
2. Check PHP error logs in cPanel

**Issue: CORS errors in browser console**

Causes:
- API not sending CORS headers

Solutions:
1. Verify `Access-Control-Allow-Origin` header in `api/index.php`
2. Check for PHP errors before headers are sent

### 7.2 Useful Debugging Commands (SSH)

```bash
# Check PHP version
php -v

# Test PHP syntax
php -l api/index.php

# Check Apache error log (if accessible)
tail -f ~/logs/error.log

# Test database connection from CLI
php -r "
require 'includes/config.php';
try {
    \$pdo = getDbConnection();
    echo 'Connected successfully';
} catch (Exception \$e) {
    echo 'Error: ' . \$e->getMessage();
}
"
```

### 7.3 phpMyAdmin SQL Queries for Verification

```sql
-- Check record counts
SELECT 'repositories' as tbl, COUNT(*) as cnt FROM repositories
UNION ALL
SELECT 'manuscripts', COUNT(*) FROM manuscripts;

-- Check a sample repository
SELECT * FROM repositories LIMIT 1;

-- Check a sample manuscript
SELECT * FROM manuscripts LIMIT 1;

-- Verify foreign key integrity
SELECT COUNT(*) as orphaned_manuscripts
FROM manuscripts m
LEFT JOIN repositories r ON m.repository_id = r.id
WHERE r.id IS NULL;
```

---

## Phase 8: Post-Deployment

### 8.1 Security Hardening

1. **Remove debug code** from `api/index.php`
2. **Restrict config.php** permissions to 600
3. **Verify .htaccess** protections are working:
   - Try accessing `/includes/config.php` directly (should get 403)
4. **Enable HTTPS** if not already (cPanel → SSL/TLS or Let's Encrypt)

### 8.2 Backup Strategy

1. **Database backups:**
   - Use cPanel → Backup Wizard for manual backups
   - JetBackup (available on server) for automated backups

2. **File backups:**
   - Download a copy of `public_html` periodically
   - Keep local git repository as source of truth

### 8.3 Monitoring

1. Check cPanel **Error Logs** periodically
2. Test the site after server updates
3. Monitor IIIF source institutions for manifest URL changes

---

## Appendix A: File Contents Summary

| File | Purpose | Lines (approx) |
|------|---------|----------------|
| `includes/config.php` | Database credentials and connection | ~35 |
| `api/index.php` | All API endpoints | ~180 |
| `.htaccess` (root) | URL rewriting | ~25 |
| `includes/.htaccess` | Directory protection | ~3 |

---

## Appendix B: API Endpoint Reference

| Method | Endpoint | Parameters | Description |
|--------|----------|------------|-------------|
| GET | `/api/repositories` | — | List all repositories with manuscript counts |
| GET | `/api/repositories/{id}` | — | Single repository with its collections |
| GET | `/api/manuscripts` | `repository_id`, `collection`, `limit`, `offset` | List manuscripts with filtering |
| GET | `/api/manuscripts/{id}` | — | Single manuscript with full details |
| GET | `/api/featured` | — | Random manuscript with thumbnail |

---

## Appendix C: Quick Reference Commands

### Export SQLite to MySQL-compatible SQL

```bash
cd /Users/rabota/Geekery/Compilatio

# Export schema (manual conversion needed)
sqlite3 database/compilatio.db ".schema" > sqlite_schema.sql

# Export repositories as INSERT statements
sqlite3 database/compilatio.db ".mode insert repositories" ".output mysql_repositories.sql" "SELECT * FROM repositories;"

# Export manuscripts as INSERT statements
sqlite3 database/compilatio.db ".mode insert manuscripts" ".output mysql_manuscripts.sql" "SELECT * FROM manuscripts;"
```

### Test API Locally Before Upload

```bash
# Start PHP built-in server (for testing PHP files locally)
cd /path/to/prepared/files
php -S localhost:8080
```

---

## Phase 9: Database Synchronization

After initial deployment, the SQLite database on serving (the development server) may be updated with new manuscripts, corrections, or new repositories. This section covers how to re-sync those changes to oldbooks.

### 9.1 Sync Scenarios

#### Scenario A: New manuscripts added to existing repository

**On serving (after updating SQLite):**

```bash
cd /Users/rabota/Geekery/Compilatio

# Export only manuscripts (repositories unchanged)
sqlite3 database/compilatio.db ".mode insert manuscripts" \
  ".output mysql_manuscripts_update.sql" \
  "SELECT * FROM manuscripts;"
```

**On oldbooks (via phpMyAdmin or SSH):**

```sql
-- Clear existing manuscripts and re-import
TRUNCATE TABLE manuscripts;
-- Then import mysql_manuscripts_update.sql
```

#### Scenario B: New repository added

**On serving:**

```bash
# Export both tables
sqlite3 database/compilatio.db ".mode insert repositories" \
  ".output mysql_repositories.sql" \
  "SELECT * FROM repositories;"

sqlite3 database/compilatio.db ".mode insert manuscripts" \
  ".output mysql_manuscripts.sql" \
  "SELECT * FROM manuscripts;"
```

**On oldbooks:**

```sql
-- Must drop manuscripts first (foreign key constraint)
TRUNCATE TABLE manuscripts;
TRUNCATE TABLE repositories;
-- Import repositories first, then manuscripts
```

#### Scenario C: Metadata corrections only

For small targeted fixes, write direct UPDATE statements:

```sql
-- Example: fix a single manuscript's thumbnail
UPDATE manuscripts
SET thumbnail_url = 'https://...'
WHERE id = 123;
```

### 9.2 Automation Scripts

#### sync_to_mysql.sh (run on serving)

```bash
#!/bin/bash
# Export SQLite database for MySQL import
# Run from Compilatio project root

set -e

DBFILE="database/compilatio.db"
OUTDIR="mysql_export"

mkdir -p "$OUTDIR"

echo "Exporting repositories..."
sqlite3 "$DBFILE" ".mode insert repositories" \
  ".output $OUTDIR/repositories.sql" \
  "SELECT * FROM repositories;"

echo "Exporting manuscripts..."
sqlite3 "$DBFILE" ".mode insert manuscripts" \
  ".output $OUTDIR/manuscripts.sql" \
  "SELECT * FROM manuscripts;"

# Generate counts for verification
REPO_COUNT=$(sqlite3 "$DBFILE" "SELECT COUNT(*) FROM repositories;")
MS_COUNT=$(sqlite3 "$DBFILE" "SELECT COUNT(*) FROM manuscripts;")

echo "Export complete:"
echo "  Repositories: $REPO_COUNT"
echo "  Manuscripts:  $MS_COUNT"
echo "Files in $OUTDIR/"
```

#### Makefile targets

Add to project Makefile:

```makefile
# Database export for MySQL migration
mysql-export:
	@mkdir -p mysql_export
	sqlite3 database/compilatio.db ".mode insert repositories" \
		".output mysql_export/repositories.sql" \
		"SELECT * FROM repositories;"
	sqlite3 database/compilatio.db ".mode insert manuscripts" \
		".output mysql_export/manuscripts.sql" \
		"SELECT * FROM manuscripts;"
	@echo "Exported to mysql_export/"

# Upload export files to oldbooks
mysql-upload:
	scp mysql_export/*.sql oldbooks:~/mysql_import/

# Full sync: export and upload
mysql-sync: mysql-export mysql-upload
	@echo "Files uploaded. Import via phpMyAdmin."
```

### 9.3 Re-sync Workflow

1. **Make changes** to SQLite database on serving
2. **Run export**: `make mysql-export` or `./sync_to_mysql.sh`
3. **Upload files**: `make mysql-upload` or SCP manually
4. **Import on oldbooks**:
   - Open phpMyAdmin
   - Select the compilatio database
   - Run: `TRUNCATE manuscripts; TRUNCATE repositories;`
   - Import `repositories.sql` first
   - Import `manuscripts.sql` second
5. **Verify counts** match the export output

### 9.4 Keeping serving and laptop in sync

Before making database changes, ensure serving and laptop have the same SQLite file:

```bash
# On laptop - pull latest from serving
rsync -avz serving:/Users/rabota/Geekery/Compilatio/database/compilatio.db ./database/

# On laptop - push local changes to serving
rsync -avz ./database/compilatio.db serving:/Users/rabota/Geekery/Compilatio/database/
```

**Rule:** Pick one machine as the primary for any given editing session. Never edit on both simultaneously.

See `DB_Ideas.md` for more details on laptop/serving sync strategies.

---

## Version History

| Date | Version | Changes |
|------|---------|---------|
| 2026-01-28 | 1.0 | Initial migration plan |
| 2026-01-28 | 1.1 | Updated data summary: all Bodleian thumbnails now fixed |
| 2026-01-29 | 1.2 | Added Phase 9: Database synchronization and automation scripts |
| 2026-01-29 | 1.3 | Fixed development server name: "serving" (user: rabota) |
| 2026-01-29 | 1.4 | Updated counts (9 repos, 3119 MSS), marked completed phases, added zip upload option |
| 2026-01-29 | 1.5 | **MIGRATION COMPLETE** - Site live at oldbooks.humspace.ucla.edu |
