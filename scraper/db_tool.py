"""
Simplified database tool for buffer/dump storage.

Key simplifications:
- Extracted helper functions remain clean
- Removed redundant comments
- Type hints added consistently
- Kept commented sectional code for future use
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from .config import DB_PATH
from .schemas import RaceFilters


@contextmanager
def get_connection():
    """Get database connection with automatic commit/rollback."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_database() -> None:
    """
    Create tables for a multistep scraping workflow.

    Note: All distance values are in yards (imperial units).
    """
    with get_connection() as conn:
        # Fixtures table
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS fixtures (
                fixture_id INTEGER PRIMARY KEY,
                fixture_date TEXT,
                course_name TEXT,
                course_id INTEGER,
                meeting_id INTEGER,
                first_race TEXT,
                number_of_races INTEGER,
                fixture_type TEXT,
                major_event TEXT,
                results_available INTEGER DEFAULT 0,
                fetched_at TEXT NOT NULL,
                processed INTEGER DEFAULT 0,
                UNIQUE(fixture_id)
            )
        """)

        # Races table
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS races (
                race_pk INTEGER PRIMARY KEY AUTOINCREMENT,
                race_id INTEGER NOT NULL,
                fixture_id INTEGER NOT NULL,
                division_sequence INTEGER NOT NULL DEFAULT 0,
                race_date TEXT NOT NULL,
                race_time TEXT,
                age_limit TEXT,
                race_class INTEGER,
                distance_value INTEGER,
                distance_text TEXT,
                distance_change_text TEXT,
                race_criteria_type TEXT,
                fetched_at TEXT NOT NULL,
                processed INTEGER DEFAULT 0,
                sectioned INTEGER DEFAULT 0,
                horse_count INTEGER DEFAULT 0,
                UNIQUE(race_id, division_sequence)
            )
        """)

        # Horses table
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS horses (
                animal_id INTEGER PRIMARY KEY,
                racehorse_name TEXT NOT NULL,
                dob TEXT,
                age INTEGER,
                moniker TEXT,
                sex TEXT,
                trainer TEXT,
                name_no_country TEXT,
                total_wins INTEGER DEFAULT 0,
                total_runs INTEGER DEFAULT 0,
                total_places INTEGER DEFAULT 0,
                fetched_at TEXT NOT NULL,
                processed INTEGER DEFAULT 0,
                UNIQUE(animal_id)
            )
        """)

        # Race performances table
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS race_performances (
                performance_id INTEGER PRIMARY KEY AUTOINCREMENT,
                race_id INTEGER NOT NULL,
                animal_id INTEGER NOT NULL,
                division_sequence INTEGER DEFAULT 0,
                result_position INTEGER,
                status INTEGER,
                horse_name TEXT,
                cloth_number TEXT NOT NULL,
                drawn_stall INTEGER,
                reserve_no INTEGER,
                trainer_name TEXT,
                jockey_name TEXT,
                sex TEXT,
                age TEXT,
                primary_color INTEGER,
                position_time TEXT,
                is_runner TEXT,
                final_position TEXT,
                race_criteria_type INTEGER DEFAULT 1,
                finish_time TEXT,
                fetched_at TEXT NOT NULL,
                processed INTEGER DEFAULT 0,
                UNIQUE(race_id, animal_id, division_sequence)
            )
        """)

        # Section times table
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS section_times (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                performance_id INTEGER NOT NULL,
                race_id INTEGER NOT NULL,
                animal_id INTEGER NOT NULL,
                racehorse_name TEXT NOT NULL,
                marker_number INTEGER NOT NULL,
                time_at_marker REAL NOT NULL,
                comment TEXT,
                official_placing TEXT,
                adj_placing TEXT,
                fetched_at TEXT NOT NULL,
                processed INTEGER DEFAULT 0,
                UNIQUE(performance_id, marker_number)
            )
        """)

        # Scraping progress tracking
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS scrape_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scrape_type TEXT NOT NULL,
                target_id TEXT NOT NULL,
                status TEXT NOT NULL,
                error_message TEXT,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                UNIQUE(scrape_type, target_id)
            )
        """)

        # Indexes
        conn.executescript("""
            CREATE INDEX IF NOT EXISTS idx_fixtures_date ON fixtures(fixture_date);
            CREATE INDEX IF NOT EXISTS idx_fixtures_processed ON fixtures(processed);
            CREATE INDEX IF NOT EXISTS idx_races_fixture ON races(fixture_id);
            CREATE INDEX IF NOT EXISTS idx_races_date ON races(race_date);
            CREATE INDEX IF NOT EXISTS idx_races_processed ON races(processed);
            CREATE INDEX IF NOT EXISTS idx_races_sectioned ON races(sectioned);
            CREATE INDEX IF NOT EXISTS idx_perf_race ON race_performances(race_id);
            CREATE INDEX IF NOT EXISTS idx_perf_horse ON race_performances(animal_id);
            CREATE INDEX IF NOT EXISTS idx_perf_processed ON race_performances(processed);
            CREATE INDEX IF NOT EXISTS idx_section_perf ON section_times(performance_id);
            CREATE INDEX IF NOT EXISTS idx_section_race ON section_times(race_id);
            CREATE INDEX IF NOT EXISTS idx_section_processed ON section_times(processed);
            CREATE INDEX IF NOT EXISTS idx_horses_name ON horses(racehorse_name);
            CREATE INDEX IF NOT EXISTS idx_horses_processed ON horses(processed)
        """)

        _ensure_scrape_log_columns(conn)
        conn.executescript("""
            CREATE INDEX IF NOT EXISTS idx_scrape_log_type_status ON scrape_log(scrape_type, status);
            CREATE INDEX IF NOT EXISTS idx_scrape_log_type_target ON scrape_log(scrape_type, target_id);
        """)


