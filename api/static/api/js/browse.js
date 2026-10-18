/**
 * Browse Data Page Logic
 */

function initBrowsePage() {
    setupHorseSearch();
    setupRaceSearch();
    setupModal();

    // Set today's date as default
    const dateInput = document.getElementById('race-date-input');
    if (dateInput) {
        dateInput.value = getToday();
    }
}

/**
 * Horse search
 */
function setupHorseSearch() {
    const searchBtn = document.getElementById('horse-search-btn');
    const searchInput = document.getElementById('horse-search-input');

    if (searchBtn) {
        searchBtn.addEventListener('click', searchHorse);
    }

    if (searchInput) {
        searchInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') searchHorse();
        });
    }
}

async function searchHorse() {
    const query = document.getElementById('horse-search-input').value.trim();
    const resultsDiv = document.getElementById('horse-results');

    if (query.length < 2) {
        resultsDiv.innerHTML = '<p class="text-muted">Wpisz co najmniej 2 znaki</p>';
        return;
    }

    resultsDiv.innerHTML = '<div class="spinner"></div><p>Wyszukiwanie...</p>';

    const result = await API.browse.searchHorse(query);

    if (result.success) {
        displayHorseResults(result.data, resultsDiv);
    } else {
        resultsDiv.innerHTML = `<div class="alert alert-danger"><i class="fas fa-exclamation-circle"></i> ${result.error}</div>`;
    }
}

function displayHorseResults(data, container) {
    if (data.horses.length === 0) {
        container.innerHTML = '<p class="text-muted">Nie znaleziono koni</p>';
        return;
    }

    let html = `<p class="text-muted mb-md">Znaleziono: ${data.count} koni</p>`;

    data.horses.forEach(horse => {
        html += `
        <div class="horse-card">
        <div class="horse-header">
        <div class="horse-name"><i class="fas fa-horse"></i> ${horse.name}</div>
        <div class="stats-grid">
        <div class="stat-card">
        <div class="stat-label">Data urodzenia</div>
        <div class="stat-value" style="font-size: 16px;">${horse.dob || 'Brak'}</div>
        </div>
        <div class="stat-card">
        <div class="stat-label">Wiek</div>
        <div class="stat-value">${horse.age || '-'}</div>
        </div>
        <div class="stat-card">
        <div class="stat-label">Płeć</div>
        <div class="stat-value" style="font-size: 20px;">${horse.sex || '-'}</div>
        </div>
        <div class="stat-card">
        <div class="stat-label">Trener</div>
        <div class="stat-value" style="font-size: 14px;">${horse.trainer || '-'}</div>
        </div>
        <div class="stat-card highlight">
        <div class="stat-label">Zwycięstwa</div>
        <div class="stat-value">${horse.total_wins}</div>
        </div>
        <div class="stat-card highlight">
        <div class="stat-label">Starty</div>
        <div class="stat-value">${horse.total_runs}</div>
        </div>
        <div class="stat-card highlight">
        <div class="stat-label">Miejsca</div>
        <div class="stat-value">${horse.total_places}</div>
        </div>
        </div>
        </div>

        <h4 class="mt-lg mb-md"><i class="fas fa-history"></i> Historia Wyścigów (${horse.race_history.length})</h4>
        <div class="table-wrapper">
        <table class="table">
        <thead>
        <tr>
        <th>Data</th>
        <th>Czas</th>
        <th>Tor</th>
        <th>Dystans</th>
        <th>Klasa</th>
        <th>Nr</th>
        <th>Pozycja</th>
        <th>Czas</th>
        <th>Dżokej</th>
        </tr>
        </thead>
        <tbody>
        `;

        horse.race_history.forEach(race => {
            const badgeClass =
            race.final_position === '1' ? 'badge-position-1' :
            race.final_position === '2' ? 'badge-position-2' :
            race.final_position === '3' ? 'badge-position-3' : 'badge-secondary';

            html += `
            <tr>
            <td>${race.race_date || '-'}</td>
            <td>${race.race_time || '-'}</td>
            <td>${race.course_name || '-'}</td>
            <td>${race.distance_text || race.distance_value + 'y' || '-'}</td>
            <td>Klasa ${race.race_class || '-'}</td>
            <td><strong>${race.cloth_number || '-'}</strong></td>
            <td><span class="badge ${badgeClass}">${race.final_position || '-'}</span></td>
            <td>${race.finish_time || '-'}</td>
            <td>${race.jockey_name || '-'}</td>
            </tr>
            `;
        });

        html += `
        </tbody>
        </table>
        </div>
        </div>
        `;
    });

    container.innerHTML = html;
}

/**
 * Race search
 */
function setupRaceSearch() {
    const searchBtn = document.getElementById('race-search-btn');

    if (searchBtn) {
        searchBtn.addEventListener('click', searchRaces);
    }
}

async function searchRaces() {
    const dateInput = document.getElementById('race-date-input').value;
    const resultsDiv = document.getElementById('race-results');

    if (!dateInput) {
        resultsDiv.innerHTML = '<p class="text-muted">Wybierz datę</p>';
        return;
    }

    resultsDiv.innerHTML = '<div class="spinner"></div><p>Wyszukiwanie...</p>';

    const result = await API.browse.searchRaces(dateInput);

    if (result.success) {
        displayRaceResults(result.data, resultsDiv);
    } else {
        resultsDiv.innerHTML = `<div class="alert alert-danger"><i class="fas fa-exclamation-circle"></i> ${result.error}</div>`;
    }
}

