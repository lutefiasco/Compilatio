#!/usr/bin/env python3
"""
build_php.py - Convert src/ to php_deploy/ with API URL transformation

Transforms JavaScript files from Python/Starlette API format to PHP format:
  - ${API_BASE}/endpoint -> apiUrl('action')
  - Injects apiUrl() helper function

Usage:
    python3 scripts/build_php.py          # Run conversion
    python3 scripts/build_php.py --check  # Verify php_deploy is in sync
"""

import argparse
import hashlib
import os
import re
import shutil
import sys
from pathlib import Path

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent
SRC_DIR = PROJECT_ROOT / 'src'
PHP_DEPLOY_DIR = PROJECT_ROOT / 'php_deploy'

# Files to transform (JS files with API calls)
JS_FILES = ['js/script.js', 'js/browse.js']

# Files to copy as-is
COPY_FILES = [
    'index.html',
    'browse.html',
    'viewer.html',
    'about.html',
    'css/styles.css',
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

# The apiUrl helper to inject into JS files
API_URL_HELPER = '''    // API helper - builds URLs without mod_rewrite
    function apiUrl(action, params = {}) {
        const url = new URL('/api/index.php', window.location.origin);
        url.searchParams.set('action', action);
        for (const [key, value] of Object.entries(params)) {
            if (value !== undefined && value !== null) {
                url.searchParams.set(key, value);
            }
        }
        return url.toString();
    }

'''


def transform_js_content(content: str, filename: str) -> str:
    """Transform JavaScript content from src/ format to php_deploy/ format."""

    # Remove the API_BASE constant line
    content = re.sub(r"\s*const API_BASE = '/api';\n", '\n', content)

    # Track if we need to inject the apiUrl helper
    needs_helper = False

    # Transform simple fetch calls: `${API_BASE}/endpoint` -> apiUrl('endpoint')
    # Note: Must include the backticks to avoid leaving them around the function call
    simple_endpoints = ['featured', 'repositories']
    for endpoint in simple_endpoints:
        pattern = rf'`\$\{{API_BASE\}}/{endpoint}`'
        if re.search(pattern, content):
            needs_helper = True
            content = re.sub(pattern, f"apiUrl('{endpoint}')", content)

    # Transform: `${API_BASE}/repositories/${id}` -> apiUrl('repository', { id: id })
    # Handles: `${API_BASE}/repositories/${currentRepo}`
    pattern = r'`\$\{API_BASE\}/repositories/\$\{(\w+)\}`'
    if re.search(pattern, content):
        needs_helper = True
        content = re.sub(pattern, r"apiUrl('repository', { id: \1 })", content)

    # Transform: `${API_BASE}/manuscripts/${id}` -> apiUrl('manuscript', { id: id })
    pattern = r'`\$\{API_BASE\}/manuscripts/\$\{(\w+)\}`'
    if re.search(pattern, content):
        needs_helper = True
        content = re.sub(pattern, r"apiUrl('manuscript', { id: \1 })", content)

    # Transform complex manuscript URLs with query params
    # Pattern: `${API_BASE}/manuscripts?repository_id=${...}&limit=${...}&offset=${...}`
    # This is more complex - we need to handle the URL building in browse.js

    # Handle the specific pattern in browse.js loadManuscripts:
    # let url = `${API_BASE}/manuscripts?repository_id=${currentRepo}&limit=${ITEMS_PER_PAGE}&offset=${currentOffset}`;
    # if (currentCollection) { url += `&collection=${encodeURIComponent(currentCollection)}`; }
    # const response = await fetch(url);

    # Transform to use params object approach
    if 'browse.js' in filename:
        # Replace the URL building block with params object approach
        old_url_block = r'''let url = `\$\{API_BASE\}/manuscripts\?repository_id=\$\{currentRepo\}&limit=\$\{ITEMS_PER_PAGE\}&offset=\$\{currentOffset\}`;
            if \(currentCollection\) \{
                url \+= `&collection=\$\{encodeURIComponent\(currentCollection\)\}`;
            \}

            const response = await fetch\(url\);'''

        new_url_block = '''const params = {
                repository_id: currentRepo,
                limit: ITEMS_PER_PAGE,
                offset: currentOffset
            };
            if (currentCollection) {
                params.collection = currentCollection;
            }

            const response = await fetch(apiUrl('manuscripts', params));'''

        if re.search(old_url_block, content):
            needs_helper = True
            content = re.sub(old_url_block, new_url_block, content)

    # Transform: `${API_BASE}/manuscripts?limit=1` -> apiUrl('manuscripts', { limit: 1 })
    pattern = r'`\$\{API_BASE\}/manuscripts\?limit=(\d+)`'
    if re.search(pattern, content):
        needs_helper = True
        content = re.sub(pattern, r"apiUrl('manuscripts', { limit: \1 })", content)

    # Inject the apiUrl helper after 'use strict'; if needed
    if needs_helper:
        # Find the position after 'use strict';
        match = re.search(r"('use strict';)\n", content)
        if match:
            insert_pos = match.end()
            content = content[:insert_pos] + '\n' + API_URL_HELPER + content[insert_pos:]

    return content


def file_hash(filepath: Path) -> str:
    """Calculate SHA256 hash of a file."""
    if not filepath.exists():
        return ''
    with open(filepath, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def content_hash(content: str) -> str:
    """Calculate SHA256 hash of content."""
    return hashlib.sha256(content.encode('utf-8')).hexdigest()


def check_sync() -> bool:
    """Check if php_deploy is in sync with src. Returns True if in sync."""
    all_synced = True

    # Check JS files (need transformation comparison)
    for js_file in JS_FILES:
        src_path = SRC_DIR / js_file
        php_path = PHP_DEPLOY_DIR / js_file

        if not src_path.exists():
            print(f"[!] Source file missing: {src_path}", file=sys.stderr)
            all_synced = False
            continue

        if not php_path.exists():
            print(f"[!] PHP deploy file missing: {php_path}", file=sys.stderr)
            all_synced = False
            continue

        # Transform src content and compare
        with open(src_path, 'r') as f:
            src_content = f.read()

        transformed = transform_js_content(src_content, js_file)

        with open(php_path, 'r') as f:
            php_content = f.read()

        if content_hash(transformed) != content_hash(php_content):
            print(f"[!] Out of sync: {js_file}", file=sys.stderr)
            all_synced = False

    # Check copy files (direct comparison)
    for copy_file in COPY_FILES:
        src_path = SRC_DIR / copy_file
        php_path = PHP_DEPLOY_DIR / copy_file

        if not src_path.exists():
            # Some files might not exist (like about.html might be optional)
            continue

        if not php_path.exists():
            print(f"[!] PHP deploy file missing: {php_path}", file=sys.stderr)
            all_synced = False
            continue

        if file_hash(src_path) != file_hash(php_path):
            print(f"[!] Out of sync: {copy_file}", file=sys.stderr)
            all_synced = False

    return all_synced


def build():
    """Run the conversion from src/ to php_deploy/."""
    print("=== Building php_deploy/ from src/ ===\n")

    # Ensure php_deploy directory structure exists
    for subdir in ['js', 'css', 'images', 'api', 'includes']:
        (PHP_DEPLOY_DIR / subdir).mkdir(parents=True, exist_ok=True)

    # Transform and write JS files
    for js_file in JS_FILES:
        src_path = SRC_DIR / js_file
        php_path = PHP_DEPLOY_DIR / js_file

        if not src_path.exists():
            print(f"[!] Skipping missing source: {src_path}")
            continue

        with open(src_path, 'r') as f:
            src_content = f.read()

        transformed = transform_js_content(src_content, js_file)

        with open(php_path, 'w') as f:
            f.write(transformed)

        print(f"[✓] Transformed: {js_file}")

    # Copy static files
    for copy_file in COPY_FILES:
        src_path = SRC_DIR / copy_file
        php_path = PHP_DEPLOY_DIR / copy_file

        if not src_path.exists():
            print(f"[!] Skipping missing source: {src_path}")
            continue

        # Ensure parent directory exists
        php_path.parent.mkdir(parents=True, exist_ok=True)

        shutil.copy2(src_path, php_path)
        print(f"[✓] Copied: {copy_file}")

    print("\n=== Build complete ===")
    print(f"Output: {PHP_DEPLOY_DIR}/")


def main():
    parser = argparse.ArgumentParser(
        description='Convert src/ to php_deploy/ with API URL transformation'
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
            print("\n[!] Warning: Verification failed after build", file=sys.stderr)
            sys.exit(1)


if __name__ == '__main__':
    main()
