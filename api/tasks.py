"""
Background task for running scraper.

Uses threading for simplicity. For production, use Celery.
"""

import threading
import uuid

from django.db import close_old_connections
from django.utils import timezone

from scraper.service import ScraperService

from .models import ScrapeJob
from .sync import sync_scraper_to_django


def run_scraper_task(job_id: str, days_back: int, filters: dict = None):
    scrape_job = None
    try:
        close_old_connections()

        scrape_job = ScrapeJob.objects.get(job_id=job_id)
        scrape_job.status = "running"
        scrape_job.started_at = timezone.now()
        scrape_job.save(update_fields=["status", "started_at"])

        def progress_callback(event: str, data: dict):
            if event == "step_completed":
                scrape_job.update_progress(
                    step=data.get("step", 0),
                    data={data.get("name", "unknown"): data.get("count", 0)},
                )

        service = ScraperService(enable_logging=True, progress_callback=progress_callback)
        scrape_result = service.scrape_days_back(days_back=days_back, filters=filters)

        # Save scraper-side stats/error first
        scrape_job.stats = scrape_result.get("stats") or {}
        scrape_job.error_message = scrape_result.get("error")
        scrape_job.save(update_fields=["stats", "error_message"])

        # Sync staging -> Django
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
        scrape_job.save(update_fields=["status", "stats", "completed_at"])

    except Exception as e:
        if scrape_job:
            scrape_job.status = "failed"
            scrape_job.error_message = str(e)
            scrape_job.completed_at = timezone.now()
            scrape_job.save(update_fields=["status", "error_message", "completed_at"])
    finally:
        close_old_connections()


def start_scrape_job(days_back: int, filters: dict = None) -> str:
    new_job_id = str(uuid.uuid4())
    ScrapeJob.objects.create(
        job_id=new_job_id,
        days_back=days_back,
        filters=filters or {},
        status="pending",
    )

    threading.Thread(
        target=run_scraper_task,
        args=(new_job_id, days_back, filters),
        daemon=True,
    ).start()

    return new_job_id

