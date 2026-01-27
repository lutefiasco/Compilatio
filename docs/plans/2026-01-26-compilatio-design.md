# Compilatio: IIIF Manuscript Aggregator

## Overview

Compilatio is a public-facing IIIF manuscript aggregator providing frictionless access to digitized medieval manuscripts from British repositories (Bodleian, British Library, eventually Cambridge) and the Huntington. It serves as an "easy first stop" before diving into institutional catalogues.

### Core Principles

- **Repository and collection as organizing principles** - Users browse by institution, then by named collection (Cotton, Harley, Junius, Ashmole, etc.)
- **Visual attribution** - Every manuscript clearly shows its source institution; we aggregate, not appropriate
- **Quality threshold** - Only manuscripts with multiple IIIF images; single-page items excluded
- **Frictionless viewing** - Universal Viewer embedded directly, no click-throughs required
- **Scholarly utility** - Normalized metadata for comparison across institutions

### What It Is Not

- Not a personal research tool (no photos, no notes, no DevonThink)
- Not a comprehensive catalogue (we link to those)
- Not a search-first interface (browse and discovery take priority)

### Target Audience

1. Scholars who know what they're looking for but want quick access without navigating multiple catalogues
2. Enthusiasts exploring illuminated manuscripts and medieval material culture

---

## Information Architecture

### Navigation Hierarchy

```
Repository (Bodleian, British Library, ...)
  └── Collection (Cotton, Harley, Junius, Ashmole, ...)
        └── Manuscript (Cotton Nero A.x, Junius 11, ...)
```

### Page Structure

**Landing Page**
- Single featured manuscript (rotating/curated)
- Repository cards with manuscript counts
- Secondary search bar

**Browse Page**
- Repository → collections with counts
- Collection → manuscripts in that collection

**Viewer Page**
- Universal Viewer (~75% width)
- Collapsible metadata sidebar
- Attribution block (always visible)
- Breadcrumb navigation (Repository > Collection > Manuscript)

### Browse Flow

1. Landing: see featured manuscript + repository cards
2. Click repository → see its collections with counts
3. Click collection → see manuscripts
4. Click manuscript → viewer with metadata sidebar

---

## Metadata Model

### Core Fields (normalized across repositories)

- **Shelfmark** - Canonical identifier
- **Date/date range** - Display format ("s. xi", "c. 1400") plus sortable year range
- **Holding institution** - Repository name
- **Contents** - What the manuscript contains
- **Provenance** - Ownership history (if available)
- **Record origin** - Where this data came from (attribution)

### Database Schema

```sql
manuscripts (
    id                  INTEGER PRIMARY KEY,
    shelfmark           TEXT NOT NULL,
    collection          TEXT,
    repository          TEXT NOT NULL,
    date_display        TEXT,
    date_start          INTEGER,
    date_end            INTEGER,
    contents            TEXT,
    provenance          TEXT,
    iiif_manifest_url   TEXT NOT NULL,
    record_origin       TEXT,
    source_url          TEXT,
    thumbnail_url       TEXT,
    image_count         INTEGER,
    created_at          DATETIME,
    updated_at          DATETIME
)

repositories (
    id                  INTEGER PRIMARY KEY,
    name                TEXT NOT NULL,
    short_name          TEXT,
    logo_url            TEXT,
    catalogue_url       TEXT
)
```

Schema will be kept simple and altered as needed via migration scripts.

---

## Visual Design

### Direction: Manuscript-Forward

Dark, warm charcoal background. Manuscripts are the star. Minimal chrome.

**Landing Page**

```
┌─────────────────────────────────────────────────────────────┐
│ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │
│ ░░  COMPILATIO                              [Search...]  ░░ │
│ ░░  Medieval Manuscripts · British Collections           ░░ │
│ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │
│ ░░                                                       ░░ │
│ ░░      ┌────────────────────────────────────┐           ░░ │
│ ░░      │                                    │           ░░ │
│ ░░      │         [ Featured Image ]         │           ░░ │
│ ░░      │                                    │           ░░ │
│ ░░      └────────────────────────────────────┘           ░░ │
│ ░░       Cotton Nero A.x · British Library · s. xiv      ░░ │
│ ░░                                                       ░░ │
│ ░░  ────────────────────────────────────────────────     ░░ │
│ ░░                                                       ░░ │
│ ░░  Bodleian Library          British Library            ░░ │
│ ░░  142 manuscripts           203 manuscripts            ░░ │
│ ░░                                                       ░░ │
│ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░ │
└─────────────────────────────────────────────────────────────┘
```

**Viewer Page**

