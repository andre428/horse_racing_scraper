"""
Step 4: Horse profiles.

Pipeline role:
    Step 1 → fixtures
    Step 2 → races
    Step 3 → results
    Step 4 → horses (THIS FILE)
    Step 5 → sectionals

Behavior:
- Selects pending animal_ids from the DB and fetches BHA horse payloads.
- Writes rows to `horses` and tracks attempts in `scrape_log`.

Key design decisions:
✔ Uses fetch_with_retry() for ALL HTTP calls
✔ Relies on global RateLimiter (passed from service)
✔ No step-level filters (operates on data already narrowed by earlier steps)
✔ Idempotent inserts; 404 and other failures recorded without aborting the batch
"""

from datetime import UTC, datetime
from typing import Any

from .config import API_BASE
from .db_tool import get_connection, get_pending_horse_ids, init_database, upsert_scrape_log
from .http_ops import fetch_with_retry
from .rate_limiter import RateLimiter
from .schemas import HorseRow
from .token_manager import TokenManager
from .utils import warn

# =========================================================
# 🔹 HELPERS
# =========================================================


def _extract_horse_payload(payload: object, animal_id: int) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        warn(
            "step4_invalid_response_type", animal_id=animal_id, response_type=type(payload).__name__
        )
        return None

    data = payload.get("data") or {}
    if not isinstance(data, dict):
        warn("step4_invalid_data_type", animal_id=animal_id, response_type=type(data).__name__)
        return None

    return data


def _build_horse_row(animal_id: int, horse_data: dict[str, Any]) -> HorseRow:
    performance_details = horse_data.get("performanceDetails") or []
    perf = (
        performance_details[0]
        if isinstance(performance_details, list) and performance_details
        else {}
    )

    return {
        "animal_id": animal_id,
        "racehorse_name": horse_data.get("name") or "",
        "name_no_country": horse_data.get("nameWithNoCountry"),
        "dob": horse_data.get("dateOfBirth"),
        "age": horse_data.get("age"),
        "moniker": horse_data.get("moniker"),
        "sex": horse_data.get("sex"),
        "trainer": horse_data.get("trainerName"),
        "total_wins": perf.get("totalWins", 0),
        "total_runs": perf.get("totalRuns", 0),
        "total_places": perf.get("totalPlaces", 0),
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "processed": 1,
    }


# =========================================================
# 🔹 MAIN ENTRY
# =========================================================


def fetch_horse_profiles(
    token_manager: TokenManager,
    limit: int = 100,
    retry_cooldown_minutes: int = 60,
    max_attempts: int = 5,
    filters: dict | None = None,
    rate_limiter: RateLimiter | None = None,
) -> dict[str, int]:
    # Reserved for ScraperService._run_batched uniform kwargs; step 4 does not filter.
    _ = filters

    if rate_limiter is None:
        raise ValueError("RateLimiter is required for Step 4")

    init_database()

    stats = {
        "horses_checked": 0,
        "horses_saved": 0,
        "horses_failed": 0,
        "horses_not_found": 0,
        "horses_skipped": 0,
    }

    with get_connection() as conn:
        animal_ids = get_pending_horse_ids(
            conn,
            limit=limit,
            retry_cooldown_minutes=retry_cooldown_minutes,
            max_attempts=max_attempts,
        )

    if not animal_ids:
        return stats

    for animal_id in animal_ids:
        stats["horses_checked"] += 1

        target_id = str(animal_id)
        url = API_BASE["horses"].format(animal_id=animal_id)

        with get_connection() as conn:
            upsert_scrape_log(conn, "horse", target_id, status="running", error_message=None)

        try:
            payload = fetch_with_retry(
                url=url, token_manager=token_manager, rate_limiter=rate_limiter
            )

            horse_data = _extract_horse_payload(payload, animal_id)
            if horse_data is None:
                raise RuntimeError("Invalid response shape (Step4)")

            horse_row = _build_horse_row(animal_id, horse_data)

            if not horse_row.get("animal_id"):
                raise RuntimeError("Missing animal_id after transform")

            save_horses([horse_row])
            stats["horses_saved"] += 1

            with get_connection() as conn:
                upsert_scrape_log(conn, "horse", target_id, status="completed", error_message=None)

        except RuntimeError as exc:
            msg = str(exc)

            if "404" in msg:
                stats["horses_not_found"] += 1

                status = "not_found"

            else:
                stats["horses_failed"] += 1

                status = "failed"

                warn("step4_horse_failed", animal_id=animal_id, error=msg)

            with get_connection() as conn:
                upsert_scrape_log(
                    conn,
                    "horse",
                    target_id,
                    status=status,
                    error_message=msg,
                    increment_attempt=True,
                )

        except Exception as exc:
            stats["horses_failed"] += 1

            warn("step4_horse_unexpected_error", animal_id=animal_id, error=str(exc))

            with get_connection() as conn:
                upsert_scrape_log(
                    conn,
                    "horse",
                    target_id,
                    status="failed",
                    error_message=f"Unexpected: {exc}",
                    increment_attempt=True,
                )

    return stats


# =========================================================
# 🔹 DB WRITE
# =========================================================


def save_horses(horses: list[HorseRow]) -> None:
    if not horses:
        return

    with get_connection() as conn:
        conn.executemany(
            """INSERT OR REPLACE INTO horses(
                animal_id, racehorse_name, name_no_country,
                dob, age, moniker, sex, trainer,
                total_wins, total_runs, total_places,
                fetched_at, processed
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    h["animal_id"],
                    h["racehorse_name"],
                    h.get("name_no_country"),
                    h.get("dob"),
                    h.get("age"),
                    h.get("moniker"),
                    h.get("sex"),
                    h.get("trainer"),
                    h.get("total_wins", 0),
                    h.get("total_runs", 0),
                    h.get("total_places", 0),
                    h["fetched_at"],
                    h["processed"],
                )
                for h in horses
            ],
        )
