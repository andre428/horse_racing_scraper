"""
Step 1: Fetch fixtures for one or multiple dates.

# The fixtures API is month-based and does NOT support server-side filtering.
# All filtering here is client-side by design.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, TypedDict

from .config import API_BASE
from .db_tool import get_connection, init_database
from .http_ops import fetch_json
from .token_manager import TokenManager


class FixtureFilters(TypedDict, total=False):
    fixture_types: list[str]
    courses: list[str]


class FixturesSummary(TypedDict):
    date_range: str
    months_checked: int
    fixtures_saved: int


class FixtureRow(TypedDict):
    fixture_id: int | None
    fixture_date: str
    course_name: str | None
    course_id: int | None
    meeting_id: int | None
    first_race: str | None
    number_of_races: int | None
    fixture_type: str | None
    major_event: str | None
    results_available: int
    fetched_at: str
    processed: int


def _parse_iso_date(value: str | None, default: date) -> date:
    if not value:
        return default
    return datetime.fromisoformat(value).date()


def _fetch_month_payload(token_manager: TokenManager, url: str) -> dict[str, Any] | None:
    """
    Fetch a URL and validate that the response is a dict payload.
    Returns None on invalid/unsupported response shapes.
    """
    token = token_manager.get_valid_token()
    payload = fetch_json(url, token)

    if not isinstance(payload, dict):
        print(f"[fetch_fixtures] Invalid response type: {type(payload)}")
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


def fetch_fixtures_range(
        token_manager: TokenManager,
        start_date: str | None = None,
        end_date: str | None = None,
        filters: FixtureFilters | None = None,
) -> FixturesSummary:
    """
    Fetch fixtures for date range and save to database.

    Returns summary dict with counts.
    """
    init_database()

    start_dt = _parse_iso_date(start_date, default=datetime.now(UTC).date())
    end_dt = _parse_iso_date(end_date, default=start_dt)

    fixtures_to_save: list[FixtureRow] = []
    months_fetched = 0

    for year, month in _iter_months(start_dt, end_dt):
        url = API_BASE["fixtures"].format(month=month, year=year)
        months_fetched += 1

        try:
            payload = _fetch_month_payload(token_manager, url)
            if payload is None:
                continue

            fixtures_list = payload.get("data") or []
            if not isinstance(fixtures_list, list):
                print(f"[fetch_fixtures] Invalid fixtures_list type: {type(fixtures_list)}")
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
            # Handle 401 - token expired
            if "401" in str(exc):
                try:
                    token_manager.refresh_token()
                except Exception as refresh_error:
                    print(f"[fetch_fixtures] Token refresh failed: {refresh_error}")
            else:
                print(f"[fetch_fixtures] Failed {year}-{month:02d}: {exc}")

        except Exception as exc:
            print(f"[fetch_fixtures] Failed {year}-{month:02d}: {exc}")

    if fixtures_to_save:
        save_fixtures(fixtures_to_save)

    return {
        "date_range": f"{start_date} → {end_date}",
        "months_checked": months_fetched,
        "fixtures_saved": len(fixtures_to_save),
    }


def save_fixtures(fixtures: list[FixtureRow]) -> None:
    """
    Save fixtures to the database.

    Maps API response format to database schema:
    - fixtureId → fixture_id
    - fixtureDate → fixture_date
    - courseName → course_name
    - meetingId → meeting_id
    - firstRace → first_race

    Missing fields are set to NULL or defaults.
    """
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


def _iter_months(start: date, end: date) -> Iterator[tuple[int, int]]:
    """Generate (year, month) tuples for each month in range."""
    year, month = start.year, start.month
    end_year, end_month = end.year, end.month

    while (year, month) <= (end_year, end_month):
        yield year, month
        month += 1
        if month > 12:
            year, month = year + 1, 1
