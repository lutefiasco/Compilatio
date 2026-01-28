#!/bin/bash
# Compilatio server startup script
# Creates virtual environment, installs dependencies, and starts the server

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR=".venv"

# Create virtual environment if it doesn't exist
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
fi

# Activate virtual environment
echo "Activating virtual environment..."
source "$VENV_DIR/bin/activate"

# Install/upgrade dependencies
echo "Installing dependencies..."
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt

# Check if database exists
if [ ! -f "database/compilatio.db" ]; then
    echo ""
    echo "Warning: Database not found at database/compilatio.db"
    echo "You may need to run the setup scripts first:"
    echo "  ./scripts/setup_bodleian.sh"
    echo "  python scripts/importers/bodleian.py --execute"
    echo ""
fi

# Start the server
echo ""
echo "Starting Compilatio server..."
python server.py
