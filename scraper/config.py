"""
Configuration constants used across the scraper.

"""

import os
from pathlib import Path

# Base headers used for requests (can be extended per-request)
HEADERS: dict[str, str] = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://www.britishhorseracing.com",
    "Referer": "https://www.britishhorseracing.com/",
}

# API URL templates
API_BASE: dict[str, str] = {
    # Fixtures overview (pagination and filtering via querystring)
    "fixtures": "https://api09.horseracing.software/bha/v1/fixtures/?fields=courseId,courseName,fixtureDate,fixtureType,fixtureSession,abandonedReasonCode,highlightTitle&month={month}&order=desc&page=1&per_page=250&resultsAvailable=1&year={year}",
    # Races in a fixture: /bha/v1/fixtures/{year}/{fixture_id}/races
    "races": "https://api09.horseracing.software/bha/v1/fixtures/{year}/{fixture_id}/races",
    # Results for a race: /bha/v1/races/{year}/{race_id}/0/results
    "results": "https://api09.horseracing.software/bha/v1/races/{year}/{race_id}/{division}/results",
    # Horse data
    "horses": "https://api09.horseracing.software/bha/v1/racehorses/{animal_id}",
    # Fixtures listed on page
    "fixture_list": "https://api09.horseracing.software/bha/v1/racecourses/",
}

# Mozilla headers for ATR
HEADERS_ATR: dict[str, str] = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://www.attheraces.com/",
    "Connection": "keep-alive",
}
API_ADD: dict[str, str] = {
    "User-Agent": "Mozilla/5.0",
    # Overview of section times tables
    "racecard": "https://www.attheraces.com/racecard/{course_slug}/{date_formatted}/{race_time}",
    "sections": "https://www.attheraces.com/ajax/sectionals-razor/{atr_race_id}/times?page=/racecard/{course_slug}/{date_formatted}/{race_time}&raceid={atr_race_id}",
}

# Cache and token management
DEFAULT_CACHE_DIR = Path("cache")
TOKEN_FILE = Path(f"{DEFAULT_CACHE_DIR}/token.json")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = os.getenv("SCRAPER_DB_PATH", str(PROJECT_ROOT / "cache" / "scraper_dump.db"))
REQUEST_TIMEOUT: int = 15
MAX_RETRIES: int = 3
BACKOFF_FACTOR: int = 2
TIMEOUT_MS: int = 60000

COURSE_NAME_MAPPINGS = {"Chelmsford City": "Chelmsford", "": ""}
