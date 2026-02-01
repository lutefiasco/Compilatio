// Compilatio Landing Page JavaScript
// Fetches data from API and populates the page

(function() {
    'use strict';

    // API helper - builds URLs without mod_rewrite
    function apiUrl(action, params = {}) {
        const url = new URL('/api/index.php', window.location.origin);
        url.searchParams.set('action', action);
        for (const [key, value] of Object.entries(params)) {
            url.searchParams.set(key, value);
        }
        return url.toString();
    }

    // DOM Elements
    const featuredCard = document.getElementById('featured-card');
    const featuredThumbnail = document.getElementById('featured-thumbnail');
    const featuredShelfmark = document.getElementById('featured-shelfmark');
    const featuredMeta = document.getElementById('featured-meta');
    const featuredContents = document.getElementById('featured-contents');
    const repoGrid = document.getElementById('repo-grid');
    const statManuscripts = document.getElementById('stat-manuscripts');
    const statIiif = document.getElementById('stat-iiif');
    const statRepositories = document.getElementById('stat-repositories');

    document.addEventListener('DOMContentLoaded', async () => {
        // Load all data in parallel
        await Promise.all([
            loadFeatured(),
            loadRepositories()
        ]);
    });

    /**
     * Load featured manuscript
     */
    async function loadFeatured() {
        try {
            const response = await fetch(apiUrl('featured'));
            if (!response.ok) throw new Error('Failed to fetch featured');

            const ms = await response.json();

            // Update featured card
            if (featuredCard) {
                featuredCard.href = `viewer.html?ms=${ms.id}`;
            }

            // Update thumbnail
            if (featuredThumbnail) {
                if (ms.thumbnail_url) {
                    const img = document.createElement('img');
                    img.src = ms.thumbnail_url;
                    img.alt = ms.shelfmark || 'Manuscript thumbnail';
                    img.className = 'featured-thumbnail';
                    img.onerror = () => {
                        // Replace with placeholder on error
                        featuredThumbnail.innerHTML = '<span>No image</span>';
                    };
                    featuredThumbnail.replaceWith(img);
                } else {
                    featuredThumbnail.innerHTML = '<span>No image</span>';
                }
            }

            // Update text
            if (featuredShelfmark) {
                featuredShelfmark.textContent = ms.shelfmark || 'Unknown';
            }

            if (featuredMeta) {
                const parts = [];
                if (ms.repository) parts.push(ms.repository);
                if (ms.date_display) parts.push(ms.date_display);
                featuredMeta.textContent = parts.join(' \u2022 ');
            }

            if (featuredContents) {
                featuredContents.textContent = ms.contents || '';
            }

        } catch (err) {
            console.error('Failed to load featured manuscript:', err);
            if (featuredShelfmark) {
                featuredShelfmark.textContent = 'Unable to load';
            }
        }
    }

    /**
     * Load repositories and stats
     */
    async function loadRepositories() {
        try {
            const response = await fetch(apiUrl('repositories'));
            if (!response.ok) throw new Error('Failed to fetch repositories');

            const repos = await response.json();

            // Calculate stats
            let totalManuscripts = 0;
            repos.forEach(repo => {
                totalManuscripts += repo.manuscript_count || 0;
            });

            // Update stats
            if (statManuscripts) {
                statManuscripts.textContent = totalManuscripts.toLocaleString();
            }
            if (statRepositories) {
                statRepositories.textContent = repos.length;
            }

            // For IIIF count, we'd need another API call or include it in repos
            // For now, show total as placeholder
            if (statIiif) {
                statIiif.textContent = '--';
                // Try to get IIIF count from manuscripts API
                loadIiifCount();
            }

            // Render repository cards
            if (repoGrid) {
                if (repos.length === 0) {
                    repoGrid.innerHTML = '<div class="empty-state"><p>No repositories found</p></div>';
                    return;
                }

                repoGrid.innerHTML = repos.map(repo => `
                    <a href="browse.html?repo=${repo.id}" class="repo-card">
                        <h3 class="repo-name">${escapeHtml(repo.name)}</h3>
                        <p class="repo-count"><strong>${repo.manuscript_count || 0}</strong> manuscripts</p>
                    </a>
                `).join('');
            }

        } catch (err) {
            console.error('Failed to load repositories:', err);
            if (repoGrid) {
                repoGrid.innerHTML = '<div class="empty-state"><p>Unable to load repositories</p></div>';
            }
        }
    }

    /**
     * Load IIIF manuscript count
     */
    async function loadIiifCount() {
        try {
            // Fetch a small batch to get the total with IIIF
            const response = await fetch(apiUrl('manuscripts', { limit: 1 }));
            if (!response.ok) return;

            const data = await response.json();

            // The API returns total count - for IIIF we'd need server-side filtering
            // For now, we'll just show a placeholder
            // TODO: Add API endpoint for stats with IIIF count

        } catch (err) {
            console.error('Failed to load IIIF count:', err);
        }
    }

    /**
     * Escape HTML special characters
     */
    function escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

})();
