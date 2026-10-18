/**
 * API Wrapper
 * Centralized API calls with error handling
 */

const API = {
    /**
     * Base fetch wrapper with CSRF token
     */
    async request(url, options = {}) {
        const defaults = {
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken')
            }
        };

        const config = {
            ...defaults,
            ...options,
            headers: {
                ...defaults.headers,
                ...options.headers
            }
        };

        try {
            const response = await fetch(url, config);
            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.error || `HTTP ${response.status}`);
            }

            return { success: true, data };
        } catch (error) {
            console.error('API Error:', error);
            return { success: false, error: error.message };
        }
    },

    /**
     * GET request
     */
    async get(url) {
        return this.request(url, { method: 'GET' });
    },

    /**
     * POST request
     */
    async post(url, data) {
        return this.request(url, {
            method: 'POST',
            body: JSON.stringify(data)
        });
    },

    /**
     * Scraper API
     */
    scraper: {
        start(data) {
            return API.post('/api/scrape/start/', data);
        },

        stop(jobId) {
            return API.post(`/api/scrape/stop/${jobId}/`);
        },

        status(jobId) {
            return API.get(`/api/scrape/status/${jobId}/`);
        },

        jobs() {
            return API.get('/api/scrape/jobs/');
        }
    },

    /**
     * Preset API
     */
    presets: {
        get(presetId) {
            return API.get(`/api/preset/${presetId}/`);
        },

        save(data) {
            return API.post('/api/preset/save/', data);
        }
    },

    /**
     * Database API
     */
    database: {
        wipePostgres() {
            return API.post('/api/database/wipe-postgresql/');
        },

        wipeSqlite() {
            return API.post('/api/database/wipe-sqlite/');
        }
    },

    /**
     * Browse API
     */
    browse: {
        searchHorse(query) {
            return API.get(`/api/browse/search-horse/?q=${encodeURIComponent(query)}`);
        },

        searchRaces(date) {
            return API.get(`/api/browse/search-races/?date=${date}`);
        },

        raceDetail(raceId) {
            return API.get(`/api/browse/race/${raceId}/`);
        }
    },

    /**
     * Reports API
     */
    reports: {
        winningPositions(filters) {
            return API.post('/api/reports/winning-positions/', filters);
        },

        exportCSV(reportData) {
            return API.post('/api/reports/export-csv/', { report_data: reportData });
        }
    }
};