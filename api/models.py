"""
Django models for the API app.

You can add models here to store scraped data in Django's database,
or keep using the scraper's SQLite database (scraper.db) as a buffer.
"""

from django.db import models


# Example: If you want to store scraped data in Django's database
# class Fixture(models.Model):
#     fixture_id = models.IntegerField(primary_key=True)
#     fixture_date = models.DateField()
#     fixture_name = models.CharField(max_length=255)
#     # ... other fields
#     
#     class Meta:
#         db_table = "fixtures"
#         ordering = ["-fixture_date"]
