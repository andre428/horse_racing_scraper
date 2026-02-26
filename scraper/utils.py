"""
Utility helpers for the package.

Provides:
- date_range helper (generator)
- simple logging wrappers (for future extension)
"""

import logging
from datetime import datetime, timedelta


def date_range(start: str, end: str):
    """
    Yield ISO date strings from start to end inclusive. Both inputs are "YYYY-MM-DD".
    """
    s = datetime.fromisoformat(start)
    e = datetime.fromisoformat(end)
    d = s
    while d <= e:
        yield d.strftime("%Y-%m-%d")
        d = d + timedelta(days=1)


logger = logging.getLogger("scraper")


def info(msg: str) -> None:
    """Simple info logging"""
    logger.info(f"[INFO] {msg}")


def warn(msg: str) -> None:
    """Simple warning logging"""
    logger.warning(f"[WARN] {msg}")
