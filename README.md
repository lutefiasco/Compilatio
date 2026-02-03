# Compilatio

A quick-and-dirty site that assembles completely digitized medieval manuscripts (mostly from UK repositories) in one location. It's not at all groundbreaking, but it is a bit of a convenience in making visible what's available.

**Live site:** https://oldbooks.humspace.ucla.edu/

## Repositories

| Repository | Manuscripts |
|------------|-------------|
| Bodleian Library | 1,713 |
| Parker Library (Corpus Christi, Cambridge) | 560 |
| Trinity College Cambridge | 534 |
| Cambridge University Library | 304 |
| Durham University Library | 287 |
| Harvard Houghton Library | 238 |
| National Library of Wales | 226 |
| Huntington Library | 190 |
| British Library | 178 |
| Yale Beinecke (Takamiya) | 139 |
| John Rylands Library | 138 |
| UCLA Library | 115 |
| National Library of Scotland | 104 |
| Lambeth Palace Library | 2 |
| **Total** | **4,728** |

## Features

- Browse by repository, collection, and manuscript
- OpenSeadragon IIIF viewer with metadata sidebar
- Visual attribution to source institutions
- Dark theme, manuscript-forward design

## Tech Stack

- **Production:** PHP 8 / MySQL (hosted on UCLA Humspace)
- **Development:** Python / Starlette / SQLite
- **Frontend:** Vanilla HTML/CSS/JavaScript
- **Viewer:** OpenSeadragon 4.1.1

## Local Development

```bash
# Clone and set up
git clone https://github.com/lutefiasco/Compilatio.git
cd Compilatio

# Install dependencies
pip install -r requirements.txt

# Run the development server
python server.py
```

Visit http://localhost:8000

## Database Recreation

The database is not included in the repository. To rebuild from source repositories:

```bash
# Bodleian (requires TEI XML clone)
./scripts/setup_bodleian.sh
python scripts/importers/bodleian.py --execute

# British Library (requires Playwright)
pip install playwright && playwright install chromium
python scripts/importers/british_library.py --collection cotton --execute
python scripts/importers/british_library.py --collection harley --execute
python scripts/importers/british_library.py --collection royal --execute

# Other repositories (see docs/plans/Initial_Dev_Plan.md for full list)
python scripts/importers/cambridge.py --execute
python scripts/importers/durham.py --execute
# ... etc.
```

## Deployment

Deploy to production (https://oldbooks.humspace.ucla.edu/):

```bash
# Full deployment with pre-flight checks
./scripts/deploy_production.sh
```

The script will:
1. Verify git is clean and synced
2. Check php_deploy/ is current
3. Validate MySQL export
4. Test SSH connectivity
5. Ask what to deploy (files, database, or both)

**Manual steps:**
```bash
# Convert src/ to php_deploy/ (run after editing src/)
python3 scripts/build_php.py

# Export database (run after database changes)
python3 scripts/export_mysql.py

# Just run checks without deploying
python3 scripts/verify_deploy.py
```

See [Production Deployment Guide](docs/plans/Production-Deployment-Guide.md) for detailed documentation.

## Project Status

See [Feb02_2026_Status.md](Feb02_2026_Status.md) for comprehensive project status.

See [Compilatio_Project_Status.md](Compilatio_Project_Status.md) for quick reference.

---

*Last updated: 2026-02-02*
