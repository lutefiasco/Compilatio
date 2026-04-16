# Compilatio

A browseable aggregator of fully digitized medieval manuscripts from major UK and US repositories, built on IIIF. Not groundbreaking, but a convenience in making visible what's available in one place.

**Live site:** https://oldbooks.humspace.ucla.edu/

## Repositories

| Repository | Manuscripts |
|------------|-------------|
| Bodleian Library | 1,713 |
| British Library | 687 |
| Parker Library (Corpus Christi, Cambridge) | 560 |
| Trinity College Cambridge | 534 |
| Cambridge University Library | 304 |
| Durham University Library | 287 |
| Harvard Houghton Library | 238 |
| National Library of Wales | 226 |
| Huntington Library | 197 |
| Yale Beinecke (Takamiya) | 139 |
| John Rylands Library | 138 |
| UCLA Library | 115 |
| National Library of Scotland | 104 |
| Lambeth Palace Library | 2 |
| **Total** | **5,244** |

## Features

- Browse by repository, collection, and manuscript
- OpenSeadragon IIIF viewer with metadata sidebar and thumbnail grid
- Visual attribution to source institutions with links to original catalogues
- Dark theme, manuscript-forward design

## Tech Stack

- **Production:** PHP 8 / MySQL (hosted on UCLA Humspace)
- **Development:** Python / Starlette / SQLite
- **Frontend:** Vanilla HTML/CSS/JavaScript
- **Viewer:** OpenSeadragon 4.1.1

## Local Development

```bash
git clone https://github.com/lutefiasco/Compilatio.git
cd Compilatio
pip install -r requirements.txt
python server.py
```

Visit http://localhost:8000

## Project Structure

```
server.py              # Starlette development server
database/
  schema.sql           # SQLite schema
  compilatio.db        # Database (not in repo — see Database Recreation)
src/                   # Development source files
  index.html           # Landing page
  browse.html          # Repository/collection/manuscript browser
  viewer.html          # Manuscript viewer (OpenSeadragon)
  about.html           # About page
  css/styles.css
  js/script.js, browse.js
  images/border-*.jpg  # Decoration from MS. Ashmole 764
php_deploy/            # Production files (auto-generated from src/)
  api/index.php        # PHP API
scripts/
  importers/           # Repository-specific import scripts
  build_php.py         # src/ → php_deploy/ converter
  export_mysql.py      # SQLite → MySQL exporter
```

## Database Recreation

The database is not included in the repository. To rebuild from source repositories:

```bash
# Bodleian (requires TEI XML clone)
./scripts/setup_bodleian.sh
python scripts/importers/bodleian.py --execute

# British Library (JSON API pipeline — replaces old Playwright scraper)
python scripts/importers/scrape_bl_inventory.py          # Step 1: full inventory
python scripts/importers/scrape_bl_details.py            # Step 2: filter + fetch details
python scripts/importers/import_bl.py --execute          # Step 3: import to DB
python scripts/importers/sync_bl_concordance.py --execute # Step 4: concordance sync

# Other repositories
python scripts/importers/cambridge.py --execute
python scripts/importers/durham.py --execute
python scripts/importers/harvard.py --execute
python scripts/importers/huntington.py --execute
python scripts/importers/john_rylands.py --execute
python scripts/importers/lambeth.py --execute
python scripts/importers/nls.py --execute
python scripts/importers/nlw.py --execute          # requires Python 3.12 + crawl4ai
python scripts/importers/parker.py --execute
python scripts/importers/trinity_cambridge.py --execute
python scripts/importers/yale_takamiya.py --execute
```

All importers support `--test` (limited run), `--verbose`, `--resume` (checkpoint recovery), and `--discover-only` / `--skip-discovery` for two-phase operation.

## Importer Scripts

| Script | Repository | Method |
|--------|------------|--------|
| `bodleian.py` | Bodleian Library | TEI XML parsing (from GitHub clone) |
| `scrape_bl_inventory.py` | British Library | JSON API (inventory) |
| `scrape_bl_details.py` | British Library | JSON API (detail pages) |
| `import_bl.py` | British Library | JSON → SQLite import |
| `sync_bl_concordance.py` | British Library | Concordance sync |
| `british_library.py` | British Library | Legacy Playwright scraper (superseded) |
| `cambridge.py` | Cambridge UL | CUDL IIIF API |
| `durham.py` | Durham UL | IIIF collection tree |
| `harvard.py` | Harvard Houghton | Biblissima discovery |
| `huntington.py` | Huntington | CONTENTdm API |
| `john_rylands.py` | John Rylands | Biblissima discovery |
| `lambeth.py` | Lambeth Palace | CUDL subset |
| `nls.py` | NL Scotland | IIIF collection tree |
| `nlw.py` | NL Wales | crawl4ai discovery |
| `parker.py` | Parker Library | HTML parsing + IIIF |
| `trinity_cambridge.py` | Trinity Cambridge | Shelfmark enumeration |
| `ucla.py` | UCLA | Direct IIIF |
| `yale_takamiya.py` | Yale Beinecke | JSON API |

## Database Schema

Two tables:

- **`repositories`** — name, short_name, logo_url, catalogue_url
- **`manuscripts`** — shelfmark, collection, repository, dates, contents, iiif_manifest_url, thumbnail_url, source_url

## Design

- Dark background (#1a1a1a) with ghosted manuscript border decoration
- Serif headings (Cormorant Garamond) + sans body (Inter)
- Ivory accent (#e8e4dc)
- Background decoration: vine scrollwork from Bodleian MS. Ashmole 764 (top + right edges, inverted with warm sepia tint)
- Source institution attribution always visible

## Navigation

1. **Landing:** featured manuscript + repository cards with counts
2. **Repository:** collections with manuscript counts
3. **Collection:** manuscript list
4. **Manuscript:** OpenSeadragon viewer with metadata sidebar + thumbnail grid

## License

This project aggregates links to IIIF resources hosted by their respective institutions. No manuscript images are stored or redistributed. All images remain the property of their source institutions.
