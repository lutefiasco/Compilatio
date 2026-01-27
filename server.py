# server.py - Compilatio server
# IIIF manuscript aggregator with API and static file serving

from starlette.applications import Starlette
from starlette.routing import Route, Mount
from starlette.staticfiles import StaticFiles
from starlette.responses import JSONResponse
import uvicorn
import sqlite3
from pathlib import Path

# Project paths
PROJECT_ROOT = Path(__file__).parent
DB_PATH = PROJECT_ROOT / "database" / "compilatio.db"


def get_db_connection():
    """Get a database connection with optimized settings."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def dict_from_row(row):
    """Convert sqlite3.Row to dict."""
    return dict(row) if row else None


# API Endpoints

async def api_repositories(request):
    """List all repositories with manuscript counts."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            r.id, r.name, r.short_name, r.logo_url, r.catalogue_url,
            COUNT(m.id) as manuscript_count
        FROM repositories r
        LEFT JOIN manuscripts m ON m.repository_id = r.id
        GROUP BY r.id
        ORDER BY r.name
    """)

    repos = [dict_from_row(row) for row in cursor.fetchall()]
    conn.close()

    return JSONResponse(repos)


async def api_repository_detail(request):
    """Get a single repository with its collections."""
    repo_id = request.path_params.get("id")
    conn = get_db_connection()
    cursor = conn.cursor()

    # Get repository
    cursor.execute(
        "SELECT * FROM repositories WHERE id = ?",
        (repo_id,)
    )
    repo = dict_from_row(cursor.fetchone())

    if not repo:
        conn.close()
        return JSONResponse({"error": "Repository not found"}, status_code=404)

    # Get collections with counts
    cursor.execute("""
        SELECT collection, COUNT(*) as count
        FROM manuscripts
        WHERE repository_id = ? AND collection IS NOT NULL
        GROUP BY collection
        ORDER BY collection
    """, (repo_id,))

    repo["collections"] = [
        {"name": row["collection"], "count": row["count"]}
        for row in cursor.fetchall()
    ]

    conn.close()
    return JSONResponse(repo)


async def api_manuscripts(request):
    """List manuscripts with optional filtering."""
    params = request.query_params

    repo_id = params.get("repository_id")
    collection = params.get("collection")
    limit = min(int(params.get("limit", 50)), 200)
    offset = int(params.get("offset", 0))

    conn = get_db_connection()
    cursor = conn.cursor()

    # Build query
    where_clauses = []
    query_params = []

    if repo_id:
        where_clauses.append("m.repository_id = ?")
        query_params.append(repo_id)

    if collection:
        where_clauses.append("m.collection = ?")
        query_params.append(collection)

    where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

    # Get total count
    cursor.execute(f"""
        SELECT COUNT(*) as total FROM manuscripts m {where_sql}
    """, query_params)
    total = cursor.fetchone()["total"]

    # Get manuscripts
    cursor.execute(f"""
        SELECT
            m.id, m.shelfmark, m.collection, m.date_display,
            m.contents, m.thumbnail_url, m.iiif_manifest_url,
            r.short_name as repository
        FROM manuscripts m
        JOIN repositories r ON r.id = m.repository_id
        {where_sql}
        ORDER BY m.collection, m.shelfmark
        LIMIT ? OFFSET ?
    """, query_params + [limit, offset])

    manuscripts = [dict_from_row(row) for row in cursor.fetchall()]
    conn.close()

    return JSONResponse({
        "total": total,
        "limit": limit,
        "offset": offset,
        "manuscripts": manuscripts
    })


async def api_manuscript_detail(request):
    """Get a single manuscript with full details."""
    ms_id = request.path_params.get("id")
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            m.*,
            r.name as repository_name,
            r.short_name as repository_short,
            r.logo_url as repository_logo,
            r.catalogue_url as repository_catalogue
        FROM manuscripts m
        JOIN repositories r ON r.id = m.repository_id
        WHERE m.id = ?
    """, (ms_id,))

    manuscript = dict_from_row(cursor.fetchone())
    conn.close()

    if not manuscript:
        return JSONResponse({"error": "Manuscript not found"}, status_code=404)

    return JSONResponse(manuscript)


async def api_featured(request):
    """Get a featured manuscript for the landing page."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # For now, pick a random manuscript with a thumbnail
    cursor.execute("""
        SELECT
            m.id, m.shelfmark, m.collection, m.date_display,
            m.contents, m.thumbnail_url, m.iiif_manifest_url,
            r.short_name as repository
        FROM manuscripts m
        JOIN repositories r ON r.id = m.repository_id
        WHERE m.thumbnail_url IS NOT NULL
        ORDER BY RANDOM()
        LIMIT 1
    """)

    featured = dict_from_row(cursor.fetchone())
    conn.close()

    if not featured:
        return JSONResponse({"error": "No manuscripts available"}, status_code=404)

    return JSONResponse(featured)


# Routes
api_routes = [
    Route("/api/repositories", api_repositories),
    Route("/api/repositories/{id:int}", api_repository_detail),
    Route("/api/manuscripts", api_manuscripts),
    Route("/api/manuscripts/{id:int}", api_manuscript_detail),
    Route("/api/featured", api_featured),
]

# Create main app
app = Starlette(routes=[
    *api_routes,
    # Static files from src/ (catches all, must be last)
    Mount("/", app=StaticFiles(directory="src", html=True), name="static"),
])

if __name__ == "__main__":
    print("Starting Compilatio server at http://localhost:8000")
    print("  Static site: http://localhost:8000/")
    print("  API: http://localhost:8000/api/")
    uvicorn.run(app, host="0.0.0.0", port=8000)
