/**
 * Reports Page Logic
 */

let currentReportData = null;

function initReportsPage() {
    setupDateDefaults();
    setupGenerateButton();
    setupExportButton();
}

function setupDateDefaults() {
    const dateFrom = document.getElementById('date-from');
    const dateTo = document.getElementById('date-to');

    if (dateFrom) dateFrom.value = getYesterday();
    if (dateTo) dateTo.value = getToday();
}

function setupGenerateButton() {
    const generateBtn = document.getElementById('generate-btn');

    if (generateBtn) {
        generateBtn.addEventListener('click', generateReport);
    }
}

async function generateReport() {
    const dateFrom = document.getElementById('date-from').value;
    const dateTo = document.getElementById('date-to').value;
    const courseName = document.getElementById('course-select').value;
    const minDistance = document.getElementById('min-distance').value;
    const maxDistance = document.getElementById('max-distance').value;

    // ============================================
    // VALIDATION: Check dates are provided
    // ============================================
    if (!dateFrom || !dateTo) {
        showAlert('Proszę wybrać zakres dat', 'warning');
        return;
    }

    // ============================================
    // VALIDATION: Check date order
    // ============================================
    const fromDate = new Date(dateFrom);
    const toDate = new Date(dateTo);

    if (fromDate > toDate) {
        showAlert(
            '⚠️ Nieprawidłowy zakres dat! Data początkowa (' + dateFrom + ') ' +
            'jest późniejsza niż data końcowa (' + dateTo + '). ' +
            'Ustaw daty w prawidłowej kolejności: od wcześniejszej do późniejszej.',
            'danger'
        );

        // Optional: Highlight the date inputs
        document.getElementById('date-from').style.borderColor = '#dc3545';
        document.getElementById('date-to').style.borderColor = '#dc3545';

        // Reset border color after 3 seconds
        setTimeout(() => {
            document.getElementById('date-from').style.borderColor = '';
            document.getElementById('date-to').style.borderColor = '';
        }, 3000);

        return;
    }

    // ============================================
    // VALIDATION: Check distance order
    // ============================================
    if (minDistance && maxDistance) {
        const min = parseInt(minDistance);
        const max = parseInt(maxDistance);

        if (min > max) {
            showAlert(
                '⚠️ Nieprawidłowy zakres dystansu! Minimalny dystans (' + min + 'y) ' +
                'jest większy niż maksymalny (' + max + 'y). ' +
                'Minimum powinno być mniejsze niż maximum.',
                'danger'
            );
            return;
        }
    }

    // ============================================
    // VALIDATION: Check date range isn't too large
    // ============================================
    const daysDifference = Math.floor((toDate - fromDate) / (1000 * 60 * 60 * 24));

    if (daysDifference > 1095) {  // 3 years
        const confirmed = confirm(
            'Wybrany zakres dat to ' + daysDifference + ' dni (ponad 3 lata). ' +
            'Generowanie raportu może potrwać dłużej. Kontynuować?'
        );

        if (!confirmed) return;
    }

    // Rest of the function continues as before...
    const generateBtn = document.getElementById('generate-btn');
    generateBtn.disabled = true;
    generateBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Generowanie...';

    const filters = { date_from: dateFrom, date_to: dateTo };
    if (courseName) filters.course_name = courseName;
    if (minDistance) filters.min_distance = minDistance;
    if (maxDistance) filters.max_distance = maxDistance;

    const result = await API.reports.winningPositions(filters);

    generateBtn.disabled = false;
    generateBtn.innerHTML = '<i class="fas fa-chart-bar"></i> Generuj Raport';

    if (result.success) {
        currentReportData = result.data.report;
        displayReport(result.data.report);
        showAlert('✓ Raport wygenerowany pomyślnie', 'success');
    } else {
        showAlert('✗ Błąd: ' + result.error, 'danger');
    }
}

