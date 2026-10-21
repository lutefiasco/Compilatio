#!/bin/bash
#
# merge_htaccess.sh - Repo .htaccess plus the server's cPanel-managed blocks
#
# Usage: scripts/merge_htaccess.sh REPO_HTACCESS LIVE_HTACCESS > merged
#
# Humspace's cPanel writes its own sections into public_html/.htaccess
# (e.g. the PHP handler, added 2026-10-21), fenced by
#   # ... BEGIN cPanel-generated ... / # ... END cPanel-generated ...
# Those sections are theirs. This prints the repo copy with any such blocks
# removed, then appends the blocks from the live file verbatim, so a deploy
# keeps whatever cPanel last set instead of reverting it.
#
# Exits non-zero (printing nothing) if either file has an unbalanced
# BEGIN/END pair, rather than guessing where a block ends.

set -euo pipefail

REPO="$1"
LIVE="$2"

BEGIN_RE='^#.*BEGIN cPanel-generated'
END_RE='^#.*END cPanel-generated'

check_balanced() {
    local file="$1" b e
    b=$(grep -c -E "$BEGIN_RE" "$file" || true)
    e=$(grep -c -E "$END_RE" "$file" || true)
    if [ "$b" != "$e" ]; then
        echo "merge_htaccess: $file has $b BEGIN and $e END cPanel markers; refusing to merge" >&2
        exit 1
    fi
}

check_balanced "$REPO"
check_balanced "$LIVE"

# Repo copy, minus any cPanel blocks (they belong to the server).
repo_body=$(awk -v b="$BEGIN_RE" -v e="$END_RE" '
    $0 ~ b {skip=1}
    !skip  {print}
    $0 ~ e {skip=0}
' "$REPO")

# cPanel blocks from the live file, verbatim.
live_blocks=$(awk -v b="$BEGIN_RE" -v e="$END_RE" '
    $0 ~ b {keep=1}
    keep   {print}
    $0 ~ e {keep=0}
' "$LIVE")

printf '%s\n' "$repo_body"
if [ -n "$live_blocks" ]; then
    printf '\n%s\n' "$live_blocks"
fi
