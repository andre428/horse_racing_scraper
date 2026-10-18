"""
ScraperService — Orchestrated horse racing data pipeline

Overview
--------
This module provides a portable, framework-agnostic scraping service responsible
for executing a multi-step data ingestion pipeline against the BHA API.

The service is designed to work with multiple launchers:
- Django (direct call or Celery task)
- CLI / scripts (testing, batch runs)
- Standalone execution

Pipeline Structure
------------------
The scraper operates as a strictly ordered sequence of dependent steps:

    Step 1 — Fixtures
        Fetch race fixtures for a given date range.
        Applies fixture-level filters (type, course).

    Step 2 — Races
        Fetch races for stored fixtures.
        Depends on Step 1 output.

    Step 3 — Results
        Fetch race results and performance data.
        Applies race-level filters (type, distance, class).
        Depends on Step 2 output.

    Step 4 — Horses (optional)
        Fetch horse profiles referenced by race performances.
        Can be disabled for performance or debugging.

    Step 5 — Sectional Times (optional)
        Fetch sectional timing data for processed races.
        Runs after results (and optionally horses).

Execution Model
---------------
- Steps run sequentially and only proceed if prior step produced data.
- Steps 4 and 5 can be independently toggled.
- Steps operate in batches to control load and allow resumability.

Rate Limiting & Networking
--------------------------
All HTTP requests are routed through a unified fetch layer (`fetch_with_retry`)
which provides:
- global rate limiting (shared across all steps)
- automatic retry handling (401 token refresh, 429 backoff)
- adaptive throttling via RateLimiter

This ensures:
- API-friendly behavior (no request flooding)
- consistent retry logic
- centralized tuning of request pacing

Resilience & Recovery
---------------------
- Each step processes data incrementally (batch-based)
- Failures do not crash the entire pipeline unless critical
- Database state allows safe re-runs and partial continuation
- External stop signal can interrupt execution safely

Filtering
---------
Filters are passed from the caller and split into:
- Fixture filters (Step 1)
- Race filters (Step 3)

Downstream steps operate only on already filtered data.

Typical Usage
-------------
    service = ScraperService()

    result = service.scrape_days_back(
        days_back=7,
        filters={
            "fixture_types": ["FLAT"],
            "courses": ["Ascot"],
            "race_type": "FLAT",
            "minimum_distance": 1200,
            "maximum_distance": 1600,
        },
        run_horses=True,
        run_sectionals=False,
    )

    print(result)

Design Goals
------------
- Deterministic and predictable execution
- Minimal API load while maintaining performance
- Clear separation of responsibilities (service vs steps vs transport)
- Easy integration with external systems (Django, Celery, CLI)

"""

from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import uuid4

from .rate_limiter import RateLimiter
from .schemas import FixtureFilters, NormalizedFilters, RaceFilters
from .step1_fixtures import fetch_fixtures_range
from .step2_races import fetch_races_for_fixtures
from .step3_results import fetch_results_for_races
from .step4_horses import fetch_horse_profiles
from .step5_sections import fetch_section_times
from .token_manager import TokenManager
from .utils import info, warn


class LogFn(Protocol):
    def __call__(self, event: str, **data: Any) -> None: ...


def _noop_log(event: str, **data: Any) -> None:
    del event, data


