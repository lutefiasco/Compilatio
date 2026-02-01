// Compilatio Browse Page JavaScript
// Handles Repository -> Collection -> Manuscript navigation

(function() {
    'use strict';

    const API_BASE = '/api';
    const ITEMS_PER_PAGE = 24;

    // State
    let currentRepo = null;
    let currentCollection = null;
    let currentOffset = 0;
    let totalItems = 0;

    // DOM Elements
    const breadcrumb = document.getElementById('breadcrumb');
    const browseTitle = document.getElementById('browse-title');
    const browseSubtitle = document.getElementById('browse-subtitle');
    const browseContent = document.getElementById('browse-content');
    const pagination = document.getElementById('pagination');
    const prevBtn = document.getElementById('prev-btn');
    const nextBtn = document.getElementById('next-btn');
    const paginationInfo = document.getElementById('pagination-info');
    const pageInput = document.getElementById('page-input');
    const totalPagesSpan = document.getElementById('total-pages');

    document.addEventListener('DOMContentLoaded', () => {
        // Parse URL parameters
        const params = new URLSearchParams(window.location.search);
        currentRepo = params.get('repo');
        currentCollection = params.get('collection');
        currentOffset = parseInt(params.get('offset') || '0', 10);

        // Set up pagination handlers
        if (prevBtn) prevBtn.addEventListener('click', goToPrevPage);
        if (nextBtn) nextBtn.addEventListener('click', goToNextPage);
        if (pageInput) {
            pageInput.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    goToPage(parseInt(pageInput.value, 10));
                }
            });
            pageInput.addEventListener('blur', () => {
                goToPage(parseInt(pageInput.value, 10));
            });
        }

        // Load appropriate view
        if (currentRepo && currentCollection) {
            loadManuscripts();
        } else if (currentRepo) {
            loadCollections();
        } else {
            loadRepositories();
        }
    });

    /**
     * Update URL without page reload
     */
    function updateUrl() {
        const params = new URLSearchParams();
        if (currentRepo) params.set('repo', currentRepo);
        if (currentCollection) params.set('collection', currentCollection);
        if (currentOffset > 0) params.set('offset', currentOffset);

        const newUrl = `browse.html${params.toString() ? '?' + params.toString() : ''}`;
        window.history.pushState({}, '', newUrl);
    }

    /**
     * Load all repositories
     */
    async function loadRepositories() {
        updateBreadcrumb([{ label: 'Home', href: 'index.html' }, { label: 'Browse' }]);
        browseTitle.textContent = 'Repositories';
        browseSubtitle.textContent = 'Select a repository to explore its collections';
        pagination.classList.add('hidden');

        try {
            const response = await fetch(`${API_BASE}/repositories`);
            if (!response.ok) throw new Error('Failed to fetch');

            const repos = await response.json();

            if (repos.length === 0) {
                browseContent.innerHTML = '<div class="empty-state"><p>No repositories found</p></div>';
                return;
            }

            browseContent.innerHTML = `
                <div class="repo-grid">
                    ${repos.map(repo => `
                        <a href="browse.html?repo=${repo.id}" class="repo-card" data-repo-id="${repo.id}">
                            <h3 class="repo-name">${escapeHtml(repo.name)}</h3>
                            <p class="repo-count"><strong>${repo.manuscript_count || 0}</strong> manuscripts</p>
                        </a>
                    `).join('')}
                </div>
            `;

            // Add click handlers for SPA-style navigation
            browseContent.querySelectorAll('.repo-card').forEach(card => {
                card.addEventListener('click', (e) => {
                    e.preventDefault();
                    currentRepo = card.dataset.repoId;
                    currentCollection = null;
                    currentOffset = 0;
                    updateUrl();
                    loadCollections();
                });
            });

        } catch (err) {
            console.error('Failed to load repositories:', err);
            browseContent.innerHTML = '<div class="empty-state"><p>Unable to load repositories</p></div>';
        }
    }

    /**
     * Load collections for a repository
     */
    async function loadCollections() {
        updateBreadcrumb([
            { label: 'Home', href: 'index.html' },
            { label: 'Browse', href: 'browse.html' },
            { label: 'Loading...' }
        ]);
        browseSubtitle.textContent = 'Loading collections...';
        pagination.classList.add('hidden');

        try {
            const response = await fetch(`${API_BASE}/repositories/${currentRepo}`);
            if (!response.ok) throw new Error('Failed to fetch');

            const repo = await response.json();

            updateBreadcrumb([
                { label: 'Home', href: 'index.html' },
                { label: 'Browse', href: 'browse.html' },
                { label: repo.name || repo.short_name }
            ]);
            browseTitle.textContent = repo.name || repo.short_name;
            browseSubtitle.textContent = `${repo.collections?.length || 0} collections`;

            const collections = repo.collections || [];

            if (collections.length === 0) {
                // No collections - show all manuscripts directly
                browseSubtitle.textContent = 'No named collections - showing all manuscripts';
                currentCollection = '';
                loadManuscripts();
                return;
            }

            browseContent.innerHTML = `
                <div class="collection-grid">
                    ${collections.map(col => `
                        <a href="browse.html?repo=${currentRepo}&collection=${encodeURIComponent(col.name)}"
                           class="collection-card"
                           data-collection="${escapeHtml(col.name)}">
                            <h3 class="collection-name">${escapeHtml(col.name)}</h3>
                            <p class="collection-count">${col.count} manuscripts</p>
                        </a>
                    `).join('')}
                </div>
            `;

            // Add click handlers
            browseContent.querySelectorAll('.collection-card').forEach(card => {
                card.addEventListener('click', (e) => {
                    e.preventDefault();
                    currentCollection = card.dataset.collection;
                    currentOffset = 0;
                    updateUrl();
                    loadManuscripts();
                });
            });

        } catch (err) {
            console.error('Failed to load collections:', err);
            browseContent.innerHTML = '<div class="empty-state"><p>Unable to load collections</p></div>';
        }
    }

    /**
     * Load manuscripts for a collection
     */
    async function loadManuscripts() {
        // First get repository info for breadcrumb
        let repoName = 'Repository';
        try {
            const repoResponse = await fetch(`${API_BASE}/repositories/${currentRepo}`);
            if (repoResponse.ok) {
                const repo = await repoResponse.json();
                repoName = repo.name || repo.short_name;
            }
        } catch (err) {
            console.error('Failed to get repo name:', err);
        }

        const breadcrumbItems = [
            { label: 'Home', href: 'index.html' },
            { label: 'Browse', href: 'browse.html' },
            { label: repoName, href: `browse.html?repo=${currentRepo}` }
        ];

        if (currentCollection) {
            breadcrumbItems.push({ label: currentCollection });
            browseTitle.textContent = currentCollection;
        } else {
            browseTitle.textContent = repoName;
        }

        updateBreadcrumb(breadcrumbItems);
        browseSubtitle.textContent = 'Loading manuscripts...';

        try {
            let url = `${API_BASE}/manuscripts?repository_id=${currentRepo}&limit=${ITEMS_PER_PAGE}&offset=${currentOffset}`;
            if (currentCollection) {
                url += `&collection=${encodeURIComponent(currentCollection)}`;
            }

            const response = await fetch(url);
            if (!response.ok) throw new Error('Failed to fetch');

            const data = await response.json();
            const manuscripts = data.manuscripts || [];
            totalItems = data.total || 0;

            browseSubtitle.textContent = `${totalItems} manuscripts`;

            if (manuscripts.length === 0) {
                browseContent.innerHTML = '<div class="empty-state"><p>No manuscripts found</p></div>';
                pagination.classList.add('hidden');
                return;
            }

            browseContent.innerHTML = `
                <div class="manuscript-grid">
                    ${manuscripts.map(ms => `
                        <a href="viewer.html?ms=${ms.id}" class="ms-card">
                            ${ms.thumbnail_url
                                ? `<img src="${escapeHtml(ms.thumbnail_url)}" alt="" class="ms-thumbnail" loading="lazy" onerror="this.outerHTML='<div class=\\'ms-thumbnail-placeholder\\'>No image</div>'">`
                                : '<div class="ms-thumbnail-placeholder">No image</div>'
                            }
                            <div class="ms-info">
                                <h3 class="ms-shelfmark">${escapeHtml(ms.shelfmark || 'Unknown')}</h3>
                                ${ms.contents ? `<p class="ms-title">${escapeHtml(truncateText(ms.contents))}</p>` : ''}
                                ${ms.date_display ? `<p class="ms-date">${escapeHtml(ms.date_display)}</p>` : ''}
                            </div>
                        </a>
                    `).join('')}
                </div>
            `;

            // Update pagination
            updatePagination();

        } catch (err) {
            console.error('Failed to load manuscripts:', err);
            browseContent.innerHTML = '<div class="empty-state"><p>Unable to load manuscripts</p></div>';
            pagination.classList.add('hidden');
        }
    }

    /**
     * Update pagination controls
     */
    function updatePagination() {
        if (totalItems <= ITEMS_PER_PAGE) {
            pagination.classList.add('hidden');
            return;
        }

        pagination.classList.remove('hidden');

        const currentPage = Math.floor(currentOffset / ITEMS_PER_PAGE) + 1;
        const totalPages = Math.ceil(totalItems / ITEMS_PER_PAGE);

        // Update input and total pages display
        if (pageInput) {
            pageInput.value = currentPage;
            pageInput.max = totalPages;
        }
        if (totalPagesSpan) {
            totalPagesSpan.textContent = totalPages;
        }

        prevBtn.disabled = currentOffset === 0;
        nextBtn.disabled = currentOffset + ITEMS_PER_PAGE >= totalItems;
    }

    /**
     * Go to previous page
     */
    function goToPrevPage() {
        if (currentOffset > 0) {
            currentOffset = Math.max(0, currentOffset - ITEMS_PER_PAGE);
            updateUrl();
            loadManuscripts();
            window.scrollTo(0, 0);
        }
    }

    /**
     * Go to next page
     */
    function goToNextPage() {
        if (currentOffset + ITEMS_PER_PAGE < totalItems) {
            currentOffset += ITEMS_PER_PAGE;
            updateUrl();
            loadManuscripts();
            window.scrollTo(0, 0);
        }
    }

    /**
     * Go to specific page number
     */
    function goToPage(pageNumber) {
        const totalPages = Math.ceil(totalItems / ITEMS_PER_PAGE);

        // Clamp to valid range
        if (isNaN(pageNumber) || pageNumber < 1) {
            pageNumber = 1;
        } else if (pageNumber > totalPages) {
            pageNumber = totalPages;
        }

        const newOffset = (pageNumber - 1) * ITEMS_PER_PAGE;

        // Only reload if actually changing pages
        if (newOffset !== currentOffset) {
            currentOffset = newOffset;
            updateUrl();
            loadManuscripts();
            window.scrollTo(0, 0);
        } else {
            // Reset input to current page if no change
            if (pageInput) pageInput.value = Math.floor(currentOffset / ITEMS_PER_PAGE) + 1;
        }
    }

    /**
     * Update breadcrumb navigation
     */
    function updateBreadcrumb(items) {
        if (!breadcrumb) return;

        breadcrumb.innerHTML = items.map((item, index) => {
            const isLast = index === items.length - 1;
            if (isLast) {
                return `<span>${escapeHtml(item.label)}</span>`;
            }
            return `
                <a href="${escapeHtml(item.href)}">${escapeHtml(item.label)}</a>
                <span class="breadcrumb-separator">/</span>
            `;
        }).join('');

        // Add click handlers for SPA navigation
        breadcrumb.querySelectorAll('a').forEach(link => {
            link.addEventListener('click', (e) => {
                // Let home link navigate normally
                if (link.href.includes('index.html')) return;

                e.preventDefault();
                const href = link.getAttribute('href');

                if (href === 'browse.html') {
                    currentRepo = null;
                    currentCollection = null;
                    currentOffset = 0;
                    updateUrl();
                    loadRepositories();
                } else if (href.includes('repo=') && !href.includes('collection=')) {
                    currentCollection = null;
                    currentOffset = 0;
                    updateUrl();
                    loadCollections();
                }
            });
        });
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

    /**
     * Truncate text to a maximum length, adding ellipsis if needed
     */
    function truncateText(text, maxLength = 70) {
        if (!text) return '';
        // Clean up whitespace
        text = text.replace(/\s+/g, ' ').trim();
        if (text.length <= maxLength) return text;
        // Try to break at a word boundary
        const truncated = text.substring(0, maxLength);
        const lastSpace = truncated.lastIndexOf(' ');
        if (lastSpace > maxLength * 0.6) {
            return truncated.substring(0, lastSpace) + '…';
        }
        return truncated + '…';
    }

    // Handle browser back/forward
    window.addEventListener('popstate', () => {
        const params = new URLSearchParams(window.location.search);
        currentRepo = params.get('repo');
        currentCollection = params.get('collection');
        currentOffset = parseInt(params.get('offset') || '0', 10);

        if (currentRepo && currentCollection) {
            loadManuscripts();
        } else if (currentRepo) {
            loadCollections();
        } else {
            loadRepositories();
        }
    });

})();
