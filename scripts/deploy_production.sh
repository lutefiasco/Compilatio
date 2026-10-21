#!/bin/bash
#
# deploy_production.sh - Deploy Compilatio to production
#
# This script orchestrates the deployment process:
# 1. Runs all pre-flight verification checks
# 2. Deploys files and/or database
# 3. Updates local status document
#
# Usage:
#   ./scripts/deploy_production.sh [files|db|both]
#
#   files  - Upload php_deploy/ to production only
#   db     - Sync MySQL database only
#   both   - Files and database (default if argument omitted: prompts interactively)
#
# Examples:
#   ./scripts/deploy_production.sh both    # non-interactive full deploy
#   ./scripts/deploy_production.sh db      # database only, no prompt
#
# Prerequisites:
#   - SSH key authorized on oldbooks.humspace.ucla.edu
#   - ~/.my.cnf configured on server for MySQL access
#

set -e

# Configuration
PROD_HOST="oldbooks.humspace.ucla.edu"
PROD_USER="oldbooks"
PROD_PATH="public_html"
MYSQL_IMPORT_PATH="mysql_import"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Get script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

echo "========================================"
echo "   Compilatio Production Deployment"
echo "========================================"
echo ""

# Step 1: Build php_deploy/ from src/
echo "Building php_deploy/ from src/..."
if ! python3 scripts/build_php.py; then
    echo ""
    echo -e "${RED}Build failed. Deployment aborted.${NC}"
    exit 1
fi
echo ""

# Step 1a2: Refresh shelfmark sort keys so any newly imported manuscripts
# sort numerically. Idempotent; importers don't set sort_key themselves.
echo "Refreshing shelfmark sort keys..."
if ! python3 scripts/sort_keys.py; then
    echo ""
    echo -e "${RED}Sort-key backfill failed. Deployment aborted.${NC}"
    exit 1
fi
echo ""

# Step 1b: Regenerate MySQL export from the live SQLite database.
# Mirrors the php_deploy build above so both deploy artifacts are always fresh
# before verify_deploy.py checks them (otherwise a DB deploy is blocked on a
# stale export the operator has to remember to regenerate by hand).
echo "Regenerating MySQL export from database/compilatio.db..."
if ! python3 scripts/export_mysql.py; then
    echo ""
    echo -e "${RED}MySQL export failed. Deployment aborted.${NC}"
    exit 1
fi
echo ""

# Step 2: Run verification
echo "Running pre-flight checks..."
echo ""

if ! python3 scripts/verify_deploy.py; then
    echo ""
    echo -e "${RED}Deployment aborted due to failed checks.${NC}"
    exit 1
fi

echo ""

# Step 3: Determine what to deploy (CLI arg or interactive prompt)
case "${1:-}" in
    files)
        DEPLOY_FILES=true
        DEPLOY_DB=false
        ;;
    db)
        DEPLOY_FILES=false
        DEPLOY_DB=true
        ;;
    both)
        DEPLOY_FILES=true
        DEPLOY_DB=true
        ;;
    "")
        echo "What would you like to deploy?"
        echo ""
        echo "  1) Files only      - Upload php_deploy/ to production"
        echo "  2) Database only   - Sync MySQL database"
        echo "  3) Both            - Files and database"
        echo "  4) Cancel"
        echo ""
        read -p "Choice [1-4]: " choice
        case $choice in
            1) DEPLOY_FILES=true;  DEPLOY_DB=false ;;
            2) DEPLOY_FILES=false; DEPLOY_DB=true  ;;
            3) DEPLOY_FILES=true;  DEPLOY_DB=true  ;;
            4|*) echo "Cancelled."; exit 0 ;;
        esac
        ;;
    *)
        echo "Unknown argument: $1"
        echo "Usage: $0 [files|db|both]"
        exit 1
        ;;
esac

echo ""

# Step 4: Deploy files
if [ "$DEPLOY_FILES" = true ]; then
    echo "----------------------------------------"
    echo "Deploying files..."
    echo "----------------------------------------"
    echo ""

    # Root .htaccess: repo copy plus whatever cPanel-managed blocks the
    # server's copy carries (Humspace's PHP handler, 2026-10-21). Built
    # before anything is uploaded, so a fetch or merge failure aborts the
    # deploy with production untouched.
    HTACCESS_TMP=$(mktemp -d)
    trap 'rm -rf "$HTACCESS_TMP"' EXIT
    echo "Fetching live .htaccess to keep cPanel-managed blocks..."
    ssh "${PROD_USER}@${PROD_HOST}" \
        "if [ -f ~/${PROD_PATH}/.htaccess ]; then cat ~/${PROD_PATH}/.htaccess; fi" \
        > "$HTACCESS_TMP/live"
    scripts/merge_htaccess.sh php_deploy/.htaccess "$HTACCESS_TMP/live" \
        > "$HTACCESS_TMP/.htaccess"
    KEPT=$(grep -c -E '^#.*BEGIN cPanel-generated' "$HTACCESS_TMP/.htaccess" || true)
    echo "  Kept ${KEPT} cPanel block(s)"
    echo ""

    # Show what will be synced
    echo "Syncing php_deploy/ -> ${PROD_USER}@${PROD_HOST}:~/${PROD_PATH}/"
    echo "(Excluding: includes/config.php, includes/.htaccess, .well-known/;"
    echo " root .htaccess uploaded separately with cPanel blocks merged)"
    echo ""

    # .well-known/ belongs to the host's certificate renewal, not to us.
    rsync -avz --delete \
        --exclude='includes/config.php' \
        --exclude='includes/.htaccess' \
        --exclude='/.htaccess' \
        --exclude='/.well-known/' \
        php_deploy/ \
        "${PROD_USER}@${PROD_HOST}:~/${PROD_PATH}/"

    # mktemp files are 0600; rsync -a carries mode over, and Apache must
    # be able to read .htaccess.
    chmod 644 "$HTACCESS_TMP/.htaccess"
    rsync -avz "$HTACCESS_TMP/.htaccess" \
        "${PROD_USER}@${PROD_HOST}:~/${PROD_PATH}/.htaccess"

    echo ""
    echo -e "${GREEN}[✓] Files deployed successfully${NC}"
    echo ""
