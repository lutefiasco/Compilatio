#!/usr/bin/env python3
"""
export_mysql.py - Export SQLite database to MySQL-compatible SQL

Exports the Compilatio SQLite database to MySQL-compatible INSERT statements
with thorough validation to catch common migration issues.

Usage:
    python3 scripts/export_mysql.py          # Run export
    python3 scripts/export_mysql.py --check  # Verify existing export is current and valid
"""

import argparse
import hashlib
import os
import re
import sqlite3
import sys
from pathlib import Path

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent
DB_PATH = PROJECT_ROOT / 'database' / 'compilatio.db'
EXPORT_DIR = PROJECT_ROOT / 'mysql_export'

# Output files
REPOS_SQL = EXPORT_DIR / 'repositories.sql'
MANUSCRIPTS_SQL = EXPORT_DIR / 'manuscripts.sql'

# Validation patterns - things that break MySQL
INVALID_PATTERNS = [
    (r'\bunistr\s*\(', 'SQLite unistr() function not supported in MySQL'),
    (r'\bjulianday\s*\(', 'SQLite julianday() function not supported in MySQL'),
    (r'\brandom\s*\(', 'SQLite random() should be RAND() in MySQL'),
    (r'\bstrftime\s*\(', 'SQLite strftime() not directly supported in MySQL'),
]


def escape_mysql(val) -> str:
    """Escape a value for MySQL INSERT statement."""
    if val is None:
        return 'NULL'
    if isinstance(val, (int, float)):
        return str(val)

    s = str(val)

    # Check for invalid UTF-8 or problematic characters
    try:
        s.encode('utf-8')
    except UnicodeEncodeError:
        # Replace invalid characters
        s = s.encode('utf-8', errors='replace').decode('utf-8')

    # MySQL escaping
    s = s.replace('\\', '\\\\')  # Backslashes first
    s = s.replace("'", "\\'")    # Single quotes
    s = s.replace('\n', '\\n')   # Newlines
    s = s.replace('\r', '\\r')   # Carriage returns
    s = s.replace('\t', '\\t')   # Tabs
    s = s.replace('\0', '')      # Null bytes (remove entirely)

    return f"'{s}'"


def validate_sql_content(content: str, filename: str) -> list:
    """Validate SQL content for MySQL compatibility. Returns list of issues."""
    issues = []

    # Check for invalid SQLite-specific patterns
    for pattern, message in INVALID_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            issues.append(f"{filename}: {message}")

    # Check file is not empty and has INSERT statements
    if 'INSERT INTO' not in content:
        issues.append(f"{filename}: No INSERT statements found")

    # Check for common escaping issues
    # Look for unescaped newlines (actual newlines in values, not \n)
    lines = content.split('\n')
    for i, line in enumerate(lines, 1):
        if line.startswith('INSERT INTO') and not line.rstrip().endswith(';'):
            # Multi-line INSERT - could indicate unescaped newline
            issues.append(f"{filename}: Possible unescaped newline at line {i}")

    return issues


def get_db_counts() -> tuple:
    """Get current counts from SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM repositories")
    repo_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM manuscripts")
    ms_count = cursor.fetchone()[0]

    conn.close()
    return repo_count, ms_count


def get_export_counts() -> tuple:
    """Get counts from exported SQL files."""
    repo_count = 0
    ms_count = 0

    if REPOS_SQL.exists():
        with open(REPOS_SQL, 'r') as f:
            content = f.read()
            repo_count = content.count('INSERT INTO repositories VALUES')

    if MANUSCRIPTS_SQL.exists():
        with open(MANUSCRIPTS_SQL, 'r') as f:
            content = f.read()
            ms_count = content.count('INSERT INTO manuscripts VALUES')

    return repo_count, ms_count


def get_db_hash() -> str:
    """Get a hash representing the current database state."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Get all data in a deterministic order
    cursor.execute("SELECT * FROM repositories ORDER BY id")
    repos = cursor.fetchall()

    cursor.execute("SELECT * FROM manuscripts ORDER BY id")
    manuscripts = cursor.fetchall()

    conn.close()

    # Create hash from data
    data = str(repos) + str(manuscripts)
    return hashlib.sha256(data.encode('utf-8')).hexdigest()


