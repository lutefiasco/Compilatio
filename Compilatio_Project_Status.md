# Compilatio Project Status

## Priority TODO

1. **[Database Sync to Production](docs/plans/2026-02-01-Database-Sync-to-Production.md)** — Local DB has 4,432 manuscripts; production has 3,119
2. **[Fix Parker Shelfmarks](docs/plans/2026-02-01-Parker-Shelfmark-Fix.md)** — 368/640 have DRUID-based shelfmarks instead of MS numbers
3. Search functionality
4. John Rylands Library exploration

---

## Current Data

| Repository | Manuscripts | Notes |
|------------|-------------|-------|
| Bodleian Library | 1,713 | Greek, Laud Misc., Barocci, etc. |
| Parker Library | 640 | Shelfmarks need fixing |
| Trinity College Cambridge | 534 | Thumbnails fixed 2026-02-01 |
| Cambridge University Library | 304 | CUDL API |
| Durham University Library | 287 | IIIF collection tree |
| National Library of Wales | 226 | Peniarth |
| Huntington Library | 190 | Ellesmere + HM collection |
| British Library | 178 | Royal, Harley, Cotton |
| Yale Beinecke | 139 | Takamiya collection |
| UCLA | 115 | Various |
| National Library of Scotland | 104 | Gaelic, Early Scottish |
| Lambeth Palace Library | 2 | CUDL subset only |
| **Total** | **4,432** | |

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

## Known Issues

| Issue | Status |
|-------|--------|
| Parker shelfmarks | Open — 368 need fixing |
| favicon.ico 404 | Open |
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
```