function displayRaceResults(data, container) {
    if (data.races.length === 0) {
        container.innerHTML = '<p class="text-muted">Nie znaleziono wyścigów w tym dniu</p>';
        return;
    }

    let html = `<p class="text-muted mb-md">Znaleziono: ${data.count} wyścigów (${data.date})</p>`;

    data.races.forEach(race => {
        html += `
        <div class="race-item" onclick="showRaceDetail(${race.race_id})">
        <div class="race-title">
        <i class="fas fa-flag-checkered"></i> ${race.course_name} - ${race.race_time}
        </div>
        <div class="race-details">
        <span><i class="fas fa-ruler"></i> ${race.distance_text || race.distance_value + 'y'}</span>
        <span><i class="fas fa-trophy"></i> Klasa ${race.race_class || '-'}</span>
        <span><i class="fas fa-users"></i> ${race.horse_count} koni</span>
        <span><i class="fas fa-calendar"></i> ${race.race_date}</span>
        </div>
        </div>
        `;
    });

    container.innerHTML = html;
}

/**
 * Race detail modal
 */
function setupModal() {
    const modal = document.getElementById('race-detail-modal');
    const closeBtn = modal?.querySelector('.modal-close');

    if (closeBtn) {
        closeBtn.addEventListener('click', () => {
            modal.classList.remove('active');
        });
    }

    if (modal) {
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                modal.classList.remove('active');
            }
        });
    }
}

async function showRaceDetail(raceId) {
    const modal = document.getElementById('race-detail-modal');
    const content = document.getElementById('race-detail-content');

    modal.classList.add('active');
    content.innerHTML = '<div class="spinner"></div><p>Ładowanie...</p>';

    const result = await API.browse.raceDetail(raceId);

    if (result.success) {
        displayRaceDetail(result.data, content);
    } else {
        content.innerHTML = `<div class="alert alert-danger"><i class="fas fa-exclamation-circle"></i> ${result.error}</div>`;
    }
}

function displayRaceDetail(data, container) {
    const race = data.race;

    let html = `
    <h2><i class="fas fa-flag-checkered"></i> ${race.course_name} - ${race.race_date} ${race.race_time}</h2>
    <div class="stats-grid mt-lg mb-lg">
    <div class="stat-card">
    <div class="stat-label">Dystans</div>
    <div class="stat-value" style="font-size: 20px;">${race.distance_text || race.distance_value + 'y'}</div>
    </div>
    <div class="stat-card">
    <div class="stat-label">Klasa</div>
    <div class="stat-value">${race.race_class || '-'}</div>
    </div>
    <div class="stat-card">
    <div class="stat-label">Limit wieku</div>
    <div class="stat-value" style="font-size: 20px;">${race.age_limit || '-'}</div>
    </div>
    <div class="stat-card highlight">
    <div class="stat-label">Liczba koni</div>
    <div class="stat-value">${data.total_horses}</div>
    </div>
    </div>

    <h3 class="mb-md"><i class="fas fa-medal"></i> Pierwsze 3 miejsca:</h3>
    <div class="grid mb-xl">
    `;

    // Top 3
    const medals = ['🥇', '🥈', '🥉'];
    data.horses.slice(0, 3).forEach((horse, idx) => {
        html += `
        <div class="card">
        <div class="card-body">
        <div style="font-size: 24px; margin-bottom: 10px;">
        ${medals[idx]} <strong>${horse.horse_name}</strong>
        </div>
        <div style="display: flex; gap: 15px; flex-wrap: wrap; font-size: 14px; color: #666;">
        <span><i class="fas fa-hashtag"></i> Numer: ${horse.cloth_number}</span>
        <span><i class="fas fa-stopwatch"></i> Czas: ${horse.finish_time || '-'}</span>
        <span><i class="fas fa-user"></i> Dżokej: ${horse.jockey_name || '-'}</span>
        </div>
        </div>
        </div>
        `;
    });

    html += `
    </div>
    <h3 class="mb-md"><i class="fas fa-list"></i> Wszystkie konie (${data.total_horses}):</h3>
    <div class="table-wrapper">
    <table class="table">
    <thead>
    <tr>
    <th>Pozycja</th>
    <th>Koń</th>
    <th>Numer</th>
    <th>Czas</th>
    <th>Dżokej</th>
    <th>Trener</th>
    <th>Boks</th>
    </tr>
    </thead>
    <tbody>
    `;

    data.horses.forEach(horse => {
        const badgeClass =
        horse.final_position === '1' ? 'badge-position-1' :
        horse.final_position === '2' ? 'badge-position-2' :
        horse.final_position === '3' ? 'badge-position-3' : 'badge-secondary';

        html += `
        <tr>
        <td><span class="badge ${badgeClass}">${horse.final_position || '-'}</span></td>
        <td><strong>${horse.horse_name}</strong></td>
        <td>${horse.cloth_number || '-'}</td>
        <td>${horse.finish_time || '-'}</td>
        <td>${horse.jockey_name || '-'}</td>
        <td>${horse.trainer_name || '-'}</td>
        <td>${horse.drawn_stall || '-'}</td>
        </tr>
        `;
    });

    html += `
    </tbody>
    </table>
    </div>
    `;

    container.innerHTML = html;
}

// Make function global for onclick
window.showRaceDetail = showRaceDetail;

// Initialize
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initBrowsePage);
} else {
    initBrowsePage();
}