def get_export_hash() -> str:
    """Get a hash of the exported SQL files."""
    if not REPOS_SQL.exists() or not MANUSCRIPTS_SQL.exists():
        return ''

    with open(REPOS_SQL, 'rb') as f:
        repos_content = f.read()
    with open(MANUSCRIPTS_SQL, 'rb') as f:
        ms_content = f.read()

    return hashlib.sha256(repos_content + ms_content).hexdigest()


def check_export() -> bool:
    """Check if existing export is current and valid. Returns True if OK."""
    all_ok = True

    # Check if export files exist
    if not REPOS_SQL.exists():
        print(f"[!] Missing: {REPOS_SQL}", file=sys.stderr)
        all_ok = False
    if not MANUSCRIPTS_SQL.exists():
        print(f"[!] Missing: {MANUSCRIPTS_SQL}", file=sys.stderr)
        all_ok = False

    if not all_ok:
        return False

    # Check counts match
    db_repos, db_ms = get_db_counts()
    export_repos, export_ms = get_export_counts()

    if db_repos != export_repos:
        print(f"[!] Repository count mismatch: DB has {db_repos}, export has {export_repos}", file=sys.stderr)
        all_ok = False

    if db_ms != export_ms:
        print(f"[!] Manuscript count mismatch: DB has {db_ms}, export has {export_ms}", file=sys.stderr)
        all_ok = False

    # Validate SQL content
    with open(REPOS_SQL, 'r') as f:
        repos_content = f.read()
    issues = validate_sql_content(repos_content, 'repositories.sql')
    for issue in issues:
        print(f"[!] {issue}", file=sys.stderr)
        all_ok = False

    with open(MANUSCRIPTS_SQL, 'r') as f:
        ms_content = f.read()
    issues = validate_sql_content(ms_content, 'manuscripts.sql')
    for issue in issues:
        print(f"[!] {issue}", file=sys.stderr)
        all_ok = False

    return all_ok


def export_table(cursor, table_name: str, output_path: Path) -> int:
    """Export a table to MySQL INSERT statements. Returns row count."""
    cursor.execute(f"SELECT * FROM {table_name}")
    rows = cursor.fetchall()

    with open(output_path, 'w') as f:
        for row in rows:
            values = ','.join(escape_mysql(v) for v in row)
            f.write(f"INSERT INTO {table_name} VALUES({values});\n")

    return len(rows)


def export():
    """Run the export from SQLite to MySQL SQL files."""
    print("=== Exporting SQLite to MySQL ===\n")

    # Ensure export directory exists
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    # Connect to database
    if not DB_PATH.exists():
        print(f"[!] Database not found: {DB_PATH}", file=sys.stderr)
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Export repositories
    repo_count = export_table(cursor, 'repositories', REPOS_SQL)
    print(f"[✓] Exported {repo_count} repositories to {REPOS_SQL.name}")

    # Export manuscripts
    ms_count = export_table(cursor, 'manuscripts', MANUSCRIPTS_SQL)
    print(f"[✓] Exported {ms_count} manuscripts to {MANUSCRIPTS_SQL.name}")

    conn.close()

    print(f"\n=== Export complete ===")
    print(f"Output: {EXPORT_DIR}/")
    print(f"  repositories.sql: {repo_count} rows")
    print(f"  manuscripts.sql:  {ms_count} rows")


def main():
    parser = argparse.ArgumentParser(
        description='Export SQLite database to MySQL-compatible SQL'
    )
    parser.add_argument(
        '--check',
        action='store_true',
        help='Check if existing export is current and valid (exit 0 if yes, 1 if stale/invalid)'
    )
    args = parser.parse_args()

    if args.check:
        if check_export():
            db_repos, db_ms = get_db_counts()
            print(f"[✓] MySQL export is valid ({db_repos} repos, {db_ms} manuscripts)")
            sys.exit(0)
        else:
            print("\n[✗] MySQL export is stale or invalid")
            print("    Run: python3 scripts/export_mysql.py")
            sys.exit(1)
    else:
        export()
        # Verify the export
        print("\nValidating export...")
        if check_export():
            print("[✓] Validation passed")
        else:
            print("[!] Warning: Validation failed after export", file=sys.stderr)
            sys.exit(1)


if __name__ == '__main__':
    main()
