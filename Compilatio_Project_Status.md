# Compilatio Project Status

**For comprehensive project status, see [Feb02_2026_Status.md](Feb02_2026_Status.md).**

## Last Production Deployment

| Field | Value |
|-------|-------|
| Date | 2026-02-03 19:24 |
| Deployed | Files + Database |
| Repositories | 14 |
| Manuscripts | 4,728 |

---

## Priority TODO

1. Search functionality
2. Investigate TCC thumbnail slow loading in viewer

**Completed:**
- Production sync (2026-02-03) — 14 repos, 4,728 manuscripts deployed via automated script
- Deployment automation (2026-02-03) — `./scripts/deploy_production.sh` with pre-flight checks
- Harvard/Houghton Library import (2026-02-02) — 238 manuscripts via Biblissima discovery
- John Rylands Library import (2026-02-02) — 138 manuscripts via Biblissima discovery

---

## Current Data

| Repository | Manuscripts | Notes |
|------------|-------------|-------|
| Bodleian Library | 1,713 | Greek, Laud Misc., Barocci, etc. |
| Parker Library | 560 | Complete |
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

## Tech Stack

| Component | Local Dev | Production |
|-----------|-----------|------------|
| Backend | Python/Starlette | PHP 8.x |
| Database | SQLite | MySQL 8.0 |
| Frontend | Vanilla JS | Same |
| Viewer | OpenSeadragon 4.1.1 | Same |
| Hosting | localhost:8000 | oldbooks.humspace.ucla.edu |

**Deployment:** Run `./scripts/deploy_production.sh` for automated deployment with pre-flight checks.

**Never edit php_deploy/ directly** — edit `src/` and run `python3 scripts/build_php.py` to transform API URLs. See **[Production Deployment Guide](docs/plans/Production-Deployment-Guide.md)**.

---

## Known Issues

| Issue | Status |
|-------|--------|
| TCC thumbnails slow | Open — thumbnails load very slowly in viewer, investigate |
| UCLA thumbnails | Open — some not displaying on browse page |
| favicon.ico 404 | Open |
| ~~Lambeth Palace URL~~ | Fixed 2026-02-02 — `catalogue_url` set to NULL; domain hijacked |
| ~~Parker shelfmarks~~ | Fixed 2026-02-01 |
| ~~TCC thumbnails~~ | Fixed 2026-02-01 |
| ~~Bodleian thumbnails~~ | Fixed 2026-01-28 |
| ~~BL duplicate shelfmarks~~ | Fixed |
| ~~Viewer dropdown (TCC)~~ | Fixed |

---

## Documentation

- **[Initial Development Plan](docs/plans/Initial_Dev_Plan.md)** — Phases 1-8 history, database recreation instructions
- **[Humspace Transition](docs/humspace_transition/)** — MySQL schema, migration plan, export files
- **[Repository Import Research](docs/plans/Repository_Import_Research.md)** — Technical notes on new sources
- **[Archived Plans](docs/plans/archived/)** — Historical design documents

---

## Quick Start

```bash
# Run local server
python server.py
# Visit http://localhost:8000

# Run importer (example)
python scripts/importers/bodleian.py --execute

# Deploy to production
./scripts/deploy_production.sh
```
