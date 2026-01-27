# Compilatio

IIIF manuscript aggregator for medieval manuscripts from British repositories (Bodleian, British Library) and eventually Huntington.

## Project Status

See [Compilatio_Project_Status.md](Compilatio_Project_Status.md) for current implementation status and next steps.

## Core Concept

- **Browse by Repository → Collection → Manuscript** (not search-first)
- Visual attribution to source institutions always visible
- Universal Viewer embedded directly
- Dark theme, manuscript-forward design

## Tech Stack

- **Backend**: Python/Starlette
- **Database**: SQLite
- **Frontend**: Vanilla JS with ES modules
- **Viewer**: Universal Viewer v4.2.1 (via CDN)

## Project Structure

```
server.py              # Starlette app
database/
  schema.sql           # SQLite schema
  compilatio.db        # Database
src/
  index.html           # Landing page
  viewer.html          # Manuscript viewer (loads UV from CDN)
  css/styles.css
  js/
    script.js          # Main functionality
    viewer.js          # Universal Viewer setup + metadata
```

## Database Schema

Key tables:
- `manuscripts` - shelfmark, collection, repository, dates, contents, iiif_manifest_url, thumbnail_url
- `repositories` - name, short_name, logo_url, catalogue_url

## Design Principles

- Dark charcoal background (#2a2a2a)
- Manuscripts are the visual focus
- Minimal chrome, clean sans-serif typography
- Always show source institution attribution with link to original catalogue

## Navigation Flow

1. Landing: featured manuscript + repository cards with counts
2. Repository: see collections with manuscript counts
3. Collection: see manuscripts
4. Manuscript: Universal Viewer (~75% width) + collapsible metadata sidebar
