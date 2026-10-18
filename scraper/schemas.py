"""
Shared scraper data contracts.

This module contains TypedDict definitions used by the scraper service,
pipeline steps, and database helpers.

The types here describe:
- caller-provided filters
- normalized service filters
- transformed database rows
- lightweight step result shapes

Keeping these contracts separate from step modules avoids importing operational
pipeline code just to share type definitions.
"""

from typing import Any, NotRequired, TypedDict


class FixtureFilters(TypedDict, total=False):
    fixture_types: list[str]
    courses: list[str]


class RaceFilters(TypedDict, total=False):
    race_type: str
    minimum_distance: int
    maximum_distance: int
    race_classes: list[int]


class NormalizedFilters(FixtureFilters, RaceFilters, total=False):
    pass


class RateLimitProfile(TypedDict, total=False):
    base_delay: float
    max_delay: float
    backoff_factor: float
    jitter_min: float
    jitter_max: float


class BatchProfile(TypedDict, total=False):
    batch_pause_seconds: float
    empty_pause_seconds: float
    max_loops: int
    rate_limit: RateLimitProfile


class CooldownResult(TypedDict):
    success: bool
    paused: bool
    retry_after_seconds: int
    stats: dict[str, Any]
    error: str


class FixturesSummary(TypedDict):
    date_range: str
    months_checked: int
    fixtures_saved: int


class FixtureRow(TypedDict):
    fixture_id: int | None
    fixture_date: str
    course_name: str | None
    course_id: int | None
    meeting_id: int | None
    first_race: str | None
    number_of_races: int | None
    fixture_type: str | None
    major_event: str | None
    results_available: int
    fetched_at: str
    processed: int


class RaceRow(TypedDict):
    race_id: int | None
    fixture_id: int
    division_sequence: int
    race_date: str | None
    race_time: str | None
    age_limit: str | None
    race_class: int | None
    distance_value: int | None
    distance_text: str | None
    distance_change_text: str | None
    race_criteria_type: Any
    fetched_at: str
    processed: int
    sectioned: int
    horse_count: int


class PerformanceRow(TypedDict):
    race_id: int
    fetched_at: str
    processed: int
    performance_id: NotRequired[int]
    animal_id: NotRequired[int | None]
    division_sequence: NotRequired[int | None]
    result_position: NotRequired[int | None]
    status: NotRequired[int | None]
    horse_name: NotRequired[str | None]
    cloth_number: NotRequired[str | None]
    drawn_stall: NotRequired[int | None]
    reserve_no: NotRequired[int | None]
    trainer_name: NotRequired[str | None]
    jockey_name: NotRequired[str | None]
    sex: NotRequired[str | None]
    age: NotRequired[str | None]
    primary_color: NotRequired[Any]
    position_time: NotRequired[str | None]
    is_runner: NotRequired[Any]
    final_position: NotRequired[str | None]
    race_criteria_type: NotRequired[Any]
    finish_time: NotRequired[str | None]


class HorseRow(TypedDict):
    animal_id: int
    racehorse_name: str
    fetched_at: str
    processed: int
    name_no_country: NotRequired[str | None]
    dob: NotRequired[str | None]
    age: NotRequired[int | None]
    moniker: NotRequired[str | None]
    sex: NotRequired[str | None]
    trainer: NotRequired[str | None]
    total_wins: NotRequired[int]
    total_runs: NotRequired[int]
    total_places: NotRequired[int]


class SectionalStats(TypedDict):
    sectionals_checked: int
    sectionals_saved: int
    sectionals_failed: int
    sectionals_skipped: int