def convert_race_time(time_string: str) -> str:
    """Convert time string to 4-digit format (e.g., '11:37:00' -> '1137')."""
    parts = time_string.split(":")
    return f"{parts[0]}{parts[1]}"


def get_unprocessed_fixtures(
        conn: Any,
        limit: int = 100,
        fixture_types: list[str] | None = None,
        courses: list[str] | None = None,
) -> list[Any]:
    """
    Get fixtures that haven't been scraped for races yet.

    Args:
        conn: Database connection
        limit: Max fixtures to return
        fixture_types: Filter by types like ["FLAT", "JUMP"]
        courses: Filter by course names like ["Ascot", "Newmarket"]

    Returns:
        List of fixture rows
    """
    query = """
        SELECT fixture_id, fixture_date, meeting_id, number_of_races
        FROM fixtures
        WHERE processed = 0 AND results_available = 1
    """
    params = []

    if fixture_types:
        placeholders = ",".join("?" * len(fixture_types))
        query += f" AND fixture_type IN ({placeholders})"
        params.extend(fixture_types)

    if courses:
        placeholders = ",".join("?" * len(courses))
        query += f" AND course_name IN ({placeholders})"
        params.extend(courses)

    query += " ORDER BY fixture_date DESC LIMIT ?"
    params.append(limit)

    cursor = conn.execute(query, params)
    return cursor.fetchall()


def get_unprocessed_races(
        conn: Any, limit: int = 100, race_filters: RaceFilters | None = None
) -> list[Any]:
    """
    Get races that haven't been scraped for results yet.

    Args:
        conn: Database connection
        limit: Max races to return
        race_filters: Optional dict with keys:
            - race_type: "FLAT" or "JUMP"
            - minimum_distance: Minimum distance in yards
            - maximum_distance: Maximum distance in yards
            - race_classes: List of race classes [1, 2, 3, etc.]

    Returns:
        List of race rows
    """
    query = "SELECT * FROM races WHERE processed = 0"
    params = []

    if race_filters:
        race_type = race_filters.get("race_type")
        if race_type:
            query += " AND race_criteria_type = ?"
            params.append(race_type)

        minimum_distance = race_filters.get("minimum_distance")
        if minimum_distance:
            query += " AND distance_value >= ?"
            params.append(minimum_distance)

        maximum_distance = race_filters.get("maximum_distance")
        if maximum_distance:
            query += " AND distance_value <= ?"
            params.append(maximum_distance)

        race_classes = race_filters.get("race_classes")
        if race_classes:
            placeholders = ",".join("?" * len(race_classes))
            query += f" AND race_class IN ({placeholders})"
            params.extend(race_classes)

    query += " ORDER BY race_date DESC, race_time ASC LIMIT ?"
    params.append(limit)

    cursor = conn.execute(query, params)
    return cursor.fetchall()


def get_unsectioned_races(conn: Any, limit: int = 100) -> list[Any]:
    """Get races that still have sectional times not fetched."""
    cursor = conn.execute(
        """
        SELECT * FROM races
        WHERE sectioned = 0
        ORDER BY race_date DESC, race_time DESC
        LIMIT ?
        """,
        (limit,),
    )
    return cursor.fetchall()


def mark_sectioned(conn: Any, race_id: int) -> None:
    """Mark a race as having sectional times fetched."""
    conn.execute(
        "UPDATE races SET sectioned = 1 WHERE race_id = ?",
        (race_id,),
    )


def validate_race_count(conn: Any, fixture_id: int, expected: int | None) -> bool:
    """Check if the scraped race count matches the expected count."""
    if expected is None:
        return True

    cursor = conn.execute(
        "SELECT COUNT(*) as actual FROM races WHERE fixture_id = ?", (fixture_id,)
    )

    actual = cursor.fetchone()["actual"]
    return actual == expected


def get_unscraped_horses(conn: Any, limit: int = 100) -> list[int]:
    """Get unique animal_ids that need full horse profiles."""
    cursor = conn.execute(
        """
        SELECT DISTINCT animal_id
        FROM race_performances
        WHERE animal_id NOT IN (SELECT animal_id FROM horses)
        LIMIT ?
        """,
        (limit,),
    )
    return [row["animal_id"] for row in cursor.fetchall()]


