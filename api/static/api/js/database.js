/**
 * Database Management Page Logic
 */

function initDatabasePage() {
    setupWipeButtons();
}

function setupWipeButtons() {
    // Wipe PostgreSQL
    const wipePgBtn = document.getElementById('wipe-pg-btn');
    if (wipePgBtn) {
        wipePgBtn.addEventListener('click', async () => {
            const confirmText = 'WYCZYŚĆ';
            const userInput = prompt(
                'Ta operacja usunie WSZYSTKIE dane z bazy PostgreSQL!\n\n' +
                'Wpisz "' + confirmText + '" aby potwierdzić:'
            );

            if (userInput !== confirmText) {
                showAlert('Operacja anulowana', 'info');
                return;
            }

            wipePgBtn.disabled = true;
            wipePgBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Czyszczenie...';

            const result = await API.database.wipePostgres();

            if (result.success) {
                showAlert('✓ ' + result.data.message, 'success');
                setTimeout(() => location.reload(), 2000);
            } else {
                showAlert('✗ Błąd: ' + result.error, 'danger');
                wipePgBtn.disabled = false;
                wipePgBtn.innerHTML = '<i class="fas fa-trash"></i> WYCZYŚĆ BAZĘ POSTGRESQL';
            }
        });
    }

    // Wipe SQLite
    const wipeSqliteBtn = document.getElementById('wipe-sqlite-btn');
    if (wipeSqliteBtn) {
        wipeSqliteBtn.addEventListener('click', async () => {
            if (!confirm('Czy na pewno chcesz wyczyścić bufor SQLite?')) {
                return;
            }

            wipeSqliteBtn.disabled = true;
            wipeSqliteBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Czyszczenie...';

            const result = await API.database.wipeSqlite();

            if (result.success) {
                showAlert('✓ ' + result.data.message, 'success');
                setTimeout(() => location.reload(), 2000);
            } else {
                showAlert('✗ Błąd: ' + result.error, 'danger');
                wipeSqliteBtn.disabled = false;
                wipeSqliteBtn.innerHTML = '<i class="fas fa-broom"></i> Wyczyść Bufor SQLite';
            }
        });
    }
}

// Initialize
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initDatabasePage);
} else {
    initDatabasePage();
}