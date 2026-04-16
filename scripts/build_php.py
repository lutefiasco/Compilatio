#!/usr/bin/env python3
"""
build_php.py - Sync src/ to php_deploy/ for production deployment

Copies all source files to php_deploy/. Production API routing is handled
entirely by .htaccess mod_rewrite rules — no JS transformation needed.

Usage:
    python3 scripts/build_php.py          # Run sync
    python3 scripts/build_php.py --check  # Verify php_deploy is in sync
"""

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent
SRC_DIR = PROJECT_ROOT / 'src'
PHP_DEPLOY_DIR = PROJECT_ROOT / 'php_deploy'

# All files to sync from src/ to php_deploy/
SYNC_FILES = [
    'index.html',
    'browse.html',
    'viewer.html',
    'about.html',
    'css/styles.css',
    'js/script.js',
    'js/browse.js',
    'images/border-top.jpg',
    'images/border-right.jpg',
]

# Files that only exist in php_deploy (don't overwrite)
PHP_ONLY_FILES = [
    'api/index.php',
    'includes/config.php',
    'includes/config.php.example',
    'includes/.htaccess',
    '.htaccess',
]


def file_hash(filepath: Path) -> str:
    """Calculate SHA256 hash of a file."""
    if not filepath.exists():
        return ''
    with open(filepath, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def check_sync() -> bool:
    """Check if php_deploy is in sync with src. Returns True if in sync."""
    all_synced = True

    for sync_file in SYNC_FILES:
        src_path = SRC_DIR / sync_file
        php_path = PHP_DEPLOY_DIR / sync_file

        if not src_path.exists():
            continue

        if not php_path.exists():
            print(f"[!] PHP deploy file missing: {php_path}", file=sys.stderr)
            all_synced = False
            continue

        if file_hash(src_path) != file_hash(php_path):
            print(f"[!] Out of sync: {sync_file}", file=sys.stderr)
            all_synced = False

    return all_synced


def build():
    """Sync src/ files to php_deploy/."""
    print("=== Building php_deploy/ from src/ ===\n")

    # Ensure php_deploy directory structure exists
    for subdir in ['js', 'css', 'images', 'api', 'includes']:
        (PHP_DEPLOY_DIR / subdir).mkdir(parents=True, exist_ok=True)

    for sync_file in SYNC_FILES:
        src_path = SRC_DIR / sync_file
        php_path = PHP_DEPLOY_DIR / sync_file

        if not src_path.exists():
            print(f"[!] Skipping missing source: {src_path}")
            continue

        php_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_path, php_path)
        print(f"[✓] Copied: {sync_file}")

    print("\n=== Build complete ===")
    print(f"Output: {PHP_DEPLOY_DIR}/")


def main():
    parser = argparse.ArgumentParser(
        description='Sync src/ to php_deploy/ for production deployment'
    )
    parser.add_argument(
        '--check',
        action='store_true',
        help='Check if php_deploy is in sync with src (exit 0 if yes, 1 if stale)'
    )
    args = parser.parse_args()

    if args.check:
        if check_sync():
            print("[✓] php_deploy/ is in sync with src/")
            sys.exit(0)
        else:
            print("\n[✗] php_deploy/ is out of sync with src/")
            print("    Run: python3 scripts/build_php.py")
            sys.exit(1)
    else:
        build()
        # Verify the build
        if check_sync():
            print("\n[✓] Verification passed: php_deploy/ matches src/")
        else:
            print("[!] Warning: Verification failed after build", file=sys.stderr)
            sys.exit(1)


if __name__ == '__main__':
    main()
