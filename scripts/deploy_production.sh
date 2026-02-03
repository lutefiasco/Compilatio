#!/bin/bash
#
# deploy_production.sh - Deploy Compilatio to production
#
# This script orchestrates the deployment process:
# 1. Runs all pre-flight verification checks
# 2. Asks what to deploy (files, database, or both)
# 3. Executes the deployment
#
# Usage:
#   ./scripts/deploy_production.sh
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

# Step 1: Run verification
echo "Running pre-flight checks..."
echo ""

if ! python3 scripts/verify_deploy.py; then
    echo ""
    echo -e "${RED}Deployment aborted due to failed checks.${NC}"
    exit 1
fi

echo ""

# Step 2: Ask what to deploy
echo "What would you like to deploy?"
echo ""
echo "  1) Files only      - Upload php_deploy/ to production"
echo "  2) Database only   - Sync MySQL database"
echo "  3) Both            - Files and database"
echo "  4) Cancel"
echo ""
read -p "Choice [1-4]: " choice

case $choice in
    1)
        DEPLOY_FILES=true
        DEPLOY_DB=false
        ;;
    2)
        DEPLOY_FILES=false
        DEPLOY_DB=true
        ;;
    3)
        DEPLOY_FILES=true
        DEPLOY_DB=true
        ;;
    4|*)
        echo "Cancelled."
        exit 0
        ;;
esac

echo ""

# Step 3: Deploy files
if [ "$DEPLOY_FILES" = true ]; then
    echo "----------------------------------------"
    echo "Deploying files..."
    echo "----------------------------------------"
    echo ""

    # Show what will be synced
    echo "Syncing php_deploy/ -> ${PROD_USER}@${PROD_HOST}:~/${PROD_PATH}/"
    echo "(Excluding: includes/config.php, includes/.htaccess)"
    echo ""

    rsync -avz --delete \
        --exclude='includes/config.php' \
        --exclude='includes/.htaccess' \
        php_deploy/ \
        "${PROD_USER}@${PROD_HOST}:~/${PROD_PATH}/"

    echo ""
    echo -e "${GREEN}[✓] Files deployed successfully${NC}"
    echo ""
fi

# Step 4: Deploy database
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

# Step 5: Summary
echo "========================================"
echo "   Deployment Complete"
echo "========================================"
echo ""

if [ "$DEPLOY_FILES" = true ]; then
    echo "  Files:    https://${PROD_HOST}/"
fi
if [ "$DEPLOY_DB" = true ]; then
    echo "  Database: Synced to MySQL"
fi

echo ""
echo "Test the site: https://${PROD_HOST}/"
echo ""
