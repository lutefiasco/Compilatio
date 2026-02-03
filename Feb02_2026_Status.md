# Compilatio Project Status — February 2, 2026

Comprehensive status of the Compilatio IIIF manuscript aggregator project.

---

## Last Production Deployment

| Field | Value |
|-------|-------|
| Date | 2026-02-03 19:24 |
| Deployed | Files + Database |
| Repositories | 14 |
| Manuscripts | 4,728 |

---

## Current Data Summary

| Repository | Manuscripts | Notes |
|------------|-------------|-------|
| Bodleian Library | 1,713 | Greek, Laud Misc., Barocci, etc. |
| Parker Library | 560 | Complete (Corpus Christi College, Cambridge) |
| Trinity College Cambridge | 534 | Thumbnails fixed 2026-02-01 |
| Cambridge University Library | 304 | CUDL API |
| Durham University Library | 287 | IIIF collection tree |
| Harvard Houghton Library | 238 | Latin, Typographic via Biblissima |
| National Library of Wales | 226 | Peniarth |
| Huntington Library | 190 | Ellesmere + HM collection |
| British Library | 178 | Royal, Harley, Cotton |
| Yale Beinecke | 139 | Takamiya collection |
| John Rylands Library | 138 | Latin, English, Hebrew via Biblissima |
| UCLA | 115 | Some thumbnails missing |
| National Library of Scotland | 104 | Gaelic, Early Scottish |
| Lambeth Palace Library | 2 | CUDL subset only |
| **Total** | **4,728** | |

---

## Priority TODO

1. Search functionality
2. Investigate TCC thumbnail slow loading in viewer

---

## Recent Completions

| Date | Task |
|------|------|
| 2026-02-03 | Production sync — 14 repos, 4,728 manuscripts deployed |
| 2026-02-03 | Deployment automation — `deploy_production.sh` with pre-flight checks, SSH sync |
| 2026-02-02 | Harvard/Houghton Library import — 238 manuscripts via Biblissima discovery |
| 2026-02-02 | John Rylands Library import — 138 manuscripts via Biblissima discovery |
| 2026-02-01 | Trinity College Cambridge thumbnails fixed |
| 2026-02-01 | Parker Library shelfmarks fixed |
| 2026-01-31 | Parker Library complete import (560 manuscripts) |
| 2026-01-30 | Trinity College Cambridge import (534 manuscripts) |
| 2026-01-30 | Yale Beinecke Takamiya import (139 manuscripts) |
| 2026-01-29 | Huntington Library import (190 manuscripts) |
| 2026-01-28 | Bodleian thumbnail fixes |

---

## Tech Stack

| Component | Local Dev | Production |
|-----------|-----------|------------|
| Backend | Python/Starlette | PHP 8.x |
| Database | SQLite | MySQL 8.0 |
| Frontend | Vanilla JS | Same |
| Viewer | OpenSeadragon 4.1.1 | Same |
| Hosting | localhost:8000 | oldbooks.humspace.ucla.edu |

---

## Production Deployment

**Production URL:** https://oldbooks.humspace.ucla.edu

**Key constraint:** mod_rewrite is unavailable on Humspace. All JavaScript must use `/api/index.php?action=...` URLs, not `/api/...` directly.

**Automated deployment:**
```bash
./scripts/deploy_production.sh
```

This script runs pre-flight checks and deploys via SSH/rsync:
1. Verifies git is clean and synced with origin
2. Checks `php_deploy/` is in sync with `src/`
3. Validates MySQL export is current
4. Tests SSH connectivity
5. Asks what to deploy (files, database, or both)
6. Deploys via rsync (files) and MySQL CLI (database)

**Individual scripts:**
```bash
python3 scripts/build_php.py       # Convert src/ → php_deploy/
python3 scripts/export_mysql.py    # Export SQLite → MySQL SQL
python3 scripts/verify_deploy.py   # Run all pre-flight checks
```

See **[Production Deployment Guide](docs/plans/Production-Deployment-Guide.md)** for full instructions.

---

## Importer Scripts

All importers located in `scripts/importers/`:

