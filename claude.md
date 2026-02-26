# Compilatio

IIIF manuscript aggregator for medieval manuscripts. 14 repositories, 4,728 manuscripts including Bodleian, British Library, Cambridge, Harvard, Yale, Huntington, and others.

## Project Status

See [Feb04_2026_Status.md](Feb04_2026_Status.md) for current implementation status and next steps.

## Core Concept

- **Browse by Repository → Collection → Manuscript** (not search-first)
- Visual attribution to source institutions always visible
- OpenSeadragon viewer with custom controls
- Dark theme, manuscript-forward design

## Concordance — Cross-Project Shelfmark Matching

**ALWAYS use the concordance when shelfmarks are involved.** Any time you cross-reference manuscripts across projects, look up external catalogue URLs, or match shelfmark variants, use `~/Geekery/Scriptorium/database/concordance.db` — not ad hoc `LIKE '%shelfmark%'` queries. The concordance is the authoritative source of truth for shelfmark forms across all projects.

The concordance is a **controlled vocabulary** (12,545 rows as of Feb 2026) with permanent, stable IDs used as foreign keys across all projects. It was seeded from Compilatio (4,746 manuscripts) and is the primary canonical source. The `concordance` table has a `compilatio_id` column that links back to `manuscripts.id` in this database.

**New manuscripts must be registered in the concordance.** Any importer that adds manuscripts to Compilatio must also update the concordance so other projects (Anglicana, Cotton, etc.) can cross-reference them. After running an importer with `--execute`, run:

```bash
cd ~/Geekery/Scriptorium && source .venv/bin/activate && python3 tools/build_concordance.py --update
```

This will match new Compilatio manuscripts against the concordance (or create new rows for them) and log full provenance. Never use `--rebuild` — the concordance now uses append-only `--init`/`--update` to preserve permanent IDs.

**Audit:** `python3 tools/build_concordance.py --audit` — shows per-project coverage, cross-project overlap, and potential issues.

## Tech Stack

- **Backend**: Python/Starlette
- **Database**: SQLite
- **Frontend**: Vanilla JS with ES modules
- **Viewer**: OpenSeadragon 4.1.1 (via CDN) with custom IIIF manifest parser

## Project Structure

```
server.py              # Starlette app (local dev)
database/
  schema.sql           # SQLite schema
  compilatio.db        # Database (not in git)
src/                   # Local development files (edit these)
  index.html           # Landing page
  browse.html          # Repository/collection/manuscript browser
  viewer.html          # Manuscript viewer (OpenSeadragon)
  about.html           # About page
  css/styles.css       # Main stylesheet
  js/script.js, browse.js
  images/border-*.jpg  # Decoration from MS. Ashmole 764
php_deploy/            # Production files (auto-generated, don't edit)
  api/index.php        # PHP API
scripts/
  deploy_production.sh # Main deployment orchestrator
  build_php.py         # src/ → php_deploy/ converter
  export_mysql.py      # SQLite → MySQL exporter
  importers/           # All repository importers
```

## Database Schema

Key tables:
- `manuscripts` - shelfmark, collection, repository, dates, contents, iiif_manifest_url, thumbnail_url
- `repositories` - name, short_name, logo_url, catalogue_url

## Design Principles

- Dark background (#1a1a1a) with ghosted manuscript border decoration
- Elegant serif headings (Cormorant Garamond) + clean sans body (Inter)
- Ivory accent color (#e8e4dc) - no gold
- Manuscripts are the visual focus
- Minimal chrome, refined typography
- Always show source institution attribution with link to original catalogue
- Background decoration: vine scrollwork from Bodleian MS. Ashmole 764 (top + right edges, inverted with warm sepia tint)

## Navigation Flow

1. Landing: featured manuscript + repository cards with counts
2. Repository: see collections with manuscript counts
3. Collection: see manuscripts
4. Manuscript: OpenSeadragon viewer with metadata sidebar + thumbnail grid

## Deployment

Production is at https://oldbooks.humspace.ucla.edu/ (PHP/MySQL on UCLA Humspace).

**Deploy workflow:**
```bash
./scripts/deploy_production.sh
```

This runs pre-flight checks (git status, file sync, database export, SSH connectivity), then asks whether to deploy files, database, or both.

**Individual scripts:**
- `scripts/build_php.py` — Convert src/ → php_deploy/ (transforms API URLs)
- `scripts/export_mysql.py` — Export SQLite → MySQL-compatible SQL
- `scripts/verify_deploy.py` — Run all pre-flight checks

**Important:** Never edit php_deploy/ directly. Always edit src/ and run `build_php.py`.

## Documentation Maintenance

Planning documents (status files, import plans, expansion docs) should be updated frequently as work progresses. Keep them current with latest findings, completed tasks, and next steps.

**Always check `~/Geekery/Scriptorium/docs/active-planning.md`** — this is the cross-project planning index. If your change affects project status, active work items, or known issues, update it there too. This applies across all related projects (Scriptorium, CONR, RONR, Anglicana, Connundra, Compilatio).
