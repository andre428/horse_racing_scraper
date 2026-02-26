/**
 * Scraper Page Logic - WITH JOB PERSISTENCE
 */

// State
let selectedCourses = new Set();
let currentJobId = null;
let pollInterval = null;

// Step configuration (UPDATED TO 5 STEPS)
const STEPS = [
    {
        number: 1,
        icon: 'fa-map-marker-alt',
        label: 'Miejsca wyścigów',
        description: 'Skanowanie i zapis miejsc wyścigów'
    },
{
      number: 2,
    icon: 'fa-flag-checkered',
    label: 'Wyścigi',
    description: 'Skanowanie i zapis wyścigów'
},
{
    number: 3,
    icon: 'fa-chart-line',
    label: 'Wyniki',
    description: 'Skanowanie i zapis wyników wyścigów'
},
{
    number: 4,
    icon: 'fa-horse',
      label: 'Dane koni',
    description: 'Skanowanie danych koni'
},
{
    number: 5,
    icon: 'fa-database',
    label: 'Transfer do bazy',
    description: 'Import danych do głównej bazy'
}
];

/**
 * Initialize scraper page
 */
function initScraperPage() {
    setupCourseAutocomplete();
    setupPresetLoader();
    setupFormSubmit();
    setupStopButton();
    setupResetButton();
    setupSavePreset();

    // NEW: Check for running job on page load
    checkForRunningJob();
}

/**
 * Check if there's a running job when page loads
 */
async function checkForRunningJob() {
    try {
        const result = await API.scraper.jobs();

        if (result.success && result.data.length > 0) {
            // Find most recent running or pending job
            const runningJob = result.data.find(job =>
            job.status === 'running' || job.status === 'pending'
            );

            if (runningJob) {
                console.log('Found running job:', runningJob.job_id);

                // Resume tracking this job
                currentJobId = runningJob.job_id;

                // Show progress UI
                show('#progress-container');
                show('#stop-btn');

                // Disable submit button
                const submitBtn = document.getElementById('submit-btn');
                submitBtn.disabled = true;
                submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Skanowanie w trakcie...';

                // Start polling
                pollProgress(currentJobId);

                showAlert('Kontynuowanie zadania: ' + runningJob.job_id.substring(0, 8), 'info');
            }
        }
    } catch (error) {
        console.error('Error checking for running job:', error);
    }
}

/**
 * Progress polling with better error handling
 */
async function pollProgress(jobId) {
    if (pollInterval) clearInterval(pollInterval);

    pollInterval = setInterval(async () => {
        const result = await API.scraper.status(jobId);

        if (result.success) {
            updateProgress(result.data);
        } else {
            // Job not found or error - stop polling
            console.error('Error polling job:', result.error);
            clearInterval(pollInterval);

            showAlert('Utracono połączenie z zadaniem', 'warning');
            resetUI();
        }
    }, 1000);  // Poll every second
}

/**
 * Update progress display
 */
function updateProgress(job) {
    const currentStep = job.current_step || 1;

    // Update step indicators (NOW 5 STEPS)
    document.querySelectorAll('.step').forEach((item, index) => {
        const stepNum = index + 1;

        if (stepNum < currentStep) {
            item.classList.add('completed');
            item.classList.remove('active');
        } else if (stepNum === currentStep) {
            item.classList.add('active');
            item.classList.remove('completed');
        } else {
            item.classList.remove('active', 'completed');
        }
    });

    // Update step counts from stats
    if (job.stats) {
        const steps = document.querySelectorAll('.step');

        // Step 1: Fixtures
        if (steps[0] && job.stats.fixtures_saved !== undefined) {
            steps[0].querySelector('.step-value').textContent = formatNumber(job.stats.fixtures_saved);
        }

        // Step 2: Races
        if (steps[1] && job.stats.races_saved !== undefined) {
            steps[1].querySelector('.step-value').textContent = formatNumber(job.stats.races_saved);
        }

        // Step 3: Performances
        if (steps[2] && job.stats.performances_saved !== undefined) {
            steps[2].querySelector('.step-value').textContent = formatNumber(job.stats.performances_saved);
        }

        // Step 4: Horses
        if (steps[3] && job.stats.horses_saved !== undefined) {
            steps[3].querySelector('.step-value').textContent = formatNumber(job.stats.horses_saved);
        }

        // Step 5: Import
        if (steps[4] && job.stats.imported_fixtures !== undefined) {
            steps[4].querySelector('.step-value').textContent = formatNumber(job.stats.imported_fixtures);
        }
    }

    // Update status message
    const statusMsg = document.getElementById('status-message');
    if (statusMsg && job.status_message) {
        statusMsg.textContent = job.status_message;
    }

    // Check completion or failure
    if (job.status === 'completed') {
        handleJobComplete(job);
    } else if (job.status === 'failed') {
        handleJobFailed(job);
    } else if (job.status === 'stopped') {
        handleJobStopped(job);
    }
}