fi

# Step 5: Deploy database
if [ "$DEPLOY_DB" = true ]; then
    echo "----------------------------------------"
    echo "Deploying database..."
    echo "----------------------------------------"
    echo ""

    # Upload SQL files
    echo "Uploading SQL files..."
    ssh "${PROD_USER}@${PROD_HOST}" "mkdir -p ~/${MYSQL_IMPORT_PATH}"
    scp mysql_export/repositories.sql mysql_export/manuscripts.sql \
        "${PROD_USER}@${PROD_HOST}:~/${MYSQL_IMPORT_PATH}/"

    echo ""
    echo "Importing to MySQL..."
    echo "(This will clear existing data and import fresh)"
    echo ""

    # Import to MySQL
    ssh "${PROD_USER}@${PROD_HOST}" bash << 'REMOTE_SCRIPT'
        set -e

        # One-time migration (2026-07-11): the export's positional INSERTs
        # include sort_key, so the column must exist. Errors (column already
        # exists) are ignored; a real problem surfaces in the import below.
        mysql -e "ALTER TABLE manuscripts ADD COLUMN sort_key VARCHAR(255);" 2>/dev/null || true

        echo "Clearing existing data..."
        mysql -e "SET FOREIGN_KEY_CHECKS=0; DELETE FROM manuscripts; DELETE FROM repositories; SET FOREIGN_KEY_CHECKS=1;"

        echo "Importing repositories..."
        mysql < ~/mysql_import/repositories.sql

        echo "Importing manuscripts..."
        mysql < ~/mysql_import/manuscripts.sql

        echo ""
        echo "Verifying import..."
        mysql -e "SELECT 'repositories' as tbl, COUNT(*) as count FROM repositories UNION ALL SELECT 'manuscripts', COUNT(*) FROM manuscripts;"
REMOTE_SCRIPT

    echo ""
    echo -e "${GREEN}[✓] Database deployed successfully${NC}"
    echo ""
fi

# Step 6: Update local status document
STATUS_FILE="Feb04_2026_Status.md"
DEPLOY_DATE=$(date "+%Y-%m-%d %H:%M")

# Determine what was deployed
if [ "$DEPLOY_FILES" = true ] && [ "$DEPLOY_DB" = true ]; then
    DEPLOYED="Files + Database"
elif [ "$DEPLOY_FILES" = true ]; then
    DEPLOYED="Files only"
else
    DEPLOYED="Database only"
fi

# Get counts from local database
REPO_COUNT=$(sqlite3 database/compilatio.db "SELECT COUNT(*) FROM repositories;")
MS_COUNT=$(sqlite3 database/compilatio.db "SELECT COUNT(*) FROM manuscripts;")
MS_COUNT_FORMATTED=$(printf "%'d" $MS_COUNT)

# Update the status file
if [ -f "$STATUS_FILE" ]; then
    # Rewrite each row of the "Last Production Deployment" table wholesale,
    # scoped to that section — "| Date |" also appears as a Recent
    # Completions column header further down.
    sed -i.bak -E "
        /^## Last Production Deployment/,/^---/ {
            s/^\| Date \|.*/| Date | ${DEPLOY_DATE} |/
            s/^\| Deployed \|.*/| Deployed | ${DEPLOYED} |/
            s/^\| Repositories \|.*/| Repositories | ${REPO_COUNT} |/
            s/^\| Manuscripts \|.*/| Manuscripts | ${MS_COUNT_FORMATTED} |/
        }
    " "$STATUS_FILE"
    rm -f "${STATUS_FILE}.bak"
    if grep -q "| Date | ${DEPLOY_DATE} |" "$STATUS_FILE"; then
        echo "Updated ${STATUS_FILE} with deployment timestamp"
    else
        echo "WARNING: failed to stamp ${STATUS_FILE} — update it by hand"
    fi
fi

# Step 7: Summary
echo ""
echo "========================================"
echo "   Deployment Complete"
echo "========================================"
echo ""

if [ "$DEPLOY_FILES" = true ]; then
    echo "  Files:    https://${PROD_HOST}/"
fi
if [ "$DEPLOY_DB" = true ]; then
    echo "  Database: ${REPO_COUNT} repos, ${MS_COUNT_FORMATTED} manuscripts"
fi
echo "  Logged:   ${STATUS_FILE}"

echo ""
echo "Test the site: https://${PROD_HOST}/"
echo ""
