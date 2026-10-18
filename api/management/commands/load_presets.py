"""
Django management command to load filter presets.

Run with: python manage.py load_presets
Run with: python manage.py load_presets --clear (delete all first)
"""

from django.core.management.base import BaseCommand

from api.models import FilterPreset


class Command(BaseCommand):
    help = "Load system filter presets"

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Delete all existing presets before loading',
        )

    def handle(self, *args, **options):
        # Clear existing presets if requested
        if options['clear']:
            old_count = FilterPreset.objects.count()
            FilterPreset.objects.all().delete()
            self.stdout.write(
                self.style.WARNING(f"Deleted {old_count} existing preset(s)")
            )

        presets = [
            {
                "name": "Test Mode",
                "description": "Quick validation (33 days, Newcastle, 6f)",
                "fixture_types": ["FLAT"],
                "courses": ["Newcastle"],
                "race_type": "FLAT",
                "minimum_distance": 1300,
                "maximum_distance": 1350,
                "is_system": True,
            },
            {
                "name": "Premium Sprints",
                "description": "Top courses, up to 7 furlongs",
                "fixture_types": ["FLAT"],
                "courses": [
                    "Ascot",
                    "Newmarket",
                    "York",
                    "Goodwood",
                    "Epsom",
                    "Doncaster",
                    "Chester",
                    "Haydock Park",
                    "Sandown Park",
                    "Newbury",
                    "Curragh",
                ],
                "race_type": "FLAT",
                "maximum_distance": 1400,
                "race_classes": [1, 2, 3],
                "is_system": True,
            },
            {
                "name": "Elite Middle Distance",
                "description": "Class 1-2, 7f to 1.5 miles",
                "fixture_types": ["FLAT"],
                "race_type": "FLAT",
                "minimum_distance": 1400,
                "maximum_distance": 2400,
                "race_classes": [1, 2],
                "is_system": True,
            },
            {
                "name": "Jump Racing",
                "description": "National Hunt races",
                "fixture_types": ["JUMP"],
                "race_type": "JUMP",
                "is_system": True,
            },
            {
                "name": "Major Championships",
                "description": "Class 1 only, top 5 courses",
                "fixture_types": ["FLAT"],
                "courses": ["Ascot", "Newmarket", "Epsom", "Goodwood", "Doncaster"],
                "race_type": "FLAT",
                "race_classes": [1],
                "is_system": True,
            },
            {
                "name": "All Flat",
                "description": "All flat racing, no filters",
                "fixture_types": ["FLAT"],
                "race_type": "FLAT",
                "is_system": True,
            },
        ]

        created_count = 0
        updated_count = 0

        for preset_data in presets:
            preset, created = FilterPreset.objects.update_or_create(
                name=preset_data["name"], defaults=preset_data
            )

            if created:
                created_count += 1
                self.stdout.write(
                    self.style.SUCCESS(f"✓ Created preset: {preset.name}")
                )
            else:
                updated_count += 1
                self.stdout.write(
                    self.style.WARNING(f"→ Updated preset: {preset.name}")
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone! Created: {created_count}, Updated: {updated_count}"
            )
        )