```
┌─────────────────────────────────────────────────────────────┐
│ ░░ COMPILATIO  ← Back to Bodleian > Junius      [Search] ░░ │
├───────────────────────────────────────────┬─────────────────┤
│ ░░                                     ░░ │ JUNIUS 11       │
│ ░░                                     ░░ │ ───────────     │
│ ░░                                     ░░ │                 │
│ ░░       [ UNIVERSAL VIEWER ]          ░░ │ Date            │
│ ░░                                     ░░ │ s. x/xi         │
│ ░░    thumbnail strip at top           ░░ │                 │
│ ░░    pan / zoom / page nav            ░░ │ Contents        │
│ ░░                                     ░░ │ OE Genesis,     │
│ ░░                                     ░░ │ Exodus, Daniel  │
│ ░░                                     ░░ │                 │
│ ░░                                     ░░ ├─────────────────┤
│ ░░                                     ░░ │ [Bodleian Logo] │
│ ░░                                     ░░ │ View in         │
│ ░░                                     ░░ │ Bodleian Cat.   │
└───────────────────────────────────────────┴─────────────────┘
```

### Style Notes

- Dark charcoal background (#2a2a2a or similar)
- Manuscript images pop against dark
- Minimal typography - clean sans-serif
- Repository attribution always visible
- Clicking featured image or repository → browse/viewer

---

## Technical Architecture

### Stack

- **Backend**: Python/Starlette (simplified from Connundra)
- **Database**: SQLite
- **Frontend**: Vanilla JS with ES modules
- **Viewer**: Universal Viewer v4.x (via CDN)
- **Hosting**: UCLA (oldbooks.humspace.ucla.edu)

### Project Structure

```
Compilatio/
├── server.py                 # Starlette app
├── database/
│   ├── compilatio.db
│   └── schema.sql
├── src/
│   ├── index.html            # Landing page
│   ├── browse.html           # Repository/collection browser
│   ├── viewer.html           # Manuscript viewer
│   ├── css/
│   │   └── styles.css
│   └── js/
│       ├── main.js           # Landing page
│       ├── browse.js         # Browse/filter
│       ├── viewer.js         # UV setup + metadata
│       └── api.js            # Shared API calls
├── scripts/
│   ├── importers/
│   │   ├── bodleian.py
│   │   └── british_library.py
│   └── migrations/
└── docs/
    └── plans/
```

### What Gets Removed from Connundra

- Photo sync, thumbnail generation, HEIC handling
- DevonThink notes integration
- Personal research fields (keywords, relations, study notes)
- Matchers (replaced by importers)
- Datasette (not appropriate for public-facing site)

---

## Repository Data Sources

### Phase 1: Bodleian

- Source: TEI XML files (already cloned in Connundra)
- Parser: Adapt existing `bodleian_tei.py`
- Collections: Junius, Ashmole, Laud Misc, Rawlinson, etc.
- IIIF: Well-structured manifests from Digital Bodleian

### Phase 2: British Library

- Source: searcharchives.bl.uk (web scraping)
- Parser: Adapt existing BL scraper
- Collections: Cotton, Harley, Royal, Additional, etc.
- Issues: Bot access restrictions; need caching/rate limiting

### Deferred

- Cambridge University Library
- Huntington Library

---

## Implementation Phases

### Phase 1: Foundation

- Fork Connundra repository → Compilatio
- Strip photos, notes, DevonThink integration
- Simplify database schema
- Basic Starlette server with static files

### Phase 2: Bodleian Import

- Adapt TEI parser for Compilatio schema
- Import from existing XML files
- Filter single-image manuscripts (image_count >= 2)
- Extract collection names from shelfmarks

### Phase 3: Core UI

- Landing page (dark theme, featured manuscript, repository cards)
- Browse page (repository → collection → manuscript)
- Viewer page with Universal Viewer
- Metadata sidebar with attribution

### Phase 4: British Library

- Adapt BL scraper/importer
- Handle bot-access issues
- Map BL collections

### Phase 5: Polish

- Search functionality
- Responsive design
- Featured manuscript rotation
- Performance optimization

### Deferred

- Cambridge, Huntington importers
- Additional repositories

---

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Viewer | Universal Viewer | Cleaner thumbnail navigation, simpler interface for "first stop" use case |
| Frontend | Vanilla JS + ES modules | No framework dependencies, better organized than single file |
| Database | SQLite | Simple, portable, sufficient for read-heavy workload |
| Hosting | UCLA institutional | Scholarly credibility, free, stable |
| Design | Dark/manuscript-forward | Images are the star, not the interface |
| Navigation | Repository → Collection → MS | Matches how scholars think about these collections |

---

## Attribution Requirements

Every manuscript view must clearly show:

1. Source institution name
2. Institution logo (where available)
3. Link to institutional catalogue record
4. Link to institution's own viewer

This respects the institutions providing the data and images, and gives users a path to authoritative sources.
