"""
Step 4: Section Times (ATR) Module
===================================

This module handles the fourth and final stage of the scraping pipeline:
fetching sectional times from ATR (At The Races) website.

Sectional times show a horse's performance at different points during a race,
providing detailed pace analysis data (e.g., times at 2f, 4f, 6f markers).

Workflow:
1. Read race data from buffer database (populated by Steps 1-3)
2. Build ATR racecard URL from race parameters
3. Extract ATR race_id from racecard page HTML
4. Build ATR sectionals API URL and scrape section times
5. Match horses to race_performances using horse names
6. Store section times in section_times table

Input: races table + race_performances table (from Steps 1-3)
Output: section_times table populated with sectional data
Note: ATR data may have delay - handle missing data gracefully

Pipeline Complete: After this step, all data is ready for Django import
"""

import re
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup

from .config import API_ADD, COURSE_NAME_MAPPINGS, HEADERS_ATR
from .db_tool import (
    get_connection,
    get_unsectioned_races,
    mark_sectioned,
    validate_race_count,
)


def fetch_sectionals(limit: int = 50):
    """
    Scan for races needing sectional times and fetch available tables.
    -check unprocessed races
    -check if sectional times already presented
    -scrape and save data with links for races and horses
    """
    with get_connection() as conn:
        races = get_unsectioned_races(conn, limit)

    stats = {"races_checked": 0, "sectionals_saved": 0, "races_done": 0}

    if not races:
        print("[DONE] No races to match sectionals")
    pass


def _format_date_for_atr(race_date: str) -> str:
    """
    Convert race date from database format to ATR URL format.

    Args:
        race_date: Date in "YYYY-MM-DD" format (from database)

    Returns:
        Date in "DD-Month-YYYY" format for ATR URLs

    Examples:
        _format_date_for_atr("2025-09-23")
        "23-September-2025"
        _format_date_for_atr("2025-01-05")
        "05-January-2025"

    Note:
        ATR uses full month names (September, not Sep) with leading
        zeros on day numbers (05, not 5).
    """
    date_obj = datetime.strptime(race_date, "%Y-%m-%d")
    return date_obj.strftime("%d-%B-%Y")


def _extract_atr_race_id(racecard_url: str) -> str | None:
    """
    Extract ATR's internal race ID from a racecard page.


    """
    try:
        response = requests.get(racecard_url, headers=HEADERS_ATR, timeout=30)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"ERROR: {e}")
        return None

    html_content = response.text
    match = re.search(r"/ajax/racecard/pacesummary/(\d+)", html_content)

    if match:
        race_id = match.group(1)
        print(f"Found ID: {race_id}")
        return race_id

    print("[Problem]: race ID not found on page")
    return None


def _racecard_url(course_slug: str, date_formatted: str, race_time: str) -> str:
    return ATR_RACE_TEMPLATE.format(
        course_slug=course_slug, date_formatted=date_formatted, race_time=race_time
    )


def _sectionals_url(atr_race_id: str, course_slug: str, date_formatted: str, race_time: str) -> str:
    return ATR_API_SECTIONAL.format(
        atr_race_id=atr_race_id,
        course_slug=course_slug,
        date_formatted=date_formatted,
        race_time=race_time,
    )


def _convert_time_to_seconds(time_str: str) -> float | None:
    """
    Convert ATR time string to seconds (float).

    Handles two formats:
    - "1m 50.42s" → 110.42 seconds
    - "50.42" → 50.42 seconds

    Args:
        time_str: Time string from ATR HTML

    Returns:
        Time in seconds as float, or None if parsing fails

    Examples:
        _convert_time_to_seconds("1m 50.42s")
        110.42
        _convert_time_to_seconds("50.42")
        50.42
        _convert_time_to_seconds("2m 5.3s")
        125.3

    Note:
        Handles optional 's' suffix and flexible whitespace.
        Returns None for invalid/empty strings.
    """
    if not time_str:
        return None

    time_str = time_str.strip()

    # Match pattern: optional minutes, required seconds
    # Pattern: (?:(\d+)m)?\s*(\d+(?:\.\d+)?)s?
    match = re.match(r"(?:(\d+)m)?\s*(\d+(?:\.\d+)?)s?", time_str)

    if not match:
        return None

    minutes = int(match.group(1)) if match.group(1) else 0
    seconds = float(match.group(2))

    return minutes * 60 + seconds