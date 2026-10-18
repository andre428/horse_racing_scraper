"""
Step 1: Fetch fixtures for a date range.

Pipeline role:
    Step 1 → fixtures (THIS FILE)
    Step 2 → races
    Step 3 → results
    Step 4 → horses
    Step 5 → sectionals

Behavior:
- Fixtures API is month-scoped; one HTTP request per (year, month) in range.
- Server does not filter by course or fixture type; filtering is client-side.

Key design decisions:
✔ Uses fetch_with_retry() for ALL HTTP calls
✔ Relies on global RateLimiter (passed from service)
✔ No internal retry loops (delegated to HTTP layer)
✔ Idempotent DB writes (INSERT OR REPLACE)
"""

from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any

from .config import API_BASE
from .db_tool import get_connection, init_database
from .http_ops import fetch_with_retry
from .rate_limiter import RateLimiter
from .schemas import FixtureFilters, FixtureRow, FixturesSummary
from .token_manager import TokenManager
from .utils import warn

# =========================================================
# 🔹 HELPERS
# =========================================================


def _parse_iso_date(value: str | None, default: date) -> date:
    if not value:
        return default
    return datetime.fromisoformat(value).date()


def _fetch_month_payload(
    token_manager: TokenManager, rate_limiter: RateLimiter, url: str
) -> dict[str, Any] | None:
    """Fetch a one-month page; return None if the payload shape is unusable."""
    payload = fetch_with_retry(url=url, token_manager=token_manager, rate_limiter=rate_limiter)

    if not isinstance(payload, dict):
        warn("step1_invalid_response_type", response_type=type(payload).__name__)
        return None

    return payload


def _fixture_date_in_range(fixture_date: str, start_dt: date, end_dt: date) -> bool:
    try:
        fixture_dt = datetime.fromisoformat(fixture_date).date()
    except ValueError:
        return False
    return start_dt <= fixture_dt <= end_dt


def _matches_filters(item: dict[str, Any], filters: FixtureFilters | None) -> bool:
    if not filters:
        return True

    fixture_types = filters.get("fixture_types")
    courses = filters.get("courses")

    return (fixture_types is None or item.get("fixtureType") in fixture_types) and (
        courses is None or item.get("courseName") in courses
    )


def _build_fixture_row(item: dict[str, Any]) -> FixtureRow | None:
    fixture_date = item.get("fixtureDate")
    if not isinstance(fixture_date, str) or not fixture_date:
        return None

    return {
        "fixture_id": item.get("fixtureId"),
        "fixture_date": fixture_date,
        "course_name": item.get("courseName"),
        "course_id": item.get("courseId"),
        "meeting_id": item.get("meetingId"),
        "first_race": item.get("firstRace"),
        "number_of_races": item.get("numberOfRaces"),
        "fixture_type": item.get("fixtureType"),
        "major_event": item.get("majorEvent"),
        "results_available": int(item.get("resultsAvailable") or 0),
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "processed": 0,
    }


def _iter_months(start: date, end: date) -> Iterator[tuple[int, int]]:
    """Generate (year, month) tuples for each month in the date range."""
    year, month = start.year, start.month
    end_year, end_month = end.year, end.month

    while (year, month) <= (end_year, end_month):
        yield year, month
        month += 1
        if month > 12:
            year, month = year + 1, 1


# =========================================================
# 🔹 MAIN ENTRY
# =========================================================


def fetch_fixtures_range(
    token_manager: TokenManager,
    start_date: str | None = None,
    end_date: str | None = None,
    filters: FixtureFilters | None = None,
    rate_limiter: RateLimiter | None = None,
) -> FixturesSummary:
    """
    Fetch fixtures for the given date range and persist them.

    Args:
        end_date ():
        start_date ():
        token_manager: authentication handler
        start_date / end_date: ISO dates (inclusive range); defaults to today
        filters: optional client-side fixture filters
        rate_limiter: global rate limiter (REQUIRED)
    """
    if rate_limiter is None:
        raise ValueError("RateLimiter must be provided")

    init_database()

    start_dt = _parse_iso_date(start_date, default=datetime.now(UTC).date())
    end_dt = _parse_iso_date(end_date, default=start_dt)

    fixtures_to_save: list[FixtureRow] = []
    months_fetched = 0

    for year, month in _iter_months(start_dt, end_dt):
        url = API_BASE["fixtures"].format(month=month, year=year)
        months_fetched += 1

        try:
            payload = _fetch_month_payload(token_manager, rate_limiter, url)
            if payload is None:
                continue

            fixtures_list = payload.get("data") or []
            if not isinstance(fixtures_list, list):
                warn("step1_invalid_fixtures_list", response_type=type(fixtures_list).__name__)
                continue

            for item in fixtures_list:
                if not isinstance(item, dict):
                    continue

                fixture_date = item.get("fixtureDate")
                if not isinstance(fixture_date, str) or not fixture_date:
                    continue

                if not _fixture_date_in_range(fixture_date, start_dt, end_dt):
                    continue

                if not _matches_filters(item, filters):
                    continue

                row = _build_fixture_row(item)
                if row is not None:
                    fixtures_to_save.append(row)

        except RuntimeError as exc:
            warn("step1_month_failed", year=year, month=month, error=str(exc))

            continue

    if fixtures_to_save:
        save_fixtures(fixtures_to_save)

    return {
        "date_range": f"{start_date} → {end_date}",
        "months_checked": months_fetched,
        "fixtures_saved": len(fixtures_to_save),
    }


# =========================================================
# 🔹 DB WRITE
# =========================================================


def save_fixtures(fixtures: list[FixtureRow]) -> None:
    """Persist fixture rows to the database."""
    if not fixtures:
        return

    with get_connection() as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO fixtures(fixture_id, fixture_date, course_name, course_id, meeting_id, first_race,
            number_of_races, fixture_type, major_event, results_available, fetched_at, processed)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    f.get("fixture_id"),
                    f.get("fixture_date"),
                    f.get("course_name"),
                    f.get("course_id"),
                    f.get("meeting_id"),
                    f.get("first_race"),
                    f.get("number_of_races"),
                    f.get("fixture_type"),
                    f.get("major_event"),
                    1 if f.get("results_available") else 0,
                    datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"),
                    f.get("processed"),
                )
                for f in fixtures
            ],
        )
