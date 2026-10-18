"""
Step 2: Fetch races for fixtures.

This step retrieves race data for fixtures stored in the database.

Pipeline role:
    Step 1 → fixtures
    Step 2 → races (THIS FILE)
    Step 3 → results
    Step 4 → horses
    Step 5 → sectionals

Behavior:
- Pulls unprocessed fixtures from DB
- Calls API for each fixture
- Extracts race list
- Saves races to DB
- Marks fixture as processed

Key design decisions:
✔ Uses fetch_with_retry() for ALL HTTP calls
✔ Relies on global RateLimiter (passed from service)
✔ No internal retry loops (delegated to HTTP layer)
✔ Safe payload validation
✔ Idempotent DB writes (INSERT OR REPLACE)

This step is lightweight and should be fast compared to later steps.
"""

from datetime import UTC, datetime
from typing import Any

from .config import API_BASE
from .db_tool import get_connection, get_unprocessed_fixtures, mark_processed
from .http_ops import fetch_with_retry
from .rate_limiter import RateLimiter
from .schemas import FixtureFilters, RaceRow
from .token_manager import TokenManager
from .utils import warn

# =========================================================
# 🔹 HELPERS
# =========================================================


def _build_races_url(fixture_date: str, fixture_id: int) -> str:
    """Construct API endpoint for fixture races."""
    year = fixture_date.split("-")[0]
    return API_BASE["races"].format(year=year, fixture_id=fixture_id)


def _extract_races_list(payload: object, fixture_id: int) -> list[dict[str, Any]] | None:
    """Validate the API response and extract a race list."""
    if not isinstance(payload, dict):
        warn(
            "step2_invalid_response_type",
            fixture_id=fixture_id,
            response_type=type(payload).__name__,
        )
        return None

    raw = payload.get("data") or []

    if not isinstance(raw, list):
        warn("step2_invalid_races_list", fixture_id=fixture_id, response_type=type(raw).__name__)
        return None

    return [r for r in raw if isinstance(r, dict)]


def _build_race_row(raw: dict[str, Any], fixture_id: int) -> RaceRow:
    """Transform a raw API race payload into a DB row."""
    return {
        "race_id": raw.get("raceId"),
        "fixture_id": fixture_id,
        "division_sequence": raw.get("divisionSequence", 0),
        "race_date": raw.get("raceDate"),
        "race_time": raw.get("raceTime"),
        "age_limit": raw.get("ageLimit"),
        "race_class": raw.get("raceClass"),
        "distance_value": raw.get("distanceValue"),
        "distance_text": raw.get("distanceText"),
        "distance_change_text": raw.get("distanceChangeText"),
        "race_criteria_type": raw.get("raceCriteriaRaceType"),
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "processed": 0,
        "sectioned": 0,
        "horse_count": 0,
    }


# =========================================================
# 🔹 MAIN ENTRY
# =========================================================


def fetch_races_for_fixtures(
    token_manager: TokenManager,
    limit: int = 50,
    filters: FixtureFilters | None = None,
    rate_limiter: RateLimiter | None = None,
) -> dict[str, int]:
    """
    Fetch races for unprocessed fixtures.

    Args:
        token_manager: authentication handler
        limit: max fixtures per batch
        filters: optional fixture filters
        rate_limiter: global rate limiter (REQUIRED)

    Returns:
        stats dict
    """

    if rate_limiter is None:
        raise ValueError("RateLimiter must be provided")

    stats = {"fixtures_checked": 0, "races_saved": 0, "fixtures_completed": 0}

    # =====================================================
    # 🔹 LOAD FIXTURES
    # =====================================================
    with get_connection() as conn:
        fixtures = get_unprocessed_fixtures(
            conn,
            limit,
            fixture_types=filters.get("fixture_types") if filters else None,
            courses=filters.get("courses") if filters else None,
        )

    if not fixtures:
        return stats

    # =====================================================
    # 🔹 PROCESS FIXTURES
    # =====================================================
    for fixture in fixtures:
        stats["fixtures_checked"] += 1

        fixture_id = fixture["fixture_id"]
        fixture_date = fixture["fixture_date"]

        url = _build_races_url(fixture_date, fixture_id)

        try:
            # 🌐 unified HTTP layer
            payload = fetch_with_retry(
                url=url, token_manager=token_manager, rate_limiter=rate_limiter
            )

            raw_races = _extract_races_list(payload, fixture_id)

            if raw_races is None:
                continue

            race_rows = [_build_race_row(raw, fixture_id) for raw in raw_races]

            # 💾 SAVE
            if race_rows:
                save_races(race_rows)
                stats["races_saved"] += len(race_rows)

            # ✅ mark fixture processed
            with get_connection() as conn:
                mark_processed(conn, "fixtures", "fixture_id", fixture_id)

            stats["fixtures_completed"] += 1

        except RuntimeError as exc:
            warn("step2_fixture_failed", fixture_id=fixture_id, error=str(exc))

            continue

    return stats


# =========================================================
# 🔹 DB WRITE
# =========================================================


def save_races(races: list[RaceRow]) -> None:
    """Persist race rows to the database."""
    if not races:
        return

    with get_connection() as conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO races (
                race_id,
                fixture_id,
                division_sequence,
                race_date,
                race_time,
                age_limit,
                race_class,
                distance_value,
                distance_text,
                distance_change_text,
                race_criteria_type,
                fetched_at,
                processed,
                sectioned,
                horse_count
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    r["race_id"],
                    r["fixture_id"],
                    r["division_sequence"],
                    r["race_date"],
                    r["race_time"],
                    r["age_limit"],
                    r["race_class"],
                    r["distance_value"],
                    r["distance_text"],
                    r["distance_change_text"],
                    r["race_criteria_type"],
                    r["fetched_at"],
                    r["processed"],
                    r["sectioned"],
                    r["horse_count"],
                )
                for r in races
            ],
        )
