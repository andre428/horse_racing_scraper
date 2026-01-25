"""
Step 4: Fetch horse profiles.

Fetches detailed horse data for unique animal_ids from race performances.
"""

from datetime import datetime

from .config import API_BASE
from .db_tool import get_connection, get_unscraped_horses
from .http_ops import fetch_json
from .token_manager import TokenManager


# TODO - add filters keyword!

def fetch_horse_profiles(token_manager: TokenManager, limit: int = 100, filters: dict = None) -> dict[str, int]:
    """
    Fetch profiles for horses not yet in the database.

    Args:
        token_manager: TokenManager instance
        limit: Max horses to fetch per call
        filters: Dict with optional filtering criteria

    Returns:
        {
            "horses_checked": int,
            "horses_saved": int,
            "horses_failed": int,
            "horses_not_found": int
        }
    """

    # Process filters - take the input but just ignore and continue
    if filters is not None:
        pass

    stats = {
        "horses_checked": 0,
        "horses_saved": 0,
        "horses_failed": 0,
        "horses_not_found": 0
    }

    # Get missing horse IDs
    with get_connection() as conn:
        animal_ids = get_unscraped_horses(conn, limit)

    if not animal_ids:
        return stats

    for animal_id in animal_ids:
        stats["horses_checked"] += 1

        # Build URL
        url = API_BASE["horses"].format(animal_id=animal_id)

        try:
            token = token_manager.get_valid_token()
            data = fetch_json(url, token)

            # Transform / normalize - matches step2 and step3 pattern
            horses = []

            # Extract performance details (might be empty array)
            raw_data = data.get("data") or []
            perf_list = raw_data.get("performanceDetails") or []
            perf = perf_list[0] if perf_list else {}

            horses.append(
                {
                    "animal_id": animal_id,
                    "racehorse_name": raw_data.get("name"),
                    "name_no_country": raw_data.get("nameWithNoCountry"),
                    "dob": raw_data.get("dateOfBirth"),
                    "age": raw_data.get("age"),
                    "moniker": raw_data.get("moniker"),
                    "sex": raw_data.get("sex"),
                    "trainer": raw_data.get("trainerName"),
                    "total_wins": perf.get("totalWins", 0),
                    "total_runs": perf.get("totalRuns", 0),
                    "total_places": perf.get("totalPlaces", 0),
                    "fetched_at": datetime.now().isoformat(timespec="seconds"),
                    "processed": 0,
                }
            )

            if horses:
                save_horses(horses)
                stats["horses_saved"] += len(horses)

        except RuntimeError as e:
            if "404" in str(e):
                stats["horses_not_found"] += 1
                print(f"[step4] Horse {animal_id} not found (404)")
            elif "401" in str(e):
                token_manager.refresh_token()
                print("[step4] Token expired, refreshing")
            else:
                stats["horses_failed"] += 1
                print(f"[step4] Failed to fetch horse {animal_id}: {e}")
            continue

        except Exception as e:
            stats["horses_failed"] += 1
            print(f"[step4] Unexpected error for horse {animal_id}: {e}")
            continue

    return stats


def save_horses(horses: list[dict[str, str | int]]) -> None:
    """Save horse profiles to database."""
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
                    h["name_no_country"],
                    h["dob"],
                    h["age"],
                    h["moniker"],
                    h["sex"],
                    h["trainer"],
                    h["total_wins"],
                    h["total_runs"],
                    h["total_places"],
                    h["fetched_at"],
                    h["processed"],
                )
                for h in horses
            ],
        )