"""
Django management command to reset/delete all presets.

Run with: python manage.py reset_presets
"""

from django.core.management.base import BaseCommand
from api.models import FilterPreset


class Command(BaseCommand):
    help = "Delete all presets from the database"

    def add_arguments(self, parser):
        parser.add_argument(
            '--confirm',
            action='store_true',
            help='Actually delete presets (without this, just shows what would be deleted)',
        )

    def handle(self, *args, **options):
        presets = FilterPreset.objects.all()
        count = presets.count()
        
        if count == 0:
            self.stdout.write(self.style.WARNING("No presets found in database."))
            return
        
        self.stdout.write(f"\nFound {count} preset(s):")
        for preset in presets:
            self.stdout.write(f"  - {preset.name} (ID: {preset.id}, System: {preset.is_system})")
        
        if options['confirm']:
            presets.delete()
            self.stdout.write(self.style.SUCCESS(f"\n✓ Deleted {count} preset(s)"))
        else:
            self.stdout.write(self.style.WARNING(
                f"\n⚠ DRY RUN: Would delete {count} preset(s)"
            ))
            self.stdout.write(
                "Run with --confirm to actually delete: python manage.py reset_presets --confirm"
            )
