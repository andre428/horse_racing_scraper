"""
Background task for running scraper
"""

import uuid

from celery import shared_task
from django.utils import timezone

from scraper.service import ScraperService

from .models import ScrapeJob
from .sync import sync_scraper_to_django

# =========================
# 🧠 PROGRESS MESSAGES (UNCHANGED)
# =========================

PROGRESS_MESSAGES = {
    "step_completed": {
        "fixtures": "Miejsca wyścigów znalezione i zapisane",
        "races": "Wyścigi pobrane i zapisane",
        "performances": "Wyniki wyścigów pobrane i zapisane",
        "horses": "Dane koni pobrane",
        "sectionals": "Czasy odcinkowe pobrane",
        "sync": "Import danych do bazy głównej ukończony",
    },
    "step_started": {
        "fixtures": "🔍 Krok 1/6: Skanowanie torów...",
        "races": "🏇 Krok 2/6: Skanowanie wyścigów...",
        "performances": "📊 Krok 3/6: Skanowanie wyników wyścigów...",
        "horses": "🐴 Krok 4/6: Skanowanie danych koni...",
        "sectional": "Krok 5/6: Skanowanie czasów odcinkowych...",
        "sync": "💾 Krok 6/6: Import danych do bazy głównej...",
    },
}


def get_human_message(event: str, name: str, count: int | None = None) -> str:
    if event == "step_started":
        return PROGRESS_MESSAGES["step_started"].get(name, f"Przetwarzanie {name}...")
    if event == "step_completed":
        base = PROGRESS_MESSAGES["step_completed"].get(name, f"{name} ukończone")
        return f"✓ {base} ({count:,})" if count is not None else f"✓ {base}"
    return f"Przetwarzanie: {name}"


# =========================
# 🚀 MAIN CELERY TASK
# =========================
@shared_task(
    bind=True,
    autoretry_for=(RuntimeError,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def run_scraper_task(job_id: str, days_back: int, filters: dict | None = None):
    job = ScrapeJob.objects.get(job_id=job_id)

    # =========================
    # 🔹 INIT JOB
    # =========================

    job.status = "running"
    job.started_at = timezone.now()
    job.status_message = "🚀 Starting scraper..."
    job.progress_percent = 0
    job.current_step = 1
    job.save()

    # =========================
    # 🔹 STOP MECHANISM (DB BASED)
    # =========================

    def should_stop() -> bool:
        job.refresh_from_db(fields=["status"])
        return job.status == "stopped"

    # =========================
    # 🔹 PROGRESS CALLBACK
    # =========================

    def progress_callback(event: str, data: dict):

        if should_stop():
            raise InterruptedError("Stopped by user")

        step = data.get("step", 1)
        name = data.get("name", "unknown")
        count = data.get("count")
        run_id = data.get("run_id")

        if event == "step_started":
            percent = int((step - 1) * 20)
            job.update_progress(
                step=step,
                message=f"[{run_id}] {name} started",
                percent=percent,
            )

        elif event == "step_completed":
            percent = int(step * 20)
            job.update_progress(
                step=step,
                message=f"[{run_id}] {name} done ({count})",
                percent=percent,
            )

    service = ScraperService(
        enable_logging=True,
        progress_callback=progress_callback,
        should_stop=should_stop,
    )

    try:
        result = service.scrape_days_back(days_back, filters)

        job.stats = result.get("stats")
        job.error_message = result.get("error")

        job.status = "completed" if result.get("success") else "failed"
        job.completed_at = timezone.now()
        job.progress_percent = 100

        job.save()

    except InterruptedError as e:
        job.status = "stopped"
        job.error_message = str(e)
        job.save()

    except Exception as e:
        job.status = "failed"
        job.error_message = str(e)
        job.save()

    # =========================
    # 🔹 RUN SCRAPER
    # =========================

    service = ScraperService(
        enable_logging=True,
        progress_callback=progress_callback,
        should_stop=should_stop,
    )

    try:
        result = service.scrape_days_back(days_back=days_back, filters=filters)

        if should_stop():
            raise InterruptedError("Skanowanie zatrzymane przez użytkownika")

        job.stats = result.get("stats") or {}
        job.error_message = result.get("error")
        job.save(update_fields=["stats", "error_message"])

        # =========================
        # 🔹 STEP 6: SYNC
        # =========================

        job.update_progress(
            step=6,
            message="💾 Krok 6/6: Import danych do bazy głównej...",
            percent=90,
        )

        if should_stop():
            raise InterruptedError("Skanowanie zatrzymane przez użytkownika")

        sync_stats = sync_scraper_to_django()

        merged = dict(job.stats or {})
        merged.update(
            {
                "imported_fixtures": sync_stats.fixtures_upserted,
                "imported_races": sync_stats.races_upserted,
                "imported_horses": sync_stats.horses_upserted,
                "imported_performances": sync_stats.performances_upserted,
            }
        )

        job.stats = merged

        # =========================
        # 🔹 COMPLETE
        # =========================

        job.status = "completed" if result.get("success") else "failed"
        job.completed_at = timezone.now()
        job.progress_percent = 100
        job.current_step = 6

        if result.get("success"):
            job.status_message = "✅ Ukończono!"
        else:
            job.status_message = "❌ Skanowanie nie powiodło się"

        job.save()

    except InterruptedError as e:
        job.status = "stopped"
        job.error_message = str(e)
        job.completed_at = timezone.now()
        job.status_message = f"⛔ {str(e)}"
        job.progress_percent = 0
        job.save()

    except Exception as e:
        job.status = "failed"
        job.error_message = str(e)
        job.completed_at = timezone.now()
        job.status_message = f"❌ Błąd: {str(e)}"
        job.progress_percent = 0
        job.save()


def start_scrape_job(days_back: int, filters: dict[str, int | str] | None = None) -> str:
    job_id = str(uuid.uuid4())

    ScrapeJob.objects.create(
        job_id=job_id,
        days_back=days_back,
        filters=filters or {},
        status="pending",
        status_message="Skanowanie rozpoczęte...",
        progress_percent=0,
        current_step=0,
    )

    run_scraper_task.delay(job_id, days_back, filters)

    return job_id
