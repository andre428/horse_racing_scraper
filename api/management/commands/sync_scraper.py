from django.conf import settings
from django.core.management.base import BaseCommand

from api.sync import sync_scraper_to_django


class Command(BaseCommand):
    help = "Sync data from scraper staging SQLite DB into Django main DB"

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit", type=int, default=None, help="Limit rows per table (debug)"
        )

    def handle(self, *args, **options):
        self.stdout.write(f"Scraper DB: {settings.SCRAPER_DB_PATH}")
        self.stdout.write(f"Django DB:  {settings.DATABASES['default']['NAME']}")

        limit = options["limit"]
        stats = sync_scraper_to_django(limit=limit)

        self.stdout.write(
            self.style.SUCCESS(
                f"Synced: fixtures={stats.fixtures_upserted}, races={stats.races_upserted}, "
                f"horses={stats.horses_upserted}, performances={stats.performances_upserted}"
            )
        )
