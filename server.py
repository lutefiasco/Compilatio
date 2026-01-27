# server.py - Compilatio server
# Serves static files for IIIF manuscript aggregator

from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles
import uvicorn
import sqlite3
from pathlib import Path

# Project paths
PROJECT_ROOT = Path(__file__).parent
DB_PATH = PROJECT_ROOT / "database" / "manuscripts.db"


def get_db_connection():
    """Get a database connection with optimized settings."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # Performance and reliability pragmas
    conn.execute("PRAGMA busy_timeout = 5000")   # 5 second retry on locks
    conn.execute("PRAGMA journal_mode = WAL")    # Write-ahead logging (faster, less locking)
    conn.execute("PRAGMA synchronous = NORMAL")  # Safe but faster than FULL
    return conn


# Create main app
app = Starlette(routes=[
    # Static files from src/ (catches all)
    Mount("/", app=StaticFiles(directory="src", html=True), name="static"),
])

if __name__ == "__main__":
    print("Starting Compilatio server at http://localhost:8000")
    print("  Static site: http://localhost:8000/")
    uvicorn.run(app, host="0.0.0.0", port=8000)
