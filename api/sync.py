from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date

from api.models import Fixture, Race, Horse, Performance


@dataclass(frozen=True)
class SyncStats:
    fixtures_upserted: int = 0
    races_upserted: int = 0
    horses_upserted: int = 0
    performances_upserted: int = 0


def _connect_scraper_db() -> sqlite3.Connection:
    db_path = Path(getattr(settings, "SCRAPER_DB_PATH"))
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> Iterable[sqlite3.Row]:
    cur = conn.execute(sql, params)
    for row in cur:
        yield row


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def _fixture_external_id(fixture_id: Any) -> str:
    return str(fixture_id)


def _race_external_id(race_id: Any, division_sequence: Any) -> str:
    return f"{race_id}:{division_sequence or 0}"


def _horse_external_id(animal_id: Any) -> str:
    return str(animal_id)


def _performance_external_id(race_id: Any, animal_id: Any, division_sequence: Any) -> str:
    return f"{race_id}:{animal_id}:{division_sequence or 0}"


def _parse_race_off_time(race_date_text: str | None, race_time_text: str | None):
    """
    Scraper has race_date TEXT and race_time TEXT.
    We'll store off_time if we can build something sensible.
    If parsing is unclear, keep it None and preserve everything in raw.
    """
    if not race_date_text:
        return None

    d = parse_date(race_date_text)
    if not d:
        return None

    # race_time is often "HH:MM" or "HH:MM:SS". If missing/unparseable, skip.
    if not race_time_text:
        return None

    t = race_time_text.strip()
    try:
        parts = t.split(":")
        if len(parts) < 2:
            return None
        hour = int(parts[0])
        minute = int(parts[1])
        second = int(parts[2]) if len(parts) >= 3 else 0
        naive = timezone.datetime(d.year, d.month, d.day, hour, minute, second)
        if timezone.is_naive(naive):
            return timezone.make_aware(naive, timezone.get_current_timezone())
        return naive
    except Exception:
        return None


@transaction.atomic
def sync_scraper_to_django(*, limit: int | None = None) -> SyncStats:
    """
    Import data from scraper staging SQLite into Django-owned tables.

    Notes:
    - Uses update_or_create (simple + correct; optimize later if needed).
    - Uses external_id strings to represent composite uniqueness.
    """
    conn = _connect_scraper_db()
    try:
        fixtures_upserted = 0
        races_upserted = 0
        horses_upserted = 0
        performances_upserted = 0

        # --- Fixtures ---
        fixtures_sql = """
            SELECT fixture_id, fixture_date, course_name, course_id, meeting_id,
                   first_race, number_of_races, fixture_type, major_event,
                   results_available, fetched_at, processed
            FROM fixtures
        """
        if limit is not None:
            fixtures_sql += " LIMIT ?"

        for row in _rows(conn, fixtures_sql, (limit,) if limit is not None else ()):
            raw = _row_to_dict(row)
            ext_id = _fixture_external_id(raw["fixture_id"])

            Fixture.objects.update_or_create(
                external_id=ext_id,
                defaults={
                    "source": "bhra",
                    "date": parse_date(raw.get("fixture_date") or "") or None,
                    "raw": raw,
                },
            )
            fixtures_upserted += 1

        # --- Races ---
        races_sql = """
            SELECT race_id, fixture_id, division_sequence, race_date, race_time,
                   age_limit, race_class, distance_value, distance_text,
                   distance_change_text, race_criteria_type, fetched_at,
                   processed, sectioned, horse_count
            FROM races
        """
        if limit is not None:
            races_sql += " LIMIT ?"

        for row in _rows(conn, races_sql, (limit,) if limit is not None else ()):
            raw = _row_to_dict(row)
            race_ext = _race_external_id(raw["race_id"], raw.get("division_sequence"))

            fixture_ext = _fixture_external_id(raw["fixture_id"])
            fixture = Fixture.objects.filter(external_id=fixture_ext).first()

            Race.objects.update_or_create(
                external_id=race_ext,
                defaults={
                    "source": "bhra",
                    "fixture": fixture,
                    "off_time": _parse_race_off_time(raw.get("race_date"), raw.get("race_time")),
                    "raw": raw,
                },
            )
            races_upserted += 1

        # --- Horses ---
        horses_sql = """
            SELECT animal_id, racehorse_name, dob, age, moniker, sex, trainer,
                   name_no_country, total_wins, total_runs, total_places,
                   fetched_at, processed
            FROM horses
        """
        if limit is not None:
            horses_sql += " LIMIT ?"

        for row in _rows(conn, horses_sql, (limit,) if limit is not None else ()):
            raw = _row_to_dict(row)
            horse_ext = _horse_external_id(raw["animal_id"])

            Horse.objects.update_or_create(
                external_id=horse_ext,
                defaults={
                    "source": "bhra",
                    "name": raw.get("racehorse_name") or "",
                    "dob": parse_date(raw.get("dob") or "") or None,
                    "raw": raw,
                },
            )
            horses_upserted += 1

        # --- Performances ---
        perfs_sql = """
            SELECT performance_id, race_id, animal_id, division_sequence,
                   result_position, status, horse_name, cloth_number, drawn_stall,
                   reserve_no, trainer_name, jockey_name, sex, age, primary_color,
                   position_time, is_runner, final_position, race_criteria_type,
                   finish_time, fetched_at, processed
            FROM race_performances
        """
        if limit is not None:
            perfs_sql += " LIMIT ?"

        for row in _rows(conn, perfs_sql, (limit,) if limit is not None else ()):
            raw = _row_to_dict(row)

            race_ext = _race_external_id(raw["race_id"], raw.get("division_sequence"))
            horse_ext = _horse_external_id(raw["animal_id"])
            perf_ext = _performance_external_id(raw["race_id"], raw["animal_id"], raw.get("division_sequence"))

            race = Race.objects.filter(external_id=race_ext).first()
            horse = Horse.objects.filter(external_id=horse_ext).first()

            Performance.objects.update_or_create(
                external_id=perf_ext,
                defaults={
                    "source": "bhra",
                    "race": race,
                    "horse": horse,
                    "raw": raw,
                },
            )
            performances_upserted += 1

        return SyncStats(
            fixtures_upserted=fixtures_upserted,
            races_upserted=races_upserted,
            horses_upserted=horses_upserted,
            performances_upserted=performances_upserted,
        )
    finally:
        conn.close()