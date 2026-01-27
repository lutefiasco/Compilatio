#!/bin/bash
# Setup script for Bodleian data import
# Clones the medieval-mss repository and initializes the database

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "=== Compilatio Bodleian Setup ==="
echo ""

# Create data directory
DATA_DIR="$PROJECT_ROOT/data"
BODLEIAN_DIR="$DATA_DIR/bodleian-medieval-mss"

if [ -d "$BODLEIAN_DIR" ]; then
    echo "Bodleian data already exists at $BODLEIAN_DIR"
    echo "To update, run: cd $BODLEIAN_DIR && git pull"
else
    echo "Cloning Bodleian medieval-mss repository (shallow clone)..."
    mkdir -p "$DATA_DIR"
    git clone --depth 1 https://github.com/bodleian/medieval-mss "$BODLEIAN_DIR"
    echo "Done. Repository cloned to $BODLEIAN_DIR"
fi

echo ""

# Initialize database
DB_DIR="$PROJECT_ROOT/database"
DB_PATH="$DB_DIR/compilatio.db"
SCHEMA_PATH="$DB_DIR/schema.sql"

if [ -f "$DB_PATH" ]; then
    echo "Database already exists at $DB_PATH"
else
    if [ -f "$SCHEMA_PATH" ]; then
        echo "Initializing database from schema..."
        sqlite3 "$DB_PATH" < "$SCHEMA_PATH"
        echo "Done. Database created at $DB_PATH"
    else
        echo "ERROR: Schema file not found at $SCHEMA_PATH"
        exit 1
    fi
fi

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo "  1. Run the importer in dry-run mode to preview:"
echo "     python scripts/importers/bodleian.py --verbose"
echo ""
echo "  2. Run the importer to populate the database:"
echo "     python scripts/importers/bodleian.py --execute"
echo ""