/**
 * Handle job completion
 */
function handleJobComplete(job) {
    clearInterval(pollInterval);
    pollInterval = null;

    showAlert('✅ Skanowanie zakończone pomyślnie!', 'success');

    // Mark all steps as completed
    document.querySelectorAll('.step').forEach(item => {
        item.classList.add('completed');
        item.classList.remove('active');
    });

    resetUI();

    // Reload page after 3 seconds to show updated job list
    setTimeout(() => location.reload(), 3000);
}

/**
 * Handle job failure
 */
function handleJobFailed(job) {
    clearInterval(pollInterval);
    pollInterval = null;

    const errorMsg = job.error_message || 'Nieznany błąd';
    showAlert('❌ Skanowanie nie powiodło się: ' + errorMsg, 'danger');

    resetUI();
}

/**
 * Handle job stopped by user
 */
function handleJobStopped(job) {
    clearInterval(pollInterval);
    pollInterval = null;

    showAlert('⛔ Skanowanie zatrzymane', 'warning');

    resetUI();
}

/**
 * Stop button with proper cleanup
 */
function setupStopButton() {
    const stopBtn = document.getElementById('stop-btn');
    if (!stopBtn) return;

    stopBtn.addEventListener('click', async () => {
        if (!currentJobId) {
            showAlert('Brak aktywnego zadania do zatrzymania', 'warning');
            return;
        }

        if (!confirm('Czy na pewno chcesz zatrzymać skanowanie?')) {
            return;
        }

        // Disable stop button to prevent double-click
        stopBtn.disabled = true;
        stopBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Zatrzymywanie...';

        const result = await API.scraper.stop(currentJobId);

        if (result.success) {
            // Success - UI will be reset by handleJobStopped when poll detects stopped status
            showAlert('⛔ Zatrzymywanie zadania...', 'info');
        } else {
            // Error stopping
            showAlert('Błąd zatrzymywania: ' + result.error, 'danger');

            // Re-enable stop button
            stopBtn.disabled = false;
            stopBtn.innerHTML = '<i class="fas fa-stop"></i> STOP';
        }
    });
}

/**
 * Reset UI to default state
 */
function resetUI() {
    // Stop polling
    if (pollInterval) {
        clearInterval(pollInterval);
        pollInterval = null;
    }

    // Hide progress UI
    hide('#progress-container');
    hide('#stop-btn');

    // Reset submit button
    const submitBtn = document.getElementById('submit-btn');
    if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.innerHTML = '<i class="fas fa-play"></i> Rozpocznij Skanowanie';
    }

    // Reset all step indicators
    document.querySelectorAll('.step').forEach(item => {
        item.classList.remove('active', 'completed');
        const valueEl = item.querySelector('.step-value');
        if (valueEl) valueEl.textContent = '-';
    });

        // Clear current job
        currentJobId = null;
}

/**
 * Form submission (unchanged, but included for completeness)
 */
