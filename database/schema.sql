-- Compilatio Database Schema
-- IIIF Manuscript Aggregator

-- Repositories table
CREATE TABLE IF NOT EXISTS repositories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    short_name TEXT,
    logo_url TEXT,
    catalogue_url TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Manuscripts table (simplified)
CREATE TABLE IF NOT EXISTS manuscripts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repository_id INTEGER NOT NULL,
    shelfmark TEXT NOT NULL,
    collection TEXT,
    date_display TEXT,
    date_start INTEGER,
    date_end INTEGER,
    contents TEXT,
    provenance TEXT,
    language TEXT,
    folios TEXT,
    iiif_manifest_url TEXT NOT NULL,
    thumbnail_url TEXT,
    source_url TEXT,
    image_count INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (repository_id) REFERENCES repositories(id),
    UNIQUE(repository_id, shelfmark)
);

CREATE INDEX IF NOT EXISTS idx_repository_id ON manuscripts(repository_id);
CREATE INDEX IF NOT EXISTS idx_shelfmark ON manuscripts(shelfmark);
CREATE INDEX IF NOT EXISTS idx_collection ON manuscripts(collection);