def mark_processed(conn: Any, table: str, id_column: str, id_value: int) -> None:
    """Mark an item as processed."""
    valid_tables = {"fixtures", "races", "race_performances", "section_times", "horses"}
    valid_columns = {"fixture_id", "race_id", "race_pk", "performance_id", "animal_id", "id"}

    if table not in valid_tables or id_column not in valid_columns:
        raise ValueError(f"Invalid table or column: {table}.{id_column}")

    conn.execute(f"UPDATE {table} SET processed = 1 WHERE {id_column} = ?", (id_value,))


def get_scraping_stats(conn: Any) -> dict[str, dict[str, int]]:
    """Get an overview of scraping progress."""
    stats = {}

    for table in ["fixtures", "races", "race_performances", "section_times", "horses"]:
        cursor = conn.execute(f"""
            SELECT
                COUNT(*) as total,
                SUM(processed) as processed,
                COUNT(*) - SUM(processed) as remaining
            FROM {table}
        """)
        stats[table] = dict(cursor.fetchone())

    return stats


def log_batch_start(conn: Any, step_name: str, batch_num: int) -> None:
    """Log when a batch starts processing."""
    conn.execute(
        """INSERT INTO scrape_log (scrape_type, target_id, status, started_at)
           VALUES (?, ?, ?, ?)""",
        (step_name, f"batch_{batch_num}", "running", datetime.now().isoformat()),
    )


def log_batch_complete(conn: Any, step_name: str, batch_num: int, items_processed: int) -> None:
    """Log successful batch completion."""
    conn.execute(
        """UPDATE scrape_log
           SET status = 'completed', completed_at = ?, error_message = ?
           WHERE scrape_type = ? AND target_id = ?""",
        (
            datetime.now().isoformat(),
            f"Processed {items_processed} items",
            step_name,
            f"batch_{batch_num}",
        ),
    )


def _ensure_scrape_log_columns(conn: Any) -> None:
    """
    Ensure scrape_log has extra columns needed for robust retry logic.

    Safe for SQLite: only adds columns if missing.
    """
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(scrape_log)")}

    if "attempts" not in existing:
        conn.execute("ALTER TABLE scrape_log ADD COLUMN attempts INTEGER DEFAULT 0")
    if "last_attempt_at" not in existing:
        conn.execute("ALTER TABLE scrape_log ADD COLUMN last_attempt_at TEXT")


def upsert_scrape_log(
        conn: Any,
        scrape_type: str,
        target_id: str,
        status: str,
        error_message: str | None = None,
        increment_attempt: bool = False,
) -> None:
    """Scrape log update"""
    now = datetime.now().isoformat(timespec="seconds")
    completed_at = now if status in {"completed", "failed", "not_found", "skipped"} else None

    # Ensure a row exists
    conn.execute(
        """
        INSERT OR IGNORE INTO scrape_log (scrape_type, target_id, status, error_message, started_at, completed_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (scrape_type, target_id, status, error_message, now, completed_at),
    )

    if increment_attempt:
        conn.execute(
            """
            UPDATE scrape_log
            SET status = ?,
                error_message = ?,
                completed_at = ?,
                attempts = COALESCE(attempts, 0) + 1,
                last_attempt_at = ?
            WHERE scrape_type = ? AND target_id = ?
            """,
            (status, error_message, completed_at, now, scrape_type, target_id),
        )
    else:
        conn.execute(
            """
            UPDATE scrape_log
            SET status = ?,
                error_message = ?,
                completed_at = ?
            WHERE scrape_type = ? AND target_id = ?
            """,
            (status, error_message, completed_at, scrape_type, target_id),
        )


def get_pending_horse_ids(
        conn: Any, limit: int = 100, retry_cooldown_minutes: int = 60, max_attempts: int = 5
) -> list[int]:
    """
    Returns animal_ids seen in race_performances but not yet in horses, excluding:
      - completed
      - not_found
    Retries:
      - failed entries only if cooldown has elapsed and attempts < max_attempts
      - never retries not_found
    """
    cursor = conn.execute(
        """
        WITH candidates AS (
            SELECT DISTINCT rp.animal_id AS animal_id
            FROM race_performances rp
            LEFT JOIN horses h ON h.animal_id = rp.animal_id
            WHERE h.animal_id IS NULL
        )
        SELECT c.animal_id
        FROM candidates c
        LEFT JOIN scrape_log sl
            ON sl.scrape_type = 'horse'
           AND sl.target_id = CAST(c.animal_id AS TEXT)
        WHERE
            sl.id IS NULL
            OR (
                sl.status NOT IN ('completed', 'not_found')
                AND (
                    sl.status != 'failed'
                    OR (
                        COALESCE(sl.attempts, 0) < ?
                        AND (
                            sl.last_attempt_at IS NULL
                            OR datetime(sl.last_attempt_at) <= datetime('now', '-' || ? || ' minutes')
                        )
                    )
                )
            )
        LIMIT ?
        """,
        (max_attempts, retry_cooldown_minutes, limit),
    )
    return [row["animal_id"] for row in cursor.fetchall()]