function setupFormSubmit() {
    const form = document.getElementById('scrape-form');
    if (!form) return;

    form.addEventListener('submit', async (e) => {
        e.preventDefault();

        const submitBtn = document.getElementById('submit-btn');
        const stopBtn = document.getElementById('stop-btn');

        // Collect form data
        const daysBack = parseInt(document.getElementById('days-back').value);
        const fixtureTypes = Array.from(document.querySelectorAll('[name="fixture_types"]:checked'))
        .map(cb => cb.value);
        const raceClasses = Array.from(document.querySelectorAll('[name="race_classes"]:checked'))
        .map(cb => parseInt(cb.value));
        const minDistance = document.getElementById('minimum-distance').value;
        const maxDistance = document.getElementById('maximum-distance').value;

        const requestData = { days_back: daysBack };

        if (fixtureTypes.length > 0) requestData.fixture_types = fixtureTypes;
                          if (selectedCourses.size > 0) requestData.courses = Array.from(selectedCourses);
                          if (raceClasses.length > 0) requestData.race_classes = raceClasses;
                          if (minDistance) requestData.minimum_distance = parseInt(minDistance);
                          if (maxDistance) requestData.maximum_distance = parseInt(maxDistance);

                          // Disable submit button
                          submitBtn.disabled = true;
        submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Uruchamianie...';

        // Start scrape
        const result = await API.scraper.start(requestData);

        if (result.success) {
            currentJobId = result.data.job_id;

            // Show progress UI
            show('#progress-container');
            show(stopBtn);

            showAlert('🚀 Skanowanie rozpoczęte!', 'success');

            // Reset step indicators
            document.querySelectorAll('.step').forEach(item => {
                item.classList.remove('active', 'completed');
                const valueEl = item.querySelector('.step-value');
                if (valueEl) valueEl.textContent = '-';
            });

                // Start polling
                pollProgress(currentJobId);
        } else {
            showAlert('Błąd: ' + result.error, 'danger');
            submitBtn.disabled = false;
            submitBtn.innerHTML = '<i class="fas fa-play"></i> Rozpocznij Skanowanie';
        }
    });
}

/**
 * Course autocomplete
 */
function setupCourseAutocomplete() {
    const searchInput = document.getElementById('course-search');
    const suggestions = document.getElementById('course-suggestions');

    if (!searchInput) return;

    searchInput.addEventListener('input', debounce((e) => {
        const query = e.target.value.toLowerCase().trim();

        if (!query) {
            suggestions.innerHTML = '';
            hide(suggestions);
            return;
        }

        const matches = allCourses.filter(course =>
        course.toLowerCase().includes(query) && !selectedCourses.has(course)
        );

        if (matches.length > 0) {
            suggestions.innerHTML = matches
            .slice(0, 10)
            .map(course => `<div class="suggestion-item" data-course="${course}">${course}</div>`)
            .join('');
            show(suggestions);
        } else {
            suggestions.innerHTML = '<div class="suggestion-item">Brak wyników</div>';
            show(suggestions);
        }
    }, 300));

    suggestions.addEventListener('click', (e) => {
        if (e.target.classList.contains('suggestion-item')) {
            const course = e.target.dataset.course;
            if (course) {
                addCourse(course);
                searchInput.value = '';
                hide(suggestions);
            }
        }
    });

    // Hide suggestions when clicking outside
    document.addEventListener('click', (e) => {
        if (!searchInput.contains(e.target) && !suggestions.contains(e.target)) {
            hide(suggestions);
        }
    });
}

function addCourse(course) {
    selectedCourses.add(course);
    renderSelectedCourses();
}

function removeCourse(course) {
    selectedCourses.delete(course);
    renderSelectedCourses();
}

function renderSelectedCourses() {
    const container = document.getElementById('selected-courses');
    if (!container) return;

    if (selectedCourses.size === 0) {
        container.innerHTML = '';
        return;
    }

    container.innerHTML = Array.from(selectedCourses)
    .map(course => `
    <span class="badge badge-primary">
    ${course}
    <i class="fas fa-times" onclick="removeCourse('${course}')" style="cursor: pointer; margin-left: 5px;"></i>
    </span>
    `)
    .join('');
}

/**
 * Preset loader
 */
function setupPresetLoader() {
    const selector = document.getElementById('preset-selector');
    if (!selector) return;

    selector.addEventListener('change', async (e) => {
        const presetId = e.target.value;
        if (!presetId) return;

        const result = await API.presets.get(presetId);

        if (result.success) {
            loadPresetData(result.data);
        } else {
            showAlert(`Błąd ładowania presetu: ${result.error}`, 'danger');
        }
    });
}

