"""
Step 3: Fetch race results.
"""

from datetime import UTC, datetime
from typing import Any, TypedDict

from .config import API_BASE
from .db_tool import get_connection, get_unprocessed_races, mark_processed
from .http_ops import fetch_json
from .token_manager import TokenManager


class RaceFilters(TypedDict, total=False):
    race_type: str
    minimum_distance: int
    maximum_distance: int
    race_classes: list[int]


class PerformanceRow(TypedDict, total=False):
    performance_id: int
    race_id: int
    animal_id: int | None
    division_sequence: int | None
    result_position: int | None
    status: int | None
    horse_name: str | None
    cloth_number: str | None
    drawn_stall: int | None
    reserve_no: int | None
    trainer_name: str | None
    jockey_name: str | None
    sex: str | None
    age: str | None
    primary_color: Any
    position_time: str | None
    is_runner: Any
    final_position: str | None
    race_criteria_type: Any
    finish_time: str | None
    fetched_at: str
    processed: int


def _build_results_url(race_date: str, race_id: int, division: int) -> str:
    year = race_date.split("-")[0]
    return API_BASE["results"].format(year=year, race_id=race_id, division=division)


def _extract_raw_performances(payload: object, race_id: int) -> list[dict[str, Any]] | None:
    if not isinstance(payload, dict):
        print(f"[Step3] Invalid response type for race {race_id}: {type(payload)}")
        return None

    raw = payload.get("data") or []
    if not isinstance(raw, list):
        print(f"[Step3] Invalid performances list type for race {race_id}: {type(raw)}")
        return None

    return [raw_performance for raw_performance in raw if isinstance(raw_performance, dict)]


def transform_performance(raw: dict[str, Any], race_id: int) -> PerformanceRow:
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
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "processed": 0,
    }


def fetch_results_for_races(
        token_manager: TokenManager,
        limit: int = 100,
        filters: RaceFilters | None = None,
) -> dict[str, int]:
    """
    Query for races needing results.
    """
    with get_connection() as conn:
        races = get_unprocessed_races(conn, limit, race_filters=filters)

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

        url = _build_results_url(race_date, race_id, division)

        try:
            token = token_manager.get_valid_token()
            payload = fetch_json(url, token)

            raw_performances = _extract_raw_performances(payload, race_id)
            if raw_performances is None:
                continue

            performances = [transform_performance(p, race_id) for p in raw_performances]

            if performances:
                save_performances(performances)
                stats["results_saved"] += len(performances)
                update_horse_count(race_id, len(performances))

            with get_connection() as conn:
                mark_processed(conn, "races", "race_id", race_id)
            stats["races_completed"] += 1

        except RuntimeError as exc:
            if "401" in str(exc):
                token_manager.refresh_token()
            print(f"[Step3] Failed race {race_id}: {exc}")
            continue

    return stats


def save_performances(performances: list[PerformanceRow]) -> None:
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
                    p.get("animal_id"),
                    p.get("division_sequence"),
                    p.get("result_position"),
                    p.get("status"),
                    p.get("horse_name"),
                    p.get("cloth_number"),
                    p.get("drawn_stall"),
                    p.get("reserve_no"),
                    p.get("trainer_name"),
                    p.get("jockey_name"),
                    p.get("sex"),
                    p.get("age"),
                    p.get("primary_color"),
                    p.get("position_time"),
                    p.get("is_runner"),
                    p.get("final_position"),
                    p.get("race_criteria_type"),
                    p.get("finish_time"),
                    p["fetched_at"],
                    p["processed"],
                )
                for p in performances
            ],
        )


def update_horse_count(race_id: int, count: int) -> None:
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
