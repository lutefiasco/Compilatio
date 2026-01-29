#!/bin/bash
#
# Wrapper script to run fix_bodleian_thumbnails.py until completion.
# Automatically restarts after failures or interruptions.
#
# Usage:
#   ./scripts/run_bodleian_thumbnails.sh           # Run until complete
#   ./scripts/run_bodleian_thumbnails.sh --dry-run # Test without changes
#

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PYTHON_SCRIPT="$SCRIPT_DIR/fix_bodleian_thumbnails.py"
PROGRESS_FILE="$SCRIPT_DIR/.bodleian_thumbnail_progress.json"
LOG_FILE="$SCRIPT_DIR/bodleian_thumbnails.log"

# Parse arguments
EXECUTE_FLAG="--execute"
if [[ "$1" == "--dry-run" ]]; then
    EXECUTE_FLAG=""
    echo "DRY RUN MODE - no database changes will be made"
fi

cd "$PROJECT_DIR"

# Function to get remaining count
get_remaining() {
    python3 -c "
import json
import sqlite3
from pathlib import Path

progress_file = Path('$PROGRESS_FILE')
db_path = Path('database/compilatio.db')

# Get total
conn = sqlite3.connect(db_path)
cursor = conn.cursor()
cursor.execute('''
    SELECT COUNT(*) FROM manuscripts m
    JOIN repositories r ON m.repository_id = r.id
    WHERE r.short_name = \"Bodleian\" AND m.iiif_manifest_url IS NOT NULL
''')
total = cursor.fetchone()[0]
conn.close()

# Get processed
processed = 0
if progress_file.exists():
    with open(progress_file) as f:
        data = json.load(f)
        processed = len(data.get('processed_ids', []))

print(total - processed)
"
}

echo "=========================================="
echo "Bodleian Thumbnail Fix - Auto Runner"
echo "=========================================="
echo "Log file: $LOG_FILE"
echo ""

RUN_COUNT=0
PAUSE_BETWEEN_RUNS=10  # seconds to wait between runs

while true; do
    REMAINING=$(get_remaining)

    if [[ "$REMAINING" -eq 0 ]]; then
        echo ""
        echo "=========================================="
        echo "ALL DONE! All manuscripts have been processed."
        echo "=========================================="

        # Show final stats
        if [[ -f "$PROGRESS_FILE" ]]; then
            echo ""
            python3 "$PYTHON_SCRIPT" --status
        fi
        break
    fi

    RUN_COUNT=$((RUN_COUNT + 1))
    echo ""
    echo "=========================================="
    echo "Run #$RUN_COUNT - $REMAINING manuscripts remaining"
    echo "Started at: $(date)"
    echo "=========================================="
    echo ""

    # Run the script, capturing output to both terminal and log
    # Use set +e to prevent script from exiting on failure
    set +e
    python3 "$PYTHON_SCRIPT" $EXECUTE_FLAG --batch-size 10 2>&1 | tee -a "$LOG_FILE"
    EXIT_CODE=${PIPESTATUS[0]}
    set -e

    echo ""
    echo "Run #$RUN_COUNT finished at $(date) with exit code $EXIT_CODE"

    # Check if we're done
    REMAINING=$(get_remaining)
    if [[ "$REMAINING" -eq 0 ]]; then
        continue  # Will exit in the next iteration
    fi

    # If there was an error or we still have work, pause and retry
    echo "Pausing $PAUSE_BETWEEN_RUNS seconds before next run..."
    sleep $PAUSE_BETWEEN_RUNS
done

echo ""
echo "Complete! Check $LOG_FILE for full history."
