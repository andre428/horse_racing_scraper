"""
Django models for the API app.

You can add models here to store scraped data in Django's database
or keep using the scraper's SQLite database (scraper.db) as a buffer.
"""

from django.db import models


class ScrapeJob(models.Model):
    """Track scraping jobs and their progress."""

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("running", "Running"),
        ("completed", "Completed"),
        ("failed", "Failed"),
    ]

    job_id = models.CharField(max_length=100, unique=True, db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")

    # Parameters
    days_back = models.IntegerField()
    filters = models.JSONField(default=dict, blank=True)

    # Progress tracking
    current_step = models.IntegerField(default=0)
    total_steps = models.IntegerField(default=4)
    status_message = models.CharField(max_length=255, blank=True, default="")
    progress_percent = models.IntegerField(default=0)

    # Results
    stats = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True, null=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["-created_at"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return f"ScrapeJob {self.job_id} - {self.status}"

    def duration(self):
        """Calculate job duration."""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None

    def update_progress(
        self, step: int, data: dict = None, message: str = None, percent: int = None
    ):
        """Update job progress with optional human-readable message."""
        self.refresh_from_db(
            fields=["stats", "current_step", "status_message", "progress_percent"]
        )
        self.current_step = step

        if message:
            self.status_message = message

        if percent is not None:
            self.progress_percent = min(100, max(0, percent))
        else:
            # Default: calculate from steps
            self.progress_percent = int((step / self.total_steps) * 100)

        if data:
            merged = dict(self.stats or {})
            merged.update(data)
            self.stats = merged

        self.save(
            update_fields=[
                "current_step",
                "stats",
                "status_message",
                "progress_percent",
            ]
        )


class FilterPreset(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)

    # Filter configuration
    fixture_types = models.JSONField(default=list)  # ["FLAT", "JUMP"]
    courses = models.JSONField(default=list)  # ["Newcastle", "Ascot"]
    race_type = models.CharField(max_length=10, blank=True)
    minimum_distance = models.IntegerField(null=True, blank=True)
    maximum_distance = models.IntegerField(null=True, blank=True)  # yards
    race_classes = models.JSONField(default=list)  # ["2yo", "3yo", "4yo", "5yo"]

    is_system = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def to_scraper_filters(self):
        """Convert to format expected by scraper."""
        filters = {}

        if self.fixture_types:
            filters["fixture_types"] = self.fixture_types

        if self.courses:
            filters["courses"] = self.courses

        if self.race_type:
            filters["race_type"] = self.race_type

        if self.minimum_distance is not None:
            filters["minimum_distance"] = self.minimum_distance

        if self.maximum_distance is not None:
            filters["maximum_distance"] = self.maximum_distance

        if self.race_classes:
            filters["race_classes"] = self.race_classes

        return filters


class Fixture(models.Model):
    source = models.CharField(max_length=50, default="bhra")
    external_id = models.CharField(
        max_length=128, unique=True, db_index=True
    )  # fixture_id as string
    date = models.DateField(null=True, blank=True)
    raw = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class Race(models.Model):
    source = models.CharField(max_length=50, default="bhra")
    external_id = models.CharField(
        max_length=128, unique=True, db_index=True
    )  # f"{race_id}:{division_sequence}"
    fixture = models.ForeignKey(
        Fixture, null=True, blank=True, on_delete=models.SET_NULL, related_name="races"
    )
    off_time = models.DateTimeField(null=True, blank=True)
    raw = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class Horse(models.Model):
    source = models.CharField(max_length=50, default="bhra")
    external_id = models.CharField(
        max_length=128, unique=True, db_index=True
    )  # animal_id as string
    name = models.CharField(max_length=255, blank=True, default="")
    dob = models.DateField(null=True, blank=True)
    raw = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class Performance(models.Model):
    source = models.CharField(max_length=50, default="bhra")
    external_id = models.CharField(
        max_length=128, unique=True, db_index=True
    )  # f"{race_id}:{animal_id}:{division_sequence}"
    race = models.ForeignKey(
        Race,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="performances",
    )
    horse = models.ForeignKey(
        Horse,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="performances",
    )
    raw = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
