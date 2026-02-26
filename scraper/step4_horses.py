"""
Step 4: Fetch horse profiles.

Fetches missing horse profiles for animal_ids referenced by race performances.
"""

import time
from datetime import UTC, datetime
from typing import Any, TypedDict

from .config import API_BASE
from .db_tool import get_connection, get_pending_horse_ids, init_database, upsert_scrape_log
from .http_ops import fetch_json
from .token_manager import TokenManager


class HorseRow(TypedDict, total=False):
    animal_id: int
    racehorse_name: str
    name_no_country: str | None
    dob: str | None
    age: int | None
    moniker: str | None
    sex: str | None
    trainer: str | None
    total_wins: int
    total_runs: int
    total_places: int
    fetched_at: str
    processed: int


def _extract_horse_payload(payload: object, animal_id: int) -> dict[str, Any] | None:
    """Return the nested horse payload dict (payload['data'])."""
    if not isinstance(payload, dict):
        print(f"[step4] Invalid response type for horse {animal_id}: {type(payload)}")
        return None

    data = payload.get("data") or {}
    if not isinstance(data, dict):
        print(f"[step4] Invalid data type for horse {animal_id}: {type(data)}")
        return None

    return data


def _build_horse_row(animal_id: int, horse_data: dict[str, Any]) -> HorseRow:
    """Map API horse payload to a DB row."""
    performance_details = horse_data.get("performanceDetails") or []
    perf = performance_details[0] if isinstance(performance_details, list) and performance_details else {}

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


def fetch_horse_profiles(
        token_manager: TokenManager,
        limit: int = 100,
        per_horse_sleep_seconds: float = 0.2,
        retry_cooldown_minutes: int = 60,
        max_attempts: int = 5,
) -> dict[str, int]:
    """Fetch and persist missing horse profiles."""
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
            payload = _fetch_horse_with_401_retry(token_manager, url)

            horse_data = _extract_horse_payload(payload, animal_id)
            if horse_data is None:
                stats["horses_failed"] += 1
                with get_connection() as conn:
                    upsert_scrape_log(
                        conn,
                        "horse",
                        target_id,
                        status="failed",
                        error_message="Invalid response shape",
                        increment_attempt=True,
                    )
                continue

            horse_row = _build_horse_row(animal_id, horse_data)

            if not horse_row.get("animal_id"):
                stats["horses_failed"] += 1
                with get_connection() as conn:
                    upsert_scrape_log(
                        conn,
                        "horse",
                        target_id,
                        status="failed",
                        error_message="Missing animal_id after transform",
                        increment_attempt=True,
                    )
                continue

            save_horses([horse_row])
            stats["horses_saved"] += 1

            with get_connection() as conn:
                upsert_scrape_log(conn, "horse", target_id, status="completed", error_message=None)

        except RuntimeError as exc:
            msg = str(exc)

            if "404" in msg:
                stats["horses_not_found"] += 1
                with get_connection() as conn:
                    upsert_scrape_log(
                        conn,
                        "horse",
                        target_id,
                        status="not_found",
                        error_message=msg,
                        increment_attempt=True,
                    )
                continue

            stats["horses_failed"] += 1
            with get_connection() as conn:
                upsert_scrape_log(
                    conn,
                    "horse",
                    target_id,
                    status="failed",
                    error_message=msg,
                    increment_attempt=True,
                )
            continue

        except Exception as exc:
            stats["horses_failed"] += 1
            with get_connection() as conn:
                upsert_scrape_log(
                    conn,
                    "horse",
                    target_id,
                    status="failed",
                    error_message=f"Unexpected: {exc}",
                    increment_attempt=True,
                )
            continue

        finally:
            if per_horse_sleep_seconds > 0:
                time.sleep(per_horse_sleep_seconds)

    return stats


def _fetch_horse_with_401_retry(token_manager: TokenManager, url: str) -> dict[str, Any]:
    """Fetch horse profile, refreshing token once on 401."""
    token = token_manager.get_valid_token()
    try:
        payload = fetch_json(url, token)
        if isinstance(payload, dict):
            return payload
        return {"data": payload}
    except RuntimeError as exc:
        if "401" in str(exc):
            token_manager.refresh_token()
            token = token_manager.get_valid_token()
            payload = fetch_json(url, token)
            if isinstance(payload, dict):
                return payload
            return {"data": payload}
        raise


def save_horses(horses: list[HorseRow]) -> None:
    """Insert horse profiles into the horses table."""
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
                    h.get("processed", 1),
                )
                for h in horses
            ],
        )
