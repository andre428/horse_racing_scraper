"""
Management command to clean up old/stale scrape jobs.
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from api.models import ScrapeJob


class Command(BaseCommand):
    help = "Clean up old and stale scrape jobs"

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=3,
            help="Delete jobs older than this many days (default: 3)",
        )
        parser.add_argument(
            "--fix-stale",
            action="store_true",
            help="Mark running jobs older than 1 hour as failed",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be deleted without actually deleting",
        )

    def handle(self, *args, **options):
        days = options["days"]
        fix_stale = options["fix_stale"]
        dry_run = options["dry_run"]

        cutoff_date = timezone.now() - timedelta(days=days)

        self.stdout.write(f"\n{'=' * 60}")
        self.stdout.write("JOB CLEANUP SYSTEM")
        self.stdout.write(f"{'=' * 60}\n")

        # ============================================
        # 1. Fix stale "running" jobs
        # ============================================
        if fix_stale:
            stale_cutoff = timezone.now() - timedelta(hours=1)

            stale_jobs = ScrapeJob.objects.filter(
                status__in=["running", "pending"],
                created_at__lt=stale_cutoff,
            )

            stale_count = stale_jobs.count()

            if stale_count > 0:
                self.stdout.write(
                    f"Found {stale_count} stale running/pending jobs (older than 1 hour)"
                )

                if not dry_run:
                    updated = stale_jobs.update(
                        status="failed",
                        error_message="Zadanie przerwane (przekroczono limit czasu)",
                        status_message="❌ Przerwane przez system",
                        completed_at=timezone.now(),
                    )
                    self.stdout.write(
                        self.style.SUCCESS(f"✓ Marked {updated} stale jobs as failed")
                    )
                else:
                    self.stdout.write(
                        self.style.WARNING(
                            f"[DRY RUN] Would mark {stale_count} jobs as failed"
                        )
                    )

        # ============================================
        # 2. Delete old completed/failed jobs
        # ============================================
        old_jobs = ScrapeJob.objects.filter(
            created_at__lt=cutoff_date,
            status__in=["completed", "failed", "stopped"],
        )

        old_count = old_jobs.count()

        if old_count > 0:
            self.stdout.write(f"\nFound {old_count} old jobs (older than {days} days)")

            # Show breakdown
            for status in ["completed", "failed", "stopped"]:
                count = old_jobs.filter(status=status).count()
                if count > 0:
                    self.stdout.write(f"  - {status}: {count}")

            if not dry_run:
                deleted, _ = old_jobs.delete()
                self.stdout.write(self.style.SUCCESS(f"✓ Deleted {deleted} old jobs"))
            else:
                self.stdout.write(
                    self.style.WARNING(f"[DRY RUN] Would delete {old_count} jobs")
                )
        else:
            self.stdout.write(f"\nNo old jobs found (older than {days} days)")

        # ============================================
        # 3. Summary
        # ============================================
        remaining = ScrapeJob.objects.count()
        running = ScrapeJob.objects.filter(status="running").count()
        pending = ScrapeJob.objects.filter(status="pending").count()

        self.stdout.write(f"\n{'=' * 60}")
        self.stdout.write("SUMMARY")
        self.stdout.write(f"{'=' * 60}")
        self.stdout.write(f"Remaining jobs: {remaining}")
        self.stdout.write(f"  - Running: {running}")
        self.stdout.write(f"  - Pending: {pending}")
        self.stdout.write(f"{'=' * 60}\n")