function loadPresetData(preset) {
    // Clear existing selections
    document.querySelectorAll('[name="fixture_types"]').forEach(cb => cb.checked = false);
    document.querySelectorAll('[name="race_classes"]').forEach(cb => cb.checked = false);
    selectedCourses.clear();
    document.getElementById('minimum-distance').value = '';
    document.getElementById('maximum-distance').value = '';

    // Load preset data
    if (preset.fixture_types?.length > 0) {
        document.querySelectorAll('[name="fixture_types"]').forEach(cb => {
            cb.checked = preset.fixture_types.includes(cb.value);
        });
    }

    if (preset.courses?.length > 0) {
        preset.courses.forEach(course => selectedCourses.add(course));
        renderSelectedCourses();
    }

    if (preset.minimum_distance) {
        document.getElementById('minimum-distance').value = preset.minimum_distance;
    }

    if (preset.maximum_distance) {
        document.getElementById('maximum-distance').value = preset.maximum_distance;
    }

    if (preset.race_classes?.length > 0) {
        document.querySelectorAll('[name="race_classes"]').forEach(cb => {
            cb.checked = preset.race_classes.includes(parseInt(cb.value));
        });
    }
}

/**
 * Form submission
 */
function setupFormSubmit() {
    const form = document.getElementById('scrape-form');
    if (!form) return;

    form.addEventListener('submit', async (e) => {
        e.preventDefault();

        const submitBtn = document.getElementById('submit-btn');
        const stopBtn = document.getElementById('stop-btn');

        // Collect form data
        const daysBack = parseInt(document.getElementById('days-back').value);
        const fixtureTypes = Array.from(document.querySelectorAll('[name="fixture_types"]:checked'))
        .map(cb => cb.value);
        const raceClasses = Array.from(document.querySelectorAll('[name="race_classes"]:checked'))
        .map(cb => parseInt(cb.value));
        const minDistance = document.getElementById('minimum-distance').value;
        const maxDistance = document.getElementById('maximum-distance').value;

        const requestData = { days_back: daysBack };

        if (fixtureTypes.length > 0) requestData.fixture_types = fixtureTypes;
                          if (selectedCourses.size > 0) requestData.courses = Array.from(selectedCourses);
                          if (raceClasses.length > 0) requestData.race_classes = raceClasses;
                          if (minDistance) requestData.minimum_distance = parseInt(minDistance);
                          if (maxDistance) requestData.maximum_distance = parseInt(maxDistance);

                          // Disable submit button
                          submitBtn.disabled = true;
        submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Uruchamianie...';

        // Start scrape
        const result = await API.scraper.start(requestData);

        if (result.success) {
            currentJobId = result.data.job_id;

            // Show progress UI
            show('#progress-container');
            show(stopBtn);

            showAlert('🚀 Skanowanie rozpoczęte!', 'success');

            // Reset step indicators
            document.querySelectorAll('.step').forEach(item => {
                item.classList.remove('active', 'completed');
                const valueEl = item.querySelector('.step-value');
                if (valueEl) valueEl.textContent = '-';
            });

                // Start polling
                pollProgress(currentJobId);
        } else {
            showAlert(`Błąd: ${result.error}`, 'danger');
            submitBtn.disabled = false;
            submitBtn.innerHTML = '<i class="fas fa-play"></i> Rozpocznij Skanowanie';
        }
    });
}

/**
 * Progress polling
 */
async function pollProgress(jobId) {
    if (pollInterval) clearInterval(pollInterval);

    pollInterval = setInterval(async () => {
        const result = await API.scraper.status(jobId);

        if (result.success) {
            updateProgress(result.data);
        }
    }, 1000);
}

function updateProgress(job) {
    // Update step indicators
    document.querySelectorAll('.step').forEach((item, index) => {
        const stepNum = index + 1;

        if (stepNum < job.current_step) {
            item.classList.add('completed');
            item.classList.remove('active');
        } else if (stepNum === job.current_step) {
            item.classList.add('active');
            item.classList.remove('completed');
        } else {
            item.classList.remove('active', 'completed');
        }
    });

    // Update counts
    if (job.stats) {
        const steps = document.querySelectorAll('.step');
        if (steps[0] && job.stats.fixtures_saved) {
            steps[0].querySelector('.step-value').textContent = formatNumber(job.stats.fixtures_saved);
        }
        if (steps[1] && job.stats.races_saved) {
            steps[1].querySelector('.step-value').textContent = formatNumber(job.stats.races_saved);
        }
        if (steps[2] && job.stats.performances_saved) {
            steps[2].querySelector('.step-value').textContent = formatNumber(job.stats.performances_saved);
        }
        if (steps[3] && job.stats.imported_fixtures) {
            steps[3].querySelector('.step-value').textContent = formatNumber(job.stats.imported_fixtures);
        }
    }

    // Update status message
    const statusMsg = document.getElementById('status-message');
    if (statusMsg) {
        statusMsg.textContent = job.status_message || STEP_NAMES[job.current_step] || 'Przetwarzanie...';
    }

    // Check completion
    if (job.status === 'completed') {
        handleJobComplete(job);
    } else if (job.status === 'failed') {
        handleJobFailed(job);
    }
}

