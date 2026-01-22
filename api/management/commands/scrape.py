# management/commands/scrape_races.py
from django.core.management.base import BaseCommand
from scraper.service import ScraperService
from django.utils import timezone
from api.models import ScrapeJob


class Command(BaseCommand):
    help = 'Scrape race data for specified date range'

    def add_arguments(self, parser):
        parser.add_argument('--days-back', type=int, default=7)
        parser.add_argument('--course', type=str, default=None)
        parser.add_argument('--verbose', action='store_true')

    def handle(self, *args, **options):
        days_back = options['days_back']
        course = options['course']
        verbose = options['verbose']

        # Create the job record
        job = ScrapeJob.objects.create(
            job_id=f"cmd_{timezone.now().timestamp()}",
            status="running"
        )

        # Progress callback for console output
        def progress_callback(event, data):
            if verbose:
                self.stdout.write(
                    self.style.SUCCESS(f"[{event}] {data}")
                )
            job.add_log(event, data)

        # Build filters
        filters = {}
        if course:
            filters["courses"] = [course]

        # Run scraper
        self.stdout.write(f"Starting scrape: {days_back} days back")

        service = ScraperService(
            enable_logging=verbose,
            progress_callback=progress_callback
        )

        result = service.scrape_days_back(
            days_back=days_back,
            filters=filters if filters else None
        )

        # Update job
        job.status = "completed" if result["success"] else "failed"
        job.stats = result["stats"]
        job.completed_at = timezone.now()
        job.save()

        # Output summary
        if result["success"]:
            self.stdout.write(
                self.style.SUCCESS(
                    f"✓ Scrape complete: {result['stats']['races_saved']} races"
                )
            )
        else:
            self.stdout.write(
                self.style.ERROR(f"✗ Scrape failed: {result['error']}")
            )