| Script | Repository | Method | Notes |
|--------|------------|--------|-------|
| `bodleian.py` | Bodleian Library | TEI XML parsing | Requires `data/medieval-mss` clone |
| `british_library.py` | British Library | Playwright | JS rendering required |
| `cambridge.py` | Cambridge UL | CUDL IIIF API | — |
| `durham.py` | Durham UL | IIIF collection tree | — |
| `harvard.py` | Harvard Houghton | Biblissima discovery | New 2026-02-02 |
| `huntington.py` | Huntington | CONTENTdm API | — |
| `john_rylands.py` | John Rylands | Biblissima discovery | New 2026-02-02 |
| `lambeth.py` | Lambeth Palace | CUDL subset | Main LUNA portal blocked |
| `nls.py` | NL Scotland | IIIF collection tree | — |
| `nlw.py` | NL Wales | crawl4ai discovery | Requires Python 3.12 |
| `parker.py` | Parker Library | HTML parsing | Manual download required |
| `trinity_cambridge.py` | Trinity Cambridge | Shelfmark enumeration | — |
| `yale_takamiya.py` | Yale Beinecke | JSON API | — |

---

## Known Issues

| Issue | Status |
|-------|--------|
| TCC thumbnails slow in viewer | Open — thumbnails load slowly |
| UCLA thumbnails | Open — some not displaying on browse page |
| favicon.ico 404 | Open |
| ~~Lambeth Palace URL~~ | Fixed 2026-02-02 — `catalogue_url` set to NULL; domain hijacked |
| ~~Parker shelfmarks~~ | Fixed 2026-02-01 |
| ~~TCC thumbnails~~ | Fixed 2026-02-01 |
| ~~Bodleian thumbnails~~ | Fixed 2026-01-28 |
| ~~BL duplicate shelfmarks~~ | Fixed |
| ~~Viewer dropdown (TCC)~~ | Fixed |

---

## Project Structure

```
server.py                    # Starlette app (local dev)
database/
  schema.sql                 # SQLite schema
  compilatio.db              # Database (not in git)
src/                         # Local development files
  index.html, browse.html, viewer.html, about.html
  css/styles.css
  js/script.js, browse.js
  images/border-*.jpg
php_deploy/                  # Production files (PHP/MySQL)
  api/index.php              # PHP API
  (auto-generated from src/ via build_php.py)
scripts/
  importers/                 # All repository importers
  deploy_production.sh       # Main deployment orchestrator
  build_php.py               # src/ → php_deploy/ converter
  export_mysql.py            # SQLite → MySQL exporter
  verify_deploy.py           # Pre-flight checks
mysql_export/                # Exported SQL files (not in git)
docs/
  plans/                     # Current planning docs
  plans/archived/            # Historical design docs
  humspace_transition/       # MySQL migration docs
```

---

## Documentation Index

**Active:**
- `README.md` — Project overview and quick start
- `CLAUDE.md` — AI assistant instructions
- `docs/plans/Production-Deployment-Guide.md` — Deployment instructions
- `docs/plans/Repository_Import_Research.md` — Technical notes on sources
- `docs/plans/Initial_Dev_Plan.md` — Phase history and database recreation

**Import Plans (Complete):**
- `docs/plans/harvard-import-plan.md` — Harvard Houghton (238 MSS)
- `docs/plans/john-rylands-import-plan.md` — John Rylands (138 MSS)

**Historical (Archived):**
- `docs/plans/archived/` — Historical design documents

---

## Dependencies

**Core (requirements.txt):**
```
uvicorn>=0.24.0
starlette>=0.32.0
beautifulsoup4>=4.12.0
httpx>=0.25.0
playwright>=1.40.0  # British Library importer only
```

**Additional (specific importers):**
- `crawl4ai` — Required for NLW importer (Python 3.12)
- `lxml` — Used by some importers for XML parsing

---

## Quick Start

```bash
# Run local server
python server.py
# Visit http://localhost:8000

# Run an importer (example)
python scripts/importers/bodleian.py --execute

# Deploy to production
./scripts/deploy_production.sh
```

---

## Design Principles

- Dark background (#1a1a1a) with ghosted manuscript border decoration
- Elegant serif headings (Cormorant Garamond) + clean sans body (Inter)
- Ivory accent color (#e8e4dc)
- Manuscripts are the visual focus
- Always show source institution attribution
- Background decoration: vine scrollwork from Bodleian MS. Ashmole 764

---

## Future Expansion Candidates

Additional repositories that could be added:

| Repository | Estimated MSS | Notes |
|------------|---------------|-------|
| Walters Art Museum | ~300 | IIIF compliant |
| Morgan Library | ~300 | Corsair collection |
| Bibliothèque nationale | ~200 | Gallica IIIF |
| Bayerische Staatsbibliothek | ~150 | BSB IIIF |

---

*Last updated: 2026-02-03*