function handleJobComplete(job) {
    clearInterval(pollInterval);

    showAlert('✅ ' + (job.status_message || 'Skanowanie zakończone!'), 'success');

    // Mark all as completed
    document.querySelectorAll('.step').forEach(item => {
        item.classList.add('completed');
        item.classList.remove('active');
    });

    resetUI();

    // Reload page after 3 seconds
    setTimeout(() => location.reload(), 3000);
}

function handleJobFailed(job) {
    clearInterval(pollInterval);

    showAlert('❌ ' + (job.error_message || 'Skanowanie nie powiodło się'), 'danger');

    resetUI();
}

/**
 * Stop button
 */
function setupStopButton() {
    const stopBtn = document.getElementById('stop-btn');
    if (!stopBtn) return;

    stopBtn.addEventListener('click', async () => {
        if (!currentJobId) return;

        if (!confirm('Czy na pewno chcesz zatrzymać skanowanie?')) return;

        const result = await API.scraper.stop(currentJobId);

        if (result.success) {
            resetUI();
            showAlert('⛔ Skanowanie zatrzymane', 'warning');
        } else {
            showAlert(`Błąd: ${result.error}`, 'danger');
        }
    });
}

/**
 * Reset UI to default state
 */
function resetUI() {
    if (pollInterval) {
        clearInterval(pollInterval);
        pollInterval = null;
    }

    hide('#progress-container');
    hide('#stop-btn');

    const submitBtn = document.getElementById('submit-btn');
    if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.innerHTML = '<i class="fas fa-play"></i> Rozpocznij Skanowanie';
    }

    document.querySelectorAll('.step').forEach(item => {
        item.classList.remove('active', 'completed');
        const valueEl = item.querySelector('.step-value');
        if (valueEl) valueEl.textContent = '-';
    });

        currentJobId = null;
}

/**
 * Reset button
 */
function setupResetButton() {
    const resetBtn = document.getElementById('reset-btn');
    if (!resetBtn) return;

    resetBtn.addEventListener('click', () => {
        document.getElementById('scrape-form').reset();
        selectedCourses.clear();
        renderSelectedCourses();
        document.getElementById('preset-selector').value = '';
        resetUI();
    });
}

/**
 * Save preset
 */
function setupSavePreset() {
    const saveBtn = document.getElementById('save-preset-btn');
    if (!saveBtn) return;

    saveBtn.addEventListener('click', async () => {
        const name = prompt('Wprowadź nazwę presetu:');
        if (!name) return;

        const description = prompt('Wprowadź opis (opcjonalnie):') || '';

        const fixtureTypes = Array.from(document.querySelectorAll('[name="fixture_types"]:checked'))
        .map(cb => cb.value);
        const raceClasses = Array.from(document.querySelectorAll('[name="race_classes"]:checked'))
        .map(cb => parseInt(cb.value));
        const minDistance = document.getElementById('minimum-distance').value;
        const maxDistance = document.getElementById('maximum-distance').value;

        const presetData = {
            name,
            description,
            fixture_types: fixtureTypes,
            courses: Array.from(selectedCourses),
                             race_classes: raceClasses,
                             minimum_distance: minDistance ? parseInt(minDistance) : null,
                             maximum_distance: maxDistance ? parseInt(maxDistance) : null
        };

        const result = await API.presets.save(presetData);

        if (result.success) {
            showAlert(result.data.message, 'success');
            setTimeout(() => location.reload(), 2000);
        } else {
            showAlert(`Błąd: ${result.error}`, 'danger');
        }
    });
}

// Initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initScraperPage);
} else {
    initScraperPage();
}