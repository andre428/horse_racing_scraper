"""
koniki_scraper package

This package provides a 3-step scraper for britishhorseracing.com:
- Step 1: fetch fixtures for a date / date range
- Step 2: fetch races for fixtures
- Step 3: fetch results for races and export CSV

The package is organized so Django or any other app can import and use
the ScraperService class or individual steps.

For Django integration:
    from scraper.service import ScraperService

    service = ScraperService()
    result = service.scrape_date_range(dates=["2025-01-15"])
"""

__all__ = [
    "ScraperService",
    "cache_manager",
    "config",
    "http_ops.py",
    "step1_fixtures",
    "step2_races",
    "step3_results",
    "utils",
]

# Import the main service class for easy access
from .service import ScraperService