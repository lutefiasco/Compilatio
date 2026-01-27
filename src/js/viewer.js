// Universal Viewer with database integration for Compilatio
// Connects to manuscript database and displays IIIF manifests

(function() {
    'use strict';

    // Configuration
    const API_BASE = '/api';

    // Repository mapping
    const REPOSITORY_MAP = {
        'British Library': ['British Library', 'BL'],
        'Bodleian Library': ['Bodleian', 'Boolean'],
        'Cambridge University Library': ['CUL', 'Cambridge University Library'],
        'Trinity College Cambridge': ['TCC', 'Trinity College Cambridge'],
        'Huntington Library': ['HEHL', 'Huntington Library'],
        'Folger Shakespeare Library': ['Folger Library', 'Folger'],
        'Morgan Library': ['Morgan LIbrary', 'Morgan Library', 'Morgan'],
        'National Library of Scotland': ['NLS', 'National Library of Scotland'],
        'National Archives': ['TNA', 'National Archives'],
        'Kungliga biblioteket': ['Kungliga', 'Kungliga biblioteket'],
        'Society of Antiquaries': ['SocAntiq', 'Society of Antiquaries'],
        'College of Arms': ['College of Arms'],
        "Chetham's Library": ["Chetham's Library", "Chetham's"],
        'Cambridgeshire Record Office': ['Cambridgeshire Record Office'],
    };

    // State
    let manuscriptsData = null;
    let uvInstance = null;
    let currentManuscript = null;
    let allViewableManuscripts = [];  // All manuscripts with IIIF images
    let selectedRepository = '';  // Currently selected repository filter

    // Sidebar state
    let activeTab = 'info';
    let sidebarCollapsed = false;

    // DOM Elements - Selectors
    const repositorySelect = document.getElementById('repository-select');
    const manuscriptSelect = document.getElementById('manuscript-select');
    const manuscriptCount = document.getElementById('manuscript-count');
    const selectorInfo = document.getElementById('selector-info');

    // DOM Elements - Sidebar
    const sidebar = document.getElementById('manuscript-sidebar');
    const tabInfo = document.getElementById('tab-info');
    const infoPanel = document.getElementById('info-panel');
    const infoContent = document.getElementById('info-content');
    const sidebarCollapseBtn = document.getElementById('sidebar-collapse-btn');

    // DOM Elements - Viewer
    const viewerLayout = document.querySelector('.viewer-layout');
    const viewerPlaceholder = document.getElementById('viewer-placeholder');
    const uvViewer = document.getElementById('uv-viewer');

    /**
     * Initialize the viewer on page load
     */
    document.addEventListener('DOMContentLoaded', async () => {
        console.log('Compilatio viewer initializing...');

        // Initialize sidebar functionality
        initSidebar();

        // Initialize keyboard shortcuts
        initKeyboardShortcuts();

        // Load manuscript data
        await loadManuscriptData();

        // Check URL parameters for deep linking
        const urlParams = new URLSearchParams(window.location.search);
        const manifestParam = urlParams.get('manifest');
        const msParam = urlParams.get('ms');

        // Handle deep linking
        if (msParam) {
            // Manuscript ID provided - load by ID
            loadManuscriptById(msParam);
        } else if (manifestParam) {
            // Direct manifest URL provided (legacy support)
            initUniversalViewer(manifestParam);
        }
        // If no deep link, wait for user to select a manuscript
    });

    // ========================================
    // SIDEBAR FUNCTIONALITY
    // ========================================

    /**
     * Initialize sidebar tabs and collapse
     */
    function initSidebar() {
        // Restore sidebar collapse state from localStorage
        const savedCollapsed = localStorage.getItem('compilatio-sidebar-collapsed');
        if (savedCollapsed === 'true') {
            sidebarCollapsed = true;
            applySidebarCollapseState();
        }

        // Tab switching (currently only info tab)
        if (tabInfo) {
            tabInfo.addEventListener('click', () => switchSidebarTab('info'));
        }

        // Sidebar collapse
        if (sidebarCollapseBtn) {
            sidebarCollapseBtn.addEventListener('click', toggleSidebar);
        }
    }

    /**
     * Switch sidebar tabs
     */
    function switchSidebarTab(tabName) {
        activeTab = tabName;

        // Update tab buttons
        if (tabInfo) {
            tabInfo.classList.toggle('active', tabName === 'info');
            tabInfo.setAttribute('aria-selected', tabName === 'info');
        }

        // Update panels
        if (infoPanel) {
            infoPanel.classList.toggle('hidden', tabName !== 'info');
            infoPanel.hidden = tabName !== 'info';
        }
    }

    /**
     * Toggle sidebar collapse state
     */
    function toggleSidebar() {
        sidebarCollapsed = !sidebarCollapsed;
        localStorage.setItem('compilatio-sidebar-collapsed', sidebarCollapsed);
        applySidebarCollapseState();
    }

    /**
     * Apply current sidebar collapse state to DOM
     */
    function applySidebarCollapseState() {
        if (sidebar) {
            sidebar.classList.toggle('collapsed', sidebarCollapsed);
        }
        if (viewerLayout) {
            viewerLayout.classList.toggle('sidebar-collapsed', sidebarCollapsed);
        }
        if (sidebarCollapseBtn) {
            sidebarCollapseBtn.textContent = sidebarCollapsed ? '»' : '«';
            sidebarCollapseBtn.setAttribute('aria-expanded', !sidebarCollapsed);
            sidebarCollapseBtn.setAttribute('aria-label', sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar');
        }
    }

    // ========================================
    // INFO PANEL
    // ========================================

    /**
     * Render the info panel with tiered metadata
     */
    function renderInfoPanel(ms) {
        if (!infoContent) return;

        if (!ms) {
            infoContent.innerHTML = '<p class="panel-placeholder">Select a manuscript to view details.</p>';
            return;
        }

        // Primary info (always visible)
        let html = `
            <div class="info-primary">
                <h3 class="info-shelfmark">${escapeHtml(ms.shelfmark || '')}</h3>
                <p class="info-repo">${escapeHtml(ms.repository || '')}</p>
                <p class="info-date">${escapeHtml(ms.date_display || '')}</p>
            </div>
        `;

        // Physical description (collapsible)
        const hasPhysical = ms.language || ms.folios;
        if (hasPhysical) {
            html += `
                <details class="info-section" open>
                    <summary>Physical Description</summary>
                    <dl class="info-list">
                        ${ms.language ? `<dt>Language</dt><dd>${escapeHtml(ms.language)}</dd>` : ''}
                        ${ms.folios ? `<dt>Folios</dt><dd>${escapeHtml(ms.folios)}</dd>` : ''}
                    </dl>
                </details>
            `;
        }

        // Contents (collapsible)
        if (ms.contents) {
            html += `
                <details class="info-section">
                    <summary>Contents</summary>
                    <p class="info-text">${escapeHtml(ms.contents)}</p>
                </details>
            `;
        }

        // Provenance (collapsible)
        if (ms.provenance) {
            html += `
                <details class="info-section">
                    <summary>Provenance</summary>
                    <p class="info-text">${escapeHtml(ms.provenance)}</p>
                </details>
            `;
        }

        // Source link
        if (ms.source_url) {
            html += `
                <div class="info-actions">
                    <a href="${escapeHtml(ms.source_url)}"
                       class="info-link" target="_blank">
                        View at Source
                    </a>
                </div>
            `;
        }

        infoContent.innerHTML = html;
    }

    // ========================================
    // KEYBOARD SHORTCUTS
    // ========================================

    /**
     * Initialize keyboard shortcuts
     */
    function initKeyboardShortcuts() {
        document.addEventListener('keydown', (e) => {
            // Don't trigger shortcuts when typing in inputs
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT' || e.target.tagName === 'TEXTAREA') {
                return;
            }

            switch (e.key) {
                case 'i':
                    e.preventDefault();
                    switchSidebarTab('info');
                    break;
                case '[':
                    e.preventDefault();
                    toggleSidebar();
                    break;
            }
        });
    }

    /**
     * Load manuscript data from API
     */
    async function loadManuscriptData() {
        // Check if running via file:// protocol
        if (window.location.protocol === 'file:') {
            console.warn('Running via file:// protocol - fetch may not work. Use a local web server.');
            showDataLoadError('This page must be served via a web server. Try: python server.py');
            return;
        }

        // Try to load from API
        try {
            const response = await fetch(`${API_BASE}/manuscripts`);
            if (response.ok) {
                const data = await response.json();
                allViewableManuscripts = data.manuscripts || data;
                manuscriptsData = {
                    manuscripts: allViewableManuscripts,
                    iiif_catalog: allViewableManuscripts.filter(m => m.iiif_manifest_url).map(m => ({
                        manifestId: m.iiif_manifest_url,
                        label: m.shelfmark,
                        id: m.id
                    }))
                };
                console.log(`Loaded ${allViewableManuscripts.length} manuscripts`);
                populateSelector();
                return;
            }
        } catch (e) {
            console.log('API fetch failed:', e.message);
        }

        showDataLoadError('Could not load manuscript data. Ensure the server is running.');
    }

    /**
     * Show an error message in the selector area
     */
    function showDataLoadError(message) {
        if (selectorInfo) {
            selectorInfo.innerHTML = `<p class="no-iiif-warning">${message}</p>`;
        }
        if (manuscriptCount) {
            manuscriptCount.textContent = '';
        }
    }

    /**
     * Populate the repository dropdown with repositories that have viewable manuscripts
     */
    function populateRepositoryDropdown() {
        if (!repositorySelect || !allViewableManuscripts.length) return;

        // Find which repositories have manuscripts in our data
        const reposWithManuscripts = new Set();
        allViewableManuscripts.forEach(ms => {
            if (ms.repository) {
                // Find which REPOSITORY_MAP key this repository belongs to
                for (const [displayName, dbValues] of Object.entries(REPOSITORY_MAP)) {
                    if (dbValues.includes(ms.repository)) {
                        reposWithManuscripts.add(displayName);
                        break;
                    }
                }
                // Also add unmapped repositories directly
                if (!Object.values(REPOSITORY_MAP).flat().includes(ms.repository)) {
                    reposWithManuscripts.add(ms.repository);
                }
            }
        });

        // Clear and repopulate
        repositorySelect.innerHTML = '<option value="">All repositories</option>';

        // Sort and add options
        Array.from(reposWithManuscripts).sort().forEach(repo => {
            const option = document.createElement('option');
            option.value = repo;
            option.textContent = repo;
            repositorySelect.appendChild(option);
        });

        // Add change listener
        repositorySelect.addEventListener('change', handleRepositoryChange);
    }

    /**
     * Handle repository selection change
     */
    function handleRepositoryChange(event) {
        selectedRepository = event.target.value;
        populateManuscriptDropdown();
    }

    /**
     * Filter manuscripts by selected repository
     */
    function filterManuscriptsByRepository() {
        if (!selectedRepository) {
            return allViewableManuscripts;
        }

        // Get database values for selected repository
        const dbValues = REPOSITORY_MAP[selectedRepository] || [selectedRepository];

        return allViewableManuscripts.filter(ms => dbValues.includes(ms.repository));
    }

    /**
     * Populate the manuscript selector dropdown
     */
    function populateSelector() {
        if (!manuscriptSelect) return;

        // Populate repository dropdown first
        populateRepositoryDropdown();

        // Populate manuscript dropdown
        populateManuscriptDropdown();

        // Add change listener for manuscript selection
        manuscriptSelect.addEventListener('change', handleManuscriptSelection);

        // Update selector info
        if (selectorInfo) {
            if (allViewableManuscripts.length > 0) {
                selectorInfo.innerHTML = `<p>Select a repository to filter, then choose a manuscript.</p>`;
            } else {
                selectorInfo.innerHTML = '<p class="no-iiif-warning">No manuscripts are currently available.</p>';
            }
        }
    }

    /**
     * Populate the manuscript dropdown with filtered manuscripts
     */
    function populateManuscriptDropdown() {
        if (!manuscriptSelect) return;

        // Get filtered manuscripts
        const filteredManuscripts = filterManuscriptsByRepository();

        // Update count
        if (manuscriptCount) {
            if (selectedRepository) {
                manuscriptCount.textContent = `(${filteredManuscripts.length} of ${allViewableManuscripts.length})`;
            } else {
                manuscriptCount.textContent = `(${filteredManuscripts.length} viewable)`;
            }
        }

        // Clear existing options
        manuscriptSelect.innerHTML = '<option value="">-- Choose a manuscript --</option>';

        // Sort by shelfmark
        const sorted = [...filteredManuscripts].sort((a, b) => {
            const labelA = a.shelfmark || '';
            const labelB = b.shelfmark || '';
            return labelA.localeCompare(labelB);
        });

        // Add options for each manuscript
        sorted.forEach(ms => {
            const option = document.createElement('option');
            option.value = ms.id;
            option.dataset.id = ms.id;
            option.dataset.manifestUrl = ms.iiif_manifest_url || '';

            const label = ms.shelfmark || `MS ${ms.id}`;
            const date = ms.date_display ? ` (${ms.date_display})` : '';
            option.textContent = `${label}${date}`;

            manuscriptSelect.appendChild(option);
        });
    }

    /**
     * Handle manuscript selection from dropdown
     */
    function handleManuscriptSelection(event) {
        const selectedOption = event.target.selectedOptions[0];
        const manuscriptId = selectedOption?.value;
        const manifestUrl = selectedOption?.dataset?.manifestUrl;

        if (!manuscriptId || manuscriptId === '') {
            clearSidebarPanels();
            return;
        }

        // Find full manuscript data
        const ms = allViewableManuscripts.find(m => m.id == manuscriptId);
        if (!ms) {
            console.error('Manuscript not found:', manuscriptId);
            return;
        }

        currentManuscript = ms;

        // Render info panel
        renderInfoPanel(ms);

        // Load IIIF viewer
        if (manifestUrl) {
            loadManifest(manifestUrl);
            updateUrl(manifestUrl, manuscriptId);
        } else {
            // No IIIF - show placeholder
            if (viewerPlaceholder) {
                viewerPlaceholder.innerHTML = '<p>This manuscript does not have IIIF images available.</p>';
                viewerPlaceholder.classList.remove('hidden');
            }
            if (uvViewer) uvViewer.classList.add('hidden');
            updateUrl(null, manuscriptId);
        }
    }

    /**
     * Clear sidebar panels when no manuscript is selected
     */
    function clearSidebarPanels() {
        renderInfoPanel(null);
    }

    /**
     * Initialize Universal Viewer
     */
    function initUniversalViewer(manifestUrl) {
        console.log('Initializing Universal Viewer...');

        // Hide placeholder
        const placeholder = document.getElementById('viewer-placeholder');
        if (placeholder) {
            placeholder.classList.add('hidden');
        }

        // Show viewer container
        if (uvViewer) {
            uvViewer.classList.remove('hidden');
        }

        // Initialize UV with manifest
        const data = {
            manifest: manifestUrl,
            embedded: true
        };

        uvInstance = UV.init('uv-viewer', data);

        // Configure UV options
        uvInstance.on('configure', function({ config, cb }) {
            cb({
                options: {
                    footerPanelEnabled: true,
                    headerPanelEnabled: true,
                    leftPanelEnabled: true,
                    rightPanelEnabled: false
                }
            });
        });

        // Handle viewer creation
        uvInstance.on('created', function() {
            console.log('Universal Viewer created');
        });

        // Handle errors
        uvInstance.on('error', function(message) {
            console.error('UV error:', message);
        });

        console.log('Universal Viewer initialized');
    }

    /**
     * Load a manifest into Universal Viewer
     */
    function loadManifest(manifestUrl) {
        console.log(`Loading manifest: ${manifestUrl}`);

        // Initialize UV on first use, or update existing instance
        if (!uvInstance) {
            initUniversalViewer(manifestUrl);
        } else {
            // UV is already initialized - load new manifest
            uvInstance.set({ manifest: manifestUrl });
        }

        // Show viewer, hide placeholder
        if (viewerPlaceholder) {
            viewerPlaceholder.classList.add('hidden');
        }
        if (uvViewer) {
            uvViewer.classList.remove('hidden');
        }
    }

    /**
     * Load manifest by URL parameter (legacy deep linking support)
     */
    function loadManifestByUrl(manifestUrl) {
        // Find manuscript with this manifest URL
        const ms = allViewableManuscripts.find(m => m.iiif_manifest_url === manifestUrl);
        if (ms) {
            loadManuscriptById(ms.id);
            return;
        }

        // Not in our data - load manifest directly (external manifest)
        initUniversalViewer(manifestUrl);
    }

    /**
     * Load a manuscript by its ID (for deep linking)
     */
    function loadManuscriptById(manuscriptId) {
        if (!allViewableManuscripts.length) return;

        const ms = allViewableManuscripts.find(m => m.id == manuscriptId);
        if (!ms) {
            console.log('Manuscript not found:', manuscriptId);
            return;
        }

        // Select in dropdown
        if (manuscriptSelect) {
            for (let option of manuscriptSelect.options) {
                if (option.value == manuscriptId) {
                    option.selected = true;
                    break;
                }
            }
        }

        currentManuscript = ms;

        // Render info panel
        renderInfoPanel(ms);

        // Load IIIF viewer
        if (ms.iiif_manifest_url) {
            loadManifest(ms.iiif_manifest_url);
        } else {
            // No IIIF - show placeholder
            if (viewerPlaceholder) {
                viewerPlaceholder.innerHTML = '<p>This manuscript does not have IIIF images available.</p>';
                viewerPlaceholder.classList.remove('hidden');
            }
            if (uvViewer) uvViewer.classList.add('hidden');
        }
    }

    /**
     * Update URL for deep linking
     */
    function updateUrl(manifestUrl, manuscriptId = null) {
        const url = new URL(window.location);

        // Clear existing params
        url.searchParams.delete('manifest');
        url.searchParams.delete('ms');

        if (manifestUrl) {
            url.searchParams.set('manifest', manifestUrl);
        }
        if (manuscriptId) {
            url.searchParams.set('ms', manuscriptId);
        }

        window.history.replaceState({}, '', url);
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

    // Export for external use
    window.addManifest = function(manifestUrl) {
        loadManifest(manifestUrl);
    };

    window.getManuscriptsData = function() {
        return manuscriptsData;
    };

})();
