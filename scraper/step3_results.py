"""
Step 3: Fetch race results.
"""

from datetime import datetime

from .config import API_BASE
from .db_tool import get_connection, get_unprocessed_races, mark_processed
from .http_ops import fetch_json
from .token_manager import TokenManager

def fetch_results_for_races(
    token_manager: TokenManager, limit: int = 100, filters: dict = None
) -> dict[str, int]:
    """
    Query for races needing results.

    Args:
        token_manager: TokenManager instance
        limit: Max races to process per call
        filters: Dict with optional keys:
            - race_type: "FLAT" or "JUMP"
            - minimum_distance: Minimum distance in meters
            - maximum_distance: Maximum distance in meters
            - race_classes: List of race classes [1, 2, 3, ...]
    """
    with get_connection() as conn:
        races = get_unprocessed_races(conn, limit, race_filters=filters if filters else None)

    stats = {
        "races_checked": 0,
        "results_saved": 0,
        "races_completed": 0,
    }

    if not races:
        return stats

    for race in races:
        stats["races_checked"] += 1

        race_id = race["race_id"]
        race_date = race["race_date"]
        division = race["division_sequence"]

        year = race_date.split("-")[0]
        url = API_BASE["results"].format(year=year, race_id=race_id, division=division)

        try:
            token = token_manager.get_valid_token()
            response = fetch_json(url, token)

            raw_performances = response.get("data", [])

            performances = [transform_performance(p, race_id) for p in raw_performances]

            if performances:
                save_performances(performances)
                stats["results_saved"] += len(performances)

                # Update horse count for this race
                update_horse_count(race_id, len(performances))

            with get_connection() as conn:
                mark_processed(conn, "races", "race_id", race_id)
            stats["races_completed"] += 1

        except RuntimeError as e:
            if "401" in str(e):
                token_manager.refresh_token()
            print(f"[Step3] Failed race {race_id}: {e}")
            continue

    return stats

def transform_performance(raw, race_id):
    """Transform API performance data to database format."""
    return {
        "race_id": race_id,
        "animal_id": raw.get("animalId"),
        "division_sequence": raw.get("divisionSequence"),
        "result_position": raw.get("resultFinishPos"),
        "status": raw.get("status"),
        "horse_name": raw.get("racehorseName"),
        "cloth_number": raw.get("clothNumber"),
        "drawn_stall": raw.get("drawnStall"),
        "reserve_no": raw.get("reserveNoOfEntry"),
        "trainer_name": raw.get("trainerName"),
        "jockey_name": raw.get("jockeyName"),
        "sex": raw.get("sex"),
        "age": raw.get("age"),
        "primary_color": raw.get("primaryColourDescription"),
        "position_time": raw.get("positionFinishTime"),
        "is_runner": raw.get("runner"),
        "final_position": raw.get("finalPosition"),
        "race_criteria_type": raw.get("raceCriteriaRaceType"),
        "finish_time": raw.get("finishTime"),
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "processed": 0,
    }

def save_performances(performances):
    """Save race performances to database."""
    if not performances:
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
                    p.get("performance_id"),
                    p["race_id"],
                    p["animal_id"],
                    p["division_sequence"],
                    p["result_position"],
                    p["status"],
                    p["horse_name"],
                    p["cloth_number"],
                    p["drawn_stall"],
                    p["reserve_no"],
                    p["trainer_name"],
                    p["jockey_name"],
                    p["sex"],
                    p["age"],
                    p["primary_color"],
                    p["position_time"],
                    p["is_runner"],
                    p["final_position"],
                    p["race_criteria_type"],
                    p["finish_time"],
                    p["fetched_at"],
                    p["processed"],
                )
                for p in performances
            ],
        )

def update_horse_count(race_id, count):
    """Update horse_count for a race after saving performances."""
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE races
            SET horse_count = ?
            WHERE race_id = ?
            """,
            (count, race_id),
        )