class ScraperService:
    """
    High-level orchestration layer for the scraping pipeline.

    Responsibilities:
    - Controls execution flow (Step 1 → Step 5)
    - Applies batching
    - Emits progress events for UI / Celery
    - Integrates rate limiting + token management
    - Supports external stop signals (Django)

    Designed to be:
    - framework-agnostic
    - observable (run_id + progress events)
    """

    def __init__(
        self,
        enable_logging: bool = True,
        rate_limit_seconds: float = 1.2,
        progress_callback: Callable[[str, dict[str, Any]], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> None:
        self.run_id = uuid4().hex[:8]

        self.enable_logging = enable_logging
        self.progress_callback = progress_callback
        self.should_stop = should_stop or (lambda: False)

        self._log: LogFn = info if enable_logging else _noop_log
        self._warn: LogFn = warn if enable_logging else _noop_log

        self.rate_limiter = RateLimiter(base_delay=rate_limit_seconds)

        self.token_manager = TokenManager()
        self.token_manager.get_valid_token()

        self.fixture_filters: FixtureFilters = {}
        self.race_filters: RaceFilters = {}

    # =========================================================
    # 🔹 PUBLIC ENTRY
    # =========================================================

    def scrape_days_back(
        self,
        days_back: int,
        filters: dict[str, Any] | None = None,
        run_horses: bool = True,
        run_sectionals: bool = True,
        batch_size: dict[str, int] | None = None,
    ) -> dict[str, Any]:
        normalized_filters = self._normalize_filters(filters or {})
        self._log(
            "scrape_started",
            run_id=self.run_id,
            days_back=days_back,
            run_horses=run_horses,
            run_sectionals=run_sectionals,
            normalized_filters=normalized_filters,
        )

        if batch_size is None:
            batch_size = {"races": 50, "results": 100, "horses": 50, "sectionals": 50}

        dates = self._build_dates(days_back)
        self.fixture_filters, self.race_filters = self._validate_filters(normalized_filters)

        stats = self._init_stats(dates)

        try:
            # ================= STEP 1 =================
            self._emit("step_started", {"step": 1, "name": "fixtures"})

            s1 = fetch_fixtures_range(
                start_date=dates[0],
                end_date=dates[-1],
                token_manager=self.token_manager,
                filters=self.fixture_filters,
                rate_limiter=self.rate_limiter,
            )

            stats.update(s1)

            self._emit(
                "step_completed",
                {"step": 1, "name": "fixtures", "count": s1.get("fixtures_saved", 0)},
            )

            if not s1.get("fixtures_saved"):
                return self._success(stats)

            # ================= STEP 2 =================
            s2 = self._run_batched(
                fetch_races_for_fixtures,
                batch_size["races"],
                filters=self.fixture_filters,
                progress_key="races_saved",
                step=2,
                name="races",
            )
            stats.update(s2)

            if not s2.get("races_saved"):
                return self._success(stats)

            # ================= STEP 3 =================
            s3 = self._run_batched(
                fetch_results_for_races,
                batch_size["results"],
                filters=self.race_filters,
                progress_key="results_saved",
                step=3,
                name="results",
            )
            stats.update(s3)

            # ================= STEP 4 =================
            if run_horses:
                s4 = self._run_batched(
                    fetch_horse_profiles,
                    batch_size["horses"],
                    filters=None,
                    progress_key="horses_saved",
                    step=4,
                    name="horses",
                )
                stats.update(s4)

            # ================= STEP 5 =================
            if run_sectionals:
                s5 = self._run_batched(
                    fetch_section_times,
                    batch_size["sectionals"],
                    filters=None,
                    progress_key="sectionals_saved",
                    step=5,
                    name="sectionals",
                )
                stats.update(s5)

            self._log("scrape_completed", run_id=self.run_id, stats=stats)

            return self._success(stats)

        except Exception as exc:
            msg = f"[run:{self.run_id}] Scraping failed: {exc}"
            self._warn("scrape_failed", run_id=self.run_id, error=msg)
            return {"success": False, "stats": stats, "error": msg}

    # =========================================================
    # 🔹 CORE ENGINE
    # =========================================================

    def _run_batched(
        self,
        fn,
        batch_size: int,
        filters: FixtureFilters | RaceFilters | None,
        progress_key: str,
        step: int,
        name: str,
        max_loops: int = 1000,
    ) -> dict[str, int]:
        totals: dict[str, int] = {}
        loop = 0

        self._emit("step_started", {"step": step, "name": name})

        while True:
            self._check_stop()
            loop += 1

            if loop > max_loops:
                raise RuntimeError(f"{fn.__name__} exceeded max_loops")

            kwargs = {
                "token_manager": self.token_manager,
                "limit": batch_size,
                "rate_limiter": self.rate_limiter,
            }

            if filters is not None:
                kwargs["filters"] = filters

            stats = fn(**kwargs)

            if not stats:
                break

            for k, v in stats.items():
                totals[k] = totals.get(k, 0) + v

            if stats.get(progress_key, 0) == 0:
                break

        self._emit(
            "step_completed", {"step": step, "name": name, "count": totals.get(progress_key, 0)}
        )

        return totals

    # =========================================================
    # 🔹 HELPERS
    # =========================================================

    def _check_stop(self) -> None:
        if self.should_stop():
            raise RuntimeError("Stopped externally")

    def _emit(self, event: str, data: dict[str, Any]) -> None:
        data["run_id"] = self.run_id
        if self.progress_callback:
            self.progress_callback(event, data)

    def _build_dates(self, days_back: int) -> list[str]:
        today = datetime.now(UTC).date()
        return [(today - timedelta(days=i)).isoformat() for i in range(days_back, -1, -1)]

    def _init_stats(self, dates: list[str]) -> dict[str, Any]:
        return {
            "dates_requested": len(dates),
            "fixtures_saved": 0,
            "races_saved": 0,
            "results_saved": 0,
            "horses_saved": 0,
            "sectionals_saved": 0,
        }

    def _success(self, stats: dict[str, Any]) -> dict[str, Any]:
        return {"success": True, "stats": stats, "error": None}

    @staticmethod
    def _normalize_list_filter(
        value: Any, *, caster: Callable[[Any], Any] | None = None
    ) -> list[Any] | None:
        """
        Normalize list-like filter input.

        Contract:
        - None or [] means "no filter" (all values)
        - non-empty sequence means "apply filter"
        """
        if value is None:
            return None

        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
            value = [value]

        normalized: list[Any] = []
        for item in value:
            if item in (None, ""):
                continue
            normalized.append(caster(item) if caster else item)

        return normalized or None

    @classmethod
    def _normalize_filters(cls, filters: dict[str, Any]) -> NormalizedFilters:
        """Normalize caller-provided filter payload into canonical service contract."""
        normalized: NormalizedFilters = {}

        fixture_types = cls._normalize_list_filter(filters.get("fixture_types"))
        if fixture_types is not None:
            normalized["fixture_types"] = [str(v) for v in fixture_types]

        courses = cls._normalize_list_filter(filters.get("courses"))
        if courses is not None:
            normalized["courses"] = [str(v) for v in courses]

        race_classes = cls._normalize_list_filter(filters.get("race_classes"), caster=int)
        if race_classes is not None:
            normalized["race_classes"] = [int(v) for v in race_classes]

        race_type = filters.get("race_type")
        if race_type not in (None, ""):
            normalized["race_type"] = str(race_type)

        min_distance = filters.get("minimum_distance")
        if min_distance not in (None, ""):
            normalized["minimum_distance"] = int(min_distance)

        max_distance = filters.get("maximum_distance")
        if max_distance not in (None, ""):
            normalized["maximum_distance"] = int(max_distance)

        return normalized

    @staticmethod
    def _validate_filters(filters: NormalizedFilters) -> tuple[FixtureFilters, RaceFilters]:
        fixture_filters: FixtureFilters = {}
        race_filters: RaceFilters = {}

        fixture_types = filters.get("fixture_types")
        if fixture_types is not None:
            fixture_filters["fixture_types"] = fixture_types

        courses = filters.get("courses")
        if courses is not None:
            fixture_filters["courses"] = courses

        race_type = filters.get("race_type")
        if race_type is not None:
            race_filters["race_type"] = race_type

        min_distance = filters.get("minimum_distance")
        if min_distance is not None:
            race_filters["minimum_distance"] = min_distance

        max_distance = filters.get("maximum_distance")
        if max_distance is not None:
            race_filters["maximum_distance"] = max_distance

        race_classes = filters.get("race_classes")
        if race_classes is not None:
            race_filters["race_classes"] = race_classes

        return fixture_filters, race_filters
