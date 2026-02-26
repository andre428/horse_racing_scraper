"""
Step 2: Fetch races for fixtures.

"""
from datetime import UTC, datetime
from typing import Any, TypedDict

from .config import API_BASE
from .db_tool import (
    get_connection,
    get_unprocessed_fixtures,
    mark_processed,
)
from .http_ops import fetch_json
from .token_manager import TokenManager


class FixtureFilters(TypedDict, total=False):
    fixture_types: list[str]
    courses: list[str]


class RaceRow(TypedDict):
    race_id: int | None
    fixture_id: int
    division_sequence: int
    race_date: str | None
    race_time: str | None
    age_limit: str | None
    race_class: int | None
    distance_value: int | None
    distance_text: str | None
    distance_change_text: str | None
    race_criteria_type: Any
    fetched_at: str
    processed: int
    sectioned: int
    horse_count: int


def _build_races_url(fixture_date: str, fixture_id: int) -> str:
    year = fixture_date.split("-")[0]
    return API_BASE["races"].format(year=year, fixture_id=fixture_id)


def _extract_races_list(payload: object, fixture_id: int) -> list[dict[str, Any]] | None:
    """
    Validate response shape and return the list of raw races.
    Returns None if the payload is unusable.
    """
    if not isinstance(payload, dict):
        print(f"[step2] Invalid response type for fixture {fixture_id}: {type(payload)}")
        return None

    raw_races = payload.get("data") or []
    if not isinstance(raw_races, list):
        print(f"[step2] Invalid races list type for fixture {fixture_id}: {type(raw_races)}")
        return None

    # Keep only dict entries
    return [r for r in raw_races if isinstance(r, dict)]


def _build_race_row(run: dict[str, Any], fixture_id: int) -> RaceRow:
    return {
        "race_id": run.get("raceId"),
        "fixture_id": fixture_id,
        "division_sequence": run.get("divisionSequence", 0),
        "race_date": run.get("raceDate"),
        "race_time": run.get("raceTime"),
        "age_limit": run.get("ageLimit"),
        "race_class": run.get("raceClass"),
        "distance_value": run.get("distanceValue"),
        "distance_text": run.get("distanceText"),
        "distance_change_text": run.get("distanceChangeText"),
        "race_criteria_type": run.get("raceCriteriaRaceType"),
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "processed": 0,
        "sectioned": 0,
        "horse_count": 0,
    }


def fetch_races_for_fixtures(
        token_manager: TokenManager,
        limit: int = 50,
        filters: FixtureFilters | None = None,
) -> dict[str, int]:
    """
    Fetch races for unprocessed fixtures.
    """
    stats = {
        "fixtures_checked": 0,
        "races_saved": 0,
        "fixtures_completed": 0,
    }

    with get_connection() as conn:
        fixtures_to_process = get_unprocessed_fixtures(
            conn,
            limit,
            fixture_types=filters.get("fixture_types") if filters else None,
            courses=filters.get("courses") if filters else None,
        )

    if not fixtures_to_process:
        return stats

    race_done_counter = 0

    for fixture in fixtures_to_process:
        stats["fixtures_checked"] += 1

        fixture_id = fixture["fixture_id"]
        fixture_date = fixture["fixture_date"]

        url = _build_races_url(fixture_date, fixture_id)

        try:
            token = token_manager.get_valid_token()
            payload = fetch_json(url, token)

            raw_races = _extract_races_list(payload, fixture_id)
            if raw_races is None:
                continue

            races = [_build_race_row(run, fixture_id) for run in raw_races]

            for _ in races:
                race_done_counter += 1
                print(f"race done {race_done_counter}")

            if races:
                save_races(races)
                stats["races_saved"] += len(races)

            with get_connection() as conn:
                mark_processed(conn, "fixtures", "fixture_id", fixture_id)
            stats["fixtures_completed"] += 1

        except RuntimeError as exc:
            if "401" in str(exc):
                token_manager.refresh_token()
            print(f"[step2] Failed fixture {fixture_id}: {exc}")
            continue

    return stats


def save_races(races: list[RaceRow]) -> None:
    """Save races to DB with a fixture_id reference."""
    if not races:
        return

    with get_connection() as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO races
            (race_id, fixture_id, division_sequence, race_date, race_time, age_limit,
            race_class, distance_value, distance_text, distance_change_text,
            race_criteria_type, fetched_at, processed, sectioned, horse_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
