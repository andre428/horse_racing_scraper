"""
koniki_scraper package

Provides a multistep scraper pipeline:
1. fixtures
2. races
3. results
4. horses
5. sectionals

Usage:
    from scraper import ScraperService

    service = ScraperService()
    result = service.scrape_date_range(dates=["2025-01-15"])
"""

from .service import ScraperService

__all__ = ["ScraperService"]
