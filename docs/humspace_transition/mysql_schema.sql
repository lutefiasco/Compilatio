-- Compilatio MySQL Schema
-- Converted from SQLite for cPanel hosting

-- Drop tables if they exist (for clean reinstall)
DROP TABLE IF EXISTS manuscripts;
DROP TABLE IF EXISTS repositories;

-- Repositories table
CREATE TABLE repositories (
    id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    short_name VARCHAR(100),
    logo_url TEXT,
    catalogue_url TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Manuscripts table
-- Note: date_display, language, folios changed to TEXT (2026-02-03) to accommodate
-- longer values from Bodleian and Cambridge manuscripts
CREATE TABLE manuscripts (
    id INT AUTO_INCREMENT PRIMARY KEY,
    repository_id INT NOT NULL,
    shelfmark VARCHAR(255) NOT NULL,
    collection VARCHAR(255),
    date_display TEXT,
    date_start INT,
    date_end INT,
    contents TEXT,
    provenance TEXT,
    language TEXT,
    folios TEXT,
    iiif_manifest_url TEXT NOT NULL,
    thumbnail_url TEXT,
    source_url TEXT,
    image_count INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (repository_id) REFERENCES repositories(id) ON DELETE CASCADE,
    UNIQUE KEY unique_repo_shelfmark (repository_id, shelfmark),
    INDEX idx_repository_id (repository_id),
    INDEX idx_shelfmark (shelfmark),
    INDEX idx_collection (collection)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
