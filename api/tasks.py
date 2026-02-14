"""
Background task for running scraper - Updated with stop functionality.
"""

import threading
import uuid

from django.db import close_old_connections
from django.utils import timezone

from scraper.service import ScraperService

from .models import ScrapeJob
from .sync import sync_scraper_to_django


# Global dictionary to track stop flags for running jobs
_stop_flags = {}


# Human-readable message mapping
PROGRESS_MESSAGES = {
    "step_completed": {
        "fixtures": "Miejsca wyścigów znalezione i zapisane",
        "races": "Szczegóły wyścigów pobrane",
        "performances": "Dane występów koni zebrane",
        "sync": "Import danych do bazy głównej",
    },
    "step_started": {
        "fixtures": "🔍 Wyszukiwanie miejsc wyścigów...",
        "races": "🏇 Pobieranie szczegółów wyścigów...",
        "performances": "📊 Zbieranie danych występów koni...",
        "sync": "💾 Importowanie danych do bazy głównej...",
    },
}


def get_human_message(event: str, name: str, count: int = None) -> str:
    """Convert technical event/name into human-readable Polish message."""
    if event == "step_started":
        return PROGRESS_MESSAGES["step_started"].get(name, f"Przetwarzanie {name}...")
    elif event == "step_completed":
        base_msg = PROGRESS_MESSAGES["step_completed"].get(name, f"{name} ukończone")
        if count is not None:
            return f"✓ {base_msg} ({count:,} elementów)"
        return f"✓ {base_msg}"
    else:
        return f"Przetwarzanie: {name}"


def run_scraper_task(job_id: str, days_back: int, filters: dict = None):
    scrape_job = None
    try:
        close_old_connections()

        # Initialize stop flag for this job
        _stop_flags[job_id] = False

        scrape_job = ScrapeJob.objects.get(job_id=job_id)
        scrape_job.status = "running"
        scrape_job.started_at = timezone.now()
        scrape_job.status_message = "🚀 Uruchamianie skanera..."
        scrape_job.progress_percent = 0
        scrape_job.save(
            update_fields=["status", "started_at", "status_message", "progress_percent"]
        )

        def progress_callback(event: str, data: dict):
            """Enhanced progress callback with human-readable messages and stop check."""

            # Check if stop was requested
            if _stop_flags.get(job_id, False):
                raise InterruptedError("Skanowanie zatrzymane przez użytkownika")

            step = data.get("step", 0)
            name = data.get("name", "unknown")
            count = data.get("count")

            if event == "step_started":
                message = get_human_message("step_started", name)
                base_percent = int((step - 1) / scrape_job.total_steps * 100)
                scrape_job.update_progress(
                    step=step, message=message, percent=base_percent
                )

            elif event == "step_completed":
                message = get_human_message("step_completed", name, count)
                percent = int(step / scrape_job.total_steps * 100)
                scrape_job.update_progress(
                    step=step,
                    data={name: count} if count is not None else None,
                    message=message,
                    percent=percent,
                )

            elif event == "progress":
                current = data.get("current", 0)
                total = data.get("total", 1)

                step_progress = (current / total) if total > 0 else 0
                base_percent = int((step - 1) / scrape_job.total_steps * 100)
                step_size = int(100 / scrape_job.total_steps)
                percent = base_percent + int(step_size * step_progress)

                message = f"Przetwarzanie {name}: {current:,} z {total:,}"
                scrape_job.update_progress(step=step, message=message, percent=percent)

        service = ScraperService(
            enable_logging=True, progress_callback=progress_callback
        )

        scrape_job.status_message = "🔄 Pobieranie danych ze źródła..."
        scrape_job.save(update_fields=["status_message"])

        scrape_result = service.scrape_days_back(days_back=days_back, filters=filters)

        # Check if stopped during scraping
        if _stop_flags.get(job_id, False):
            raise InterruptedError("Skanowanie zatrzymane przez użytkownika")

        scrape_job.stats = scrape_result.get("stats") or {}
        scrape_job.error_message = scrape_result.get("error")
        scrape_job.save(update_fields=["stats", "error_message"])

        # Sync staging -> Django
        scrape_job.status_message = "💾 Importowanie danych do bazy głównej..."
        scrape_job.progress_percent = 80
        scrape_job.save(update_fields=["status_message", "progress_percent"])

        sync_stats = sync_scraper_to_django()

        merged = dict(scrape_job.stats or {})
        merged.update(
            {
                "imported_fixtures": sync_stats.fixtures_upserted,
                "imported_races": sync_stats.races_upserted,
                "imported_horses": sync_stats.horses_upserted,
                "imported_performances": sync_stats.performances_upserted,
            }
        )
        scrape_job.stats = merged

        scrape_job.status = "completed" if scrape_result.get("success") else "failed"
        scrape_job.completed_at = timezone.now()
        scrape_job.progress_percent = 100

        if scrape_result.get("success"):
            total_races = merged.get("races_saved", 0)
            scrape_job.status_message = (
                f"✅ Ukończono! Przetworzono {total_races:,} wyścigów"
            )
        else:
            scrape_job.status_message = "❌ Skanowanie nie powiodło się"

        scrape_job.save(
            update_fields=[
                "status",
                "stats",
                "completed_at",
                "status_message",
                "progress_percent",
            ]
        )

    except InterruptedError as e:
        # Job was stopped by user
        if scrape_job:
            scrape_job.status = "failed"
            scrape_job.error_message = str(e)
            scrape_job.completed_at = timezone.now()
            scrape_job.status_message = f"⛔ {str(e)}"
            scrape_job.progress_percent = 0
            scrape_job.save(
                update_fields=[
                    "status",
                    "error_message",
                    "completed_at",
                    "status_message",
                    "progress_percent",
                ]
            )
    except Exception as e:
        if scrape_job:
            scrape_job.status = "failed"
            scrape_job.error_message = str(e)
            scrape_job.completed_at = timezone.now()
            scrape_job.status_message = f"❌ Błąd: {str(e)}"
            scrape_job.progress_percent = 0
            scrape_job.save(
                update_fields=[
                    "status",
                    "error_message",
                    "completed_at",
                    "status_message",
                    "progress_percent",
                ]
            )
    finally:
        # Clean up stop flag
        if job_id in _stop_flags:
            del _stop_flags[job_id]
        close_old_connections()


def start_scrape_job(days_back: int, filters: dict = None) -> str:
    """Start a new scrape job in a background thread."""
    new_job_id = str(uuid.uuid4())
    ScrapeJob.objects.create(
        job_id=new_job_id,
        days_back=days_back,
        filters=filters or {},
        status="pending",
        status_message="⏳ Oczekiwanie na start...",
        progress_percent=0,
    )

    threading.Thread(
        target=run_scraper_task,
        args=(new_job_id, days_back, filters),
        daemon=True,
    ).start()

    return new_job_id


def stop_scrape_job(job_id: str) -> bool:
    """
    Request a scrape job to stop.

    Note: This sets a flag that the scraper checks periodically.
    The actual thread cannot be forcefully terminated, but will
    exit gracefully when it checks the flag.

    Returns:
        bool: True if stop flag was set, False if job not running
    """
    if job_id in _stop_flags:
        _stop_flags[job_id] = True
        return True
    return False