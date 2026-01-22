"""
Step 2: Fetch races for fixtures.

"""

from datetime import datetime
from typing import Any

from .config import API_BASE
from .db_tool import (
    get_connection,
    get_unprocessed_fixtures,
    mark_processed,
    validate_race_count,
)
from .http_ops import fetch_json
from .token_manager import TokenManager


def fetch_races_for_fixtures(token_manager: TokenManager, limit: int = 50, filters: dict = None) -> dict[str, int]:
    """
    Fetch races for unprocessed fixtures.

    Args:
        token_manager: TokenManager instance
        limit: Max fixtures to process per call
        filters: Dict with optional keys:
            - fixture_types: List of fixture types ["FLAT", "JUMP", "AWT"]
            - courses: List of course names ["Ascot", "Newmarket", ...]
    """
    stats = {
        "fixtures_checked": 0,
        "races_saved": 0,
        "fixtures_completed": 0,
        "validation_failures": 0,
    }

    # Get fixtures with filters applied
    with get_connection() as conn:
        fixtures_to_process = get_unprocessed_fixtures(
            conn,
            limit,
            fixture_types=filters.get("fixture_types") if filters else None,
            courses=filters.get("courses") if filters else None
        )

    if not fixtures_to_process:
        return stats

    for fixture in fixtures_to_process:
        stats["fixtures_checked"] += 1

        fixture_id = fixture["fixture_id"]
        fixture_date = fixture["fixture_date"]
        expected_races = fixture["number_of_races"]

        year = fixture_date.split("-")[0]
        url = API_BASE["races"].format(year=year, fixture_id=fixture_id)

        try:
            # Fetch from api
            token = token_manager.get_valid_token()
            data = fetch_json(url, token)

            # Extraction path
            raw_races = data.get("data") or []

            # Transform / normalize
            races = []
            for run in raw_races:
                races.append(
                    {
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
                        "fetched_at": datetime.now().isoformat(timespec="seconds"),
                        "processed": 0,
                        "sectioned": 0,
                        "horse_count": 0,
                    }
                )
            if races:
                save_races(races)
                stats["races_saved"] += len(races)

            # Validate count
            with get_connection() as conn:
                if validate_race_count(conn, fixture_id, expected_races):
                    mark_processed(conn, "fixtures", "fixture_id", fixture_id)
                    stats["fixtures_completed"] += 1
                else:
                    stats["validation_failures"] += 1
                    print(f"[step2] Race count mismatch for fixture {fixture_id}")

        except RuntimeError as e:
            if "401" in str(e):
                token_manager.refresh_token()
            print(f"[step2] Failed fixture {fixture_id}: {e}")
            continue

    return stats


def save_races(races: list[dict[str, Any]]) -> None:
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
                    r["race_id"],  # From API but required for our logic
                    r["fixture_id"],  # WE set this
                    r["division_sequence"],  # WE set default 0
                    r["race_date"],  # From API but required
                    r["race_time"],  # From API, could be None
                    r["age_limit"],  # From API, could be None
                    r["race_class"],  # From API, could be None
                    r["distance_value"],  # From API, could be None
                    r["distance_text"],  # From API, could be None
                    r["distance_change_text"],  # From API, could be None
                    r["race_criteria_type"],  # From API, could be None
                    r["fetched_at"],  # WE set this
                    r["processed"],  # WE set this to 0
                    r["sectioned"],
                    r["horse_count"],
                )
                for r in races
            ],
        )