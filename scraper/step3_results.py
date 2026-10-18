"""
Step 3: Fetch race results.

Pipeline role:
    Step 1 → fixtures
    Step 2 → races
    Step 3 → results (THIS FILE)
    Step 4 → horses
    Step 5 → sectionals

Behavior:
- Pulls unprocessed races from DB
- Applies race-level filters while selecting races
- Calls API for each race/division
- Extracts race performance rows
- Saves performances to DB
- Updates race horse counts
- Marks races as processed

Key design decisions:
✔ Uses fetch_with_retry() for ALL HTTP calls
✔ Relies on global RateLimiter (passed from service)
✔ No internal retry loops (delegated to HTTP layer)
✔ Safe payload validation
✔ Idempotent DB writes (INSERT OR REPLACE)

This step is the bridge between race metadata and downstream horse/profile work.
"""

from datetime import UTC, datetime
from typing import Any

from .config import API_BASE
from .db_tool import get_connection, get_unprocessed_races, mark_processed
from .http_ops import fetch_with_retry
from .rate_limiter import RateLimiter
from .schemas import PerformanceRow, RaceFilters
from .token_manager import TokenManager
from .utils import warn

# =========================================================
# 🔹 HELPERS
# =========================================================


def _build_results_url(race_date: str, race_id: int, division: int) -> str:
    year = race_date.split("-")[0]
    return API_BASE["results"].format(year=year, race_id=race_id, division=division)


def _extract_raw_performances(payload: object, race_id: int) -> list[dict[str, Any]] | None:
    if not isinstance(payload, dict):
        warn("step3_invalid_response_type", race_id=race_id, response_type=type(payload).__name__)
        return None

    raw = payload.get("data") or []
    if not isinstance(raw, list):
        warn("step3_invalid_performances_list", race_id=race_id, response_type=type(raw).__name__)
        return None

    return [p for p in raw if isinstance(p, dict)]


def _transform_performance(raw: dict[str, Any], race_id: int) -> PerformanceRow:
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


# =========================================================
# 🔹 MAIN FUNCTION
# =========================================================


def fetch_results_for_races(
    token_manager: TokenManager,
    limit: int = 100,
    filters: RaceFilters | None = None,
    rate_limiter: RateLimiter | None = None,
) -> dict[str, int]:
    if rate_limiter is None:
        raise ValueError("RateLimiter is required for Step 3")

    stats = {"races_checked": 0, "results_saved": 0, "races_completed": 0}

    with get_connection() as conn:
        races = get_unprocessed_races(conn, limit, race_filters=filters)

    if not races:
        return stats

    for race in races:
        stats["races_checked"] += 1

        race_id = race["race_id"]
        race_date = race["race_date"]
        division = race["division_sequence"]

        url = _build_results_url(race_date, race_id, division)

        try:
            payload = fetch_with_retry(
                url=url, token_manager=token_manager, rate_limiter=rate_limiter
            )

            raw_performances = _extract_raw_performances(payload, race_id)
            if raw_performances is None:
                continue

            performances = [_transform_performance(p, race_id) for p in raw_performances]

            if performances:
                save_performances(performances)
                stats["results_saved"] += len(performances)
                update_horse_count(race_id, len(performances))

            with get_connection() as conn:
                mark_processed(conn, "races", "race_id", race_id)

            stats["races_completed"] += 1

        except RuntimeError as exc:
            warn("step3_race_failed", race_id=race_id, error=str(exc))

            continue

    return stats


# =========================================================
# 🔹 DB HELPERS
# =========================================================


def save_performances(performances: list[PerformanceRow]) -> None:
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
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE races
            SET horse_count = ?
            WHERE race_id = ?
            """,
            (count, race_id),
        )
