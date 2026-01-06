"""
Step 3: Fetch race results and export to CSV.

Given a list of race dicts (from Step 2), fetch each race result via:
  /bha/v1/races/{year}/{race_id}/{division}/results

1. Query DB for races WHERE processed = 0
2. For each race:
   a. Extract race_id and year from race_date
   b. Build URL: /bha/v1/races/{year}/{race_id}/0/results
   c. Fetch results with token
   d. Parse performances array
   e. Save to race_performances table (with race_id reference)
   f. Mark race as processed = 1
3. Return summary stats

# Extract year from race_date
year = race_date.split("-")[0]  # "2025-12-08" → "2025"

# Build URL
url = API_BASE["results"].format(year=year, race_id=race_id, division=division_sequence)
# Result: .../bha/v1/races/2025/66431/0/results
"""

from datetime import datetime

from .config import API_BASE
from .db_tool import get_connection, get_unprocessed_races, mark_processed
from .http_ops import fetch_json
from .token_manager import TokenManager


def fetch_results_for_races(token_manager: TokenManager, limit: int = 100, filters: dict = None) -> dict[str, int]:
    """
    Query for races needing results.

    Args:
        token_manager: TokenManager instance
        limit: Max races to process per call
        filters: Dict with optional keys:
            - race_type: "FLAT" or "JUMP"
            - min_distance: Minimum distance in meters
            - max_distance: Maximum distance in meters
            - race_classes: List of race classes [1, 2, 3, ...]
    """
    # Get races with filters applied
    with get_connection() as conn:
        races = get_unprocessed_races(
            conn,
            limit,
            race_filters=filters if filters else None
        )

    stats = {
        "races_checked": 0,
        "results_saved": 0,
        "races_completed": 0,
    }

    for race in races:
        stats["races_checked"] += 1

        # Extract
        race_id = race["race_id"]
        race_date = race["race_date"]
        division = race["division_sequence"]

        year = race_date.split("-")[0]
        url = API_BASE["results"].format(year=year, race_id=race_id, division=division)

        try:
            token = token_manager.get_valid_token()
            data = fetch_json(url, token)

            raw_result = data.get("data") or []

            results = []
            for result in raw_result:
                results.append(
                    {
                        "race_id": result.get("raceId"),
                        "animal_id": result.get("animalId"),
                        "division_sequence": result.get("divisionSequence"),
                        "result_position": result.get("resultFinishPos"),
                        "status": result.get("status"),
                        "horse_name": result.get("racehorseName"),
                        "cloth_number": result.get("clothNumber"),
                        "drawn_stall": result.get("drawnStall"),
                        "reserve_no": result.get("reserveNoOfEntry"),
                        "trainer_name": result.get("trainerName"),
                        "jockey_name": result.get("jockeyName"),
                        "sex": result.get("sex"),
                        "age": result.get("age"),
                        "primary_color": result.get("primaryColourDescription"),
                        "position_time": result.get("positionFinishTime"),
                        "is_runner": result.get("runner"),
                        "final_position": result.get("finalPosition"),
                        "race_criteria_type": result.get("raceCriteriaRaceType"),
                        "finish_time": result.get("finishTime"),
                        "fetched_at": datetime.now().isoformat(timespec="seconds"),
                        "processed": 0,
                    }
                )
            if results:
                save_results(results, race_id)
                stats["results_saved"] += len(results)

            with get_connection() as conn:
                mark_processed(conn, "races", "race_id", race_id)
            stats["races_completed"] += 1

        except RuntimeError as exc:
            if "401" in str(exc):
                token_manager.refresh_token()

            print(f"[step3_results] Error fetching races for fixture {race_id}: {exc!s}")
            continue

    return stats


def save_results(results: list[dict[str, str | int]], race_id: int) -> None:
    """Save results for a race."""
    if not results:
        return

    with get_connection() as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO race_performances
               (performance_id, race_id, animal_id, division_sequence, result_position,
               status, horse_name, cloth_number, drawn_stall, reserve_no, trainer_name,
               jockey_name, sex, age, primary_color, position_time, is_runner, final_position,
               race_criteria_type, finish_time, fetched_at, processed)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    r.get("performance_id"),  # Optional, might not be in API response
                    race_id,  # WE pass this as parameter
                    r["animal_id"],  # Required from API
                    r["division_sequence"],  # From API, could be None
                    r["result_position"],  # From API, could be None
                    r["status"],  # From API, could be None
                    r["horse_name"],  # From API, could be None
                    r["cloth_number"],  # From API, could be None
                    r["drawn_stall"],  # From API, could be None
                    r["reserve_no"],  # From API, could be None
                    r["trainer_name"],  # From API, could be None
                    r["jockey_name"],  # From API, could be None
                    r["sex"],  # FIXED: was r.get("sex,")
                    r["age"],  # FIXED: was r.get("age,")
                    r["primary_color"],  # From API, could be None
                    r["position_time"],  # From API, could be None
                    r["is_runner"],  # From API, could be None
                    r["final_position"],  # From API, could be None
                    r["race_criteria_type"],  # From API, could be None
                    r["finish_time"],  # From API, could be None
                    r["fetched_at"],  # WE set this
                    r["processed"]  # WE set this to 0
                )
                for r in results
            ],
        )