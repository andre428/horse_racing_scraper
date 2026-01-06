"""
Step 1: Fetch fixtures for one or multiple dates.

# The fixtures API is month-based and does NOT support server-side filtering.
# All filtering here is client-side by design.
"""

from datetime import date, datetime

from .config import API_BASE
from .db_tool import get_connection, init_database
from .http_ops import fetch_json
from .token_manager import TokenManager


def fetch_fixtures_range(token_manager: TokenManager, start_date: str | None = None, end_date: str | None = None,
                         filters: dict[str, str | int] | None = None) -> dict[str, str | int]:
    """
    Fetch fixtures for date range and save to database.

    Returns summary dict with counts.
    """
    if token_manager is None:
        raise ValueError("token_manager is required")

    init_database()

    start_dt = datetime.fromisoformat(start_date).date() if start_date else date.today()
    end_dt = datetime.fromisoformat(end_date).date() if end_date else start_dt

    fixtures_to_save = []
    months_fetched = 0

    for year, month in _iter_months(start_dt, end_dt):
        url = API_BASE["fixtures"].format(month=month, year=year)
        months_fetched += 1

        try:
            # Get valid token
            token = token_manager.get_valid_token()

            # Make authenticated request
            payload = fetch_json(url, token)

            # Validate response
            if not isinstance(payload, dict):
                print(f"[fetch_fixtures] Invalid response type: {type(payload)}")
                continue

            fixtures_list = payload.get("data") or payload.get("fixtures") or []

            if not isinstance(fixtures_list, list):
                print(f"[fetch_fixtures] Invalid fixtures_list type: {type(fixtures_list)}")
                continue

            # Filter to date range
            for item in fixtures_list:
                fixture_date = item.get("fixtureDate")
                if not fixture_date:
                    continue

                try:
                    fixture_dt = datetime.fromisoformat(fixture_date).date()
                except ValueError:
                    continue

                # Date filter
                if not (start_dt <= fixture_dt <= end_dt):
                    continue

                # Fixture type filter
                if filters and "fixture_types" in filters:
                    if item.get("fixtureType") not in filters["fixture_types"]:
                        continue

                # Course filter
                if filters and "courses" in filters:
                    if item.get("courseName") not in filters["courses"]:
                        continue

                # All filters passed → save
                fixtures_to_save.append(
                    {
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
                        "fetched_at": datetime.now().isoformat(timespec="seconds"),
                        "processed": 0,
                    }
                )
        except RuntimeError as e:
            # Handle 401 - token expired
            if "401" in str(e):
                print("[fetch_fixtures] Token expired, refreshing...")
                try:
                    token_manager.refresh_token()
                    # Retry this month
                    # (Could make this more sophisticated)
                except Exception as refresh_error:
                    print(f"[fetch_fixtures] Token refresh failed: {refresh_error}")
            else:
                print(f"[fetch_fixtures] Failed {year}-{month:02d}: {e}")
            continue

        except Exception as exc:
            print(f"[fetch_fixtures] Failed {year}-{month:02d}: {exc}")
        continue

    if fixtures_to_save:
        save_fixtures(fixtures_to_save)

    return {
        "date_range": f"{start_date} → {end_date}",
        "months_checked": months_fetched,
        "fixtures_saved": len(fixtures_to_save),
    }


def save_fixtures(fixtures: list[dict[str, str | int]]) -> None:
    """
    Save fixtures to database.

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
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    f.get("processed"),
                )
                for f in fixtures
            ],
        )


def find_fixtures_with_incomplete_races(
        start_date: str,
        end_date: str,
) -> list[dict[str, str | int]]:
    """
    Find fixtures where the expected number_of_races does not match
    the number of races stored in the ``races`` table.

    This is a diagnostic/helper function that can be used:
    - after Step 2 to verify completeness of race data
    - before Step 3 to avoid requesting results for incomplete fixtures

    Args:
        start_date: Inclusive start date in ``YYYY-MM-DD`` format.
        end_date: Inclusive end date in ``YYYY-MM-DD`` format.

    Returns:
        List of dicts with keys:
            - fixtureId
            - fixtureDate
            - expectedRaces   (number_of_races from fixtures table, may be NULL)
            - actualRaces     (COUNT(*) from races table)
    """
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT
                f.fixture_id,
                f.fixture_date,
                f.number_of_races AS expected_races,
                COUNT(r.race_id) AS actual_races
            FROM fixtures f
            LEFT JOIN races r
                ON r.fixture_id = f.fixture_id
            WHERE f.fixture_date BETWEEN ? AND ?
            GROUP BY
                f.fixture_id,
                f.fixture_date,
                f.number_of_races
            HAVING
                -- Either number_of_races is known and doesn't match,
                -- or number_of_races IS NULL but there are races present.
                (expected_races IS NOT NULL AND expected_races != actual_races)
                OR (expected_races IS NULL AND actual_races > 0)
            ORDER BY f.fixture_date, f.fixture_id
            """,
            (start_date, end_date),
        )
        rows = cursor.fetchall()

        return [
            {
                "fixtureId": row["fixture_id"],
                "fixtureDate": row["fixture_date"],
                "expectedRaces": row["expected_races"],
                "actualRaces": row["actual_races"],
            }
            for row in rows
        ]


def _iter_months(start: date, end: date):
    """Generate (year, month) tuples for each month in range."""
    year, month = start.year, start.month
    end_year, end_month = end.year, end.month

    while (year, month) <= (end_year, end_month):
        yield year, month
        month += 1
        if month > 12:
            year, month = year + 1, 1