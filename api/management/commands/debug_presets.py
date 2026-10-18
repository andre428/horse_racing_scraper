"""
Django management command to debug preset issues.

Run with: python manage.py debug_presets
"""

import json

from django.core.management.base import BaseCommand
from django.urls import get_resolver

from api.models import FilterPreset


class Command(BaseCommand):
    help = "Debug preset loading issues"

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("\n=== PRESET DEBUGGING ===\n"))

        # 1. Check database presets
        self.stdout.write(self.style.WARNING("1. Presets in database:"))
        presets = FilterPreset.objects.all()
        if presets.exists():
            for preset in presets:
                self.stdout.write(f"  ID: {preset.id}, Name: {preset.name}, System: {preset.is_system}")
        else:
            self.stdout.write(self.style.ERROR("  No presets found!"))

        # 2. Check URL patterns
        self.stdout.write(self.style.WARNING("\n2. Checking URL patterns:"))
        resolver = get_resolver()
        found_preset_get = False
        found_preset_save = False

        for pattern in resolver.url_patterns:
            if hasattr(pattern, 'url_patterns'):
                # This is an included URLconf
                for sub_pattern in pattern.url_patterns:
                    pattern_str = str(sub_pattern.pattern)
                    if 'preset' in pattern_str:
                        self.stdout.write(f"  Found: {pattern_str}")
                        if '<int:preset_id>' in pattern_str or '<preset_id>' in pattern_str:
                            found_preset_get = True
                        if 'save' in pattern_str:
                            found_preset_save = True

        if found_preset_get:
            self.stdout.write(self.style.SUCCESS("  ✓ GET preset URL found"))
        else:
            self.stdout.write(self.style.ERROR("  ✗ GET preset URL MISSING!"))

        if found_preset_save:
            self.stdout.write(self.style.SUCCESS("  ✓ Save preset URL found"))
        else:
            self.stdout.write(self.style.ERROR("  ✗ Save preset URL MISSING!"))

        # 3. Test preset retrieval
        self.stdout.write(self.style.WARNING("\n3. Testing preset retrieval:"))
        if presets.exists():
            first_preset = presets.first()
            try:
                data = {
                    "id": first_preset.id,
                    "name": first_preset.name,
                    "description": first_preset.description,
                    "fixture_types": first_preset.fixture_types,
                    "courses": first_preset.courses,
                    "race_type": first_preset.race_type,
                    "minimum_distance": first_preset.minimum_distance,
                    "maximum_distance": first_preset.maximum_distance,
                    "race_classes": first_preset.race_classes,
                }
                json_str = json.dumps(data)
                self.stdout.write(self.style.SUCCESS("  ✓ Preset serializes to JSON successfully"))
                self.stdout.write(f"  Sample: {json_str[:100]}...")
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  ✗ Failed to serialize: {e}"))

        # 4. Check views.py
        self.stdout.write(self.style.WARNING("\n4. Checking if views are imported:"))
        try:
            from api import views
            if hasattr(views, 'get_preset'):
                self.stdout.write(self.style.SUCCESS("  ✓ get_preset view exists"))
            else:
                self.stdout.write(self.style.ERROR("  ✗ get_preset view MISSING!"))

            if hasattr(views, 'save_preset'):
                self.stdout.write(self.style.SUCCESS("  ✓ save_preset view exists"))
            else:
                self.stdout.write(self.style.ERROR("  ✗ save_preset view MISSING!"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"  ✗ Error importing views: {e}"))

        # 5. Recommendations
        self.stdout.write(self.style.WARNING("\n5. Recommendations:"))
        self.stdout.write("  Run these commands:")
        self.stdout.write("    python manage.py show_urls | grep preset")
        self.stdout.write("    python manage.py reset_presets  (to clear all)")
        self.stdout.write("    python manage.py load_presets   (to reload)")

        self.stdout.write(self.style.SUCCESS("\n=== DEBUG COMPLETE ===\n"))
