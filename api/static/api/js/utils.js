/**
 * Utility Functions
 * Shared helper functions used across all pages
 */

/**
 * Get CSRF token from cookies
 */
function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

/**
 * Format number with Polish thousand separators
 * @param {number} num - Number to format
 * @returns {string} Formatted number
 */
function formatNumber(num) {
    if (num === null || num === undefined) return '-';
    return num.toLocaleString('pl-PL');
}

/**
 * Show/hide element
 */
function show(element) {
    if (typeof element === 'string') {
        element = document.querySelector(element);
    }
    if (element) element.classList.remove('hidden');
}

function hide(element) {
    if (typeof element === 'string') {
        element = document.querySelector(element);
    }
    if (element) element.classList.add('hidden');
}

/**
 * Show alert message
 */
function showAlert(message, type = 'info') {
    const alertDiv = document.createElement('div');
    alertDiv.className = `alert alert-${type}`;

    const icon = {
        'info': 'fa-circle-info',
        'success': 'fa-circle-check',
        'warning': 'fa-triangle-exclamation',
        'danger': 'fa-circle-xmark'
    }[type] || 'fa-circle-info';

    alertDiv.innerHTML = `<i class="fas ${icon}"></i> ${message}`;

    // Insert at top of container
    const container = document.querySelector('.container');
    if (container) {
        container.insertBefore(alertDiv, container.firstChild);

        // Auto-remove after 5 seconds
        setTimeout(() => alertDiv.remove(), 5000);
    }
}

/**
 * Debounce function (delay execution)
 */
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

/**
 * Format date to YYYY-MM-DD
 */
function formatDate(date) {
    if (!date) return '';
    const d = new Date(date);
    const year = d.getFullYear();
    const month = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
}

/**
 * Get yesterday's date as YYYY-MM-DD
 */
function getYesterday() {
    const date = new Date();
    date.setDate(date.getDate() - 1);
    return formatDate(date);
}

/**
 * Get today's date as YYYY-MM-DD
 */
function getToday() {
    return formatDate(new Date());
}

/**
 * Initialize tooltips (simple implementation)
 */
function initTooltips() {
    document.querySelectorAll('[data-tooltip]').forEach(element => {
        const wrapper = document.createElement('div');
        wrapper.className = 'tooltip-wrapper';
        element.parentNode.insertBefore(wrapper, element);
        wrapper.appendChild(element);

        const tooltip = document.createElement('div');
        tooltip.className = 'tooltip-text';
        tooltip.textContent = element.getAttribute('data-tooltip');
        wrapper.appendChild(tooltip);
    });
}

/**
 * Initialize when DOM is ready
 */
document.addEventListener('DOMContentLoaded', () => {
    initTooltips();

    // Set active nav link based on current page
    const currentPath = window.location.pathname;
    document.querySelectorAll('.nav-link').forEach(link => {
        if (link.getAttribute('href') === currentPath) {
            link.classList.add('active');
        }
    });
});