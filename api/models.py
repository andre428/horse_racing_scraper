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

    def update_progress(self, step: int, data: dict = None):
        """Update job progress."""
        self.refresh_from_db(fields=["stats", "current_step"])
        self.current_step = step
        if data:
            merged = dict(self.stats or {})
            merged.update(data)
            self.stats = merged
        self.save(update_fields=["current_step", "stats"])


# --- Django-owned canonical storage (main DB) ---


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
        Race, null=True, blank=True, on_delete=models.SET_NULL, related_name="performances"
    )
    horse = models.ForeignKey(
        Horse, null=True, blank=True, on_delete=models.SET_NULL, related_name="performances"
    )
    raw = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
