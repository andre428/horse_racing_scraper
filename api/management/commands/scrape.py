"""
Django management command to run the scraper.

Usage:
    python manage.py scrape 3    # Scrape last 3 days
    python manage.py scrape 1    # Scrape last 1 day (today + yesterday)
"""

from django.core.management.base import BaseCommand

from scraper.service import ScraperService


class Command(BaseCommand):
    help = "Scrape horse racing data for the last N days"

    def add_arguments(self, parser):
        parser.add_argument(
            "days_back",
            type=int,
            help="Number of days back to scrape (0 = today only, 1 = today + yesterday, etc.)",
        )
        parser.add_argument(
            "--output-csv",
            type=str,
            help="Optional path to CSV file for results export",
        )

    def handle(self, *args, **options):
        days_back = options["days_back"]
        output_csv = options.get("output_csv")

        if days_back < 0:
            self.stdout.write(
                self.style.ERROR("days_back must be >= 0")
            )
            return

        self.stdout.write(
            self.style.SUCCESS(f"Starting scraper for last {days_back} days...")
        )

        service = ScraperService(enable_logging=True)
        result = service.scrape_days_back(days_back=days_back, output_csv=output_csv)

        if result["success"]:
            self.stdout.write(
                self.style.SUCCESS(
                    f"✓ Scraping completed successfully!\n"
                    f"  Fixtures: {result['stats']['fixtures_count']}\n"
                    f"  Races: {result['stats']['races_count']}\n"
                    f"  Results: {result['stats']['results_count']}"
                )
            )
        else:
            self.stdout.write(
                self.style.ERROR(f"✗ Scraping failed: {result['error']}")
            )