function displayReport(report) {
    const resultsSection = document.getElementById('results-section');
    const headerDiv = document.getElementById('report-header');
    const tableContainer = document.getElementById('report-table-container');

    // Build header
    let headerHtml = `
    <h3 class="mb-md"><i class="fas fa-trophy"></i> Raport: Wygrywające Pozycje Startowe</h3>
    <div class="report-info-grid">
    <div class="report-info-item">
    <div class="report-info-label">Okres</div>
    <div class="report-info-value">${report.filters.date_from} - ${report.filters.date_to}</div>
    </div>
    <div class="report-info-item">
    <div class="report-info-label">Tor</div>
    <div class="report-info-value">${report.filters.course_name || 'Wszystkie'}</div>
    </div>
    `;

    if (report.filters.min_distance || report.filters.max_distance) {
        const minD = report.filters.min_distance || '-';
        const maxD = report.filters.max_distance || '-';
        headerHtml += `
        <div class="report-info-item">
        <div class="report-info-label">Dystans</div>
        <div class="report-info-value">${minD} - ${maxD} jardów</div>
        </div>
        `;
    }

    headerHtml += `
    <div class="report-info-item">
    <div class="report-info-label">Liczba wyścigów</div>
    <div class="report-info-value">${formatNumber(report.total_races)}</div>
    </div>
    </div>
    `;

    headerDiv.innerHTML = headerHtml;

    // Build table
    let tableHtml = `
    <div class="table-wrapper">
    <table class="table table-striped">
    <thead>
    <tr>
    <th>Numer Startowy</th>
    <th>1. miejsce</th>
    <th>2. miejsce</th>
    <th>3. miejsce</th>
    <th>4. miejsce</th>
    <th>Suma Top 4</th>
    </tr>
    </thead>
    <tbody>
    `;

    report.results.forEach((row, index) => {
        const rowClass = index < 3 ? 'top-performer' : '';
        tableHtml += `
        <tr class="${rowClass}">
        <td><strong style="color: var(--color-accent); font-size: 18px;">${row.cloth_number}</strong></td>
        <td><strong>${formatNumber(row.first)}</strong></td>
        <td><strong>${formatNumber(row.second)}</strong></td>
        <td><strong>${formatNumber(row.third)}</strong></td>
        <td><strong>${formatNumber(row.fourth)}</strong></td>
        <td style="background: #e7f3ff; font-weight: bold; color: var(--color-accent);">${formatNumber(row.total_top_4)}</td>
        </tr>
        `;
    });

    tableHtml += `
    </tbody>
    </table>
    </div>
    `;

    tableContainer.innerHTML = tableHtml;
    show(resultsSection);

    // Scroll to results
    resultsSection.scrollIntoView({ behavior: 'smooth' });
}

function setupExportButton() {
    const exportBtn = document.getElementById('export-csv-btn');

    if (exportBtn) {
        exportBtn.addEventListener('click', exportToCSV);
    }
}

async function exportToCSV() {
    if (!currentReportData) {
        showAlert('Brak danych do eksportu', 'warning');
        return;
    }

    const exportBtn = document.getElementById('export-csv-btn');
    exportBtn.disabled = true;
    exportBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Eksportowanie...';

    try {
        const response = await fetch('/api/reports/export-csv/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken')
            },
            body: JSON.stringify({ report_data: currentReportData })
        });

        if (!response.ok) {
            throw new Error('Nie udało się wyeksportować raportu');
        }

        // Download file
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `raport_pozycje_startowe_${formatDate(new Date())}.csv`;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);

        showAlert('✓ Raport wyeksportowany', 'success');
    } catch (error) {
        showAlert('✗ Błąd eksportu: ' + error.message, 'danger');
    } finally {
        exportBtn.disabled = false;
        exportBtn.innerHTML = '<i class="fas fa-download"></i> Eksportuj do CSV';
    }
}

// Initialize
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initReportsPage);
} else {
    initReportsPage();
}