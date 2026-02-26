"""
Scraper service for orchestrating multistep scraping.
"""

import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from .db_tool import get_connection, get_scraping_stats, get_unscraped_horses
from .step1_fixtures import FixtureFilters, fetch_fixtures_range
from .step2_races import fetch_races_for_fixtures
from .step3_results import RaceFilters, fetch_results_for_races
from .step4_horses import fetch_horse_profiles
from .token_manager import TokenManager
from .utils import info, warn


class ScraperService:
    """Coordinates fixtures → races → results → horses scraping workflow."""

    def __init__(
        self,
        enable_logging: bool = True,
        rate_limit_seconds: int = 2,
        progress_callback: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        """Create service and initialize token manager."""
        self.enable_logging = enable_logging
        self.rate_limit_seconds = rate_limit_seconds
        self.progress_callback = progress_callback
        self._log = info if enable_logging else lambda _: None
        self._warn = warn if enable_logging else lambda _: None

        self.fixture_filters: FixtureFilters = {}
        self.race_filters: RaceFilters = {}

        self._log("Initializing token manager...")
        self.token_manager = TokenManager()

        try:
            self.token_manager.get_valid_token()
            self._log("Token ready")
        except Exception as exc:
            self._warn(f"Token initialization failed: {exc}")
            raise

    @staticmethod
    def _validate_filters(filters: dict[str, Any] | None) -> tuple[FixtureFilters, RaceFilters]:
        """Validate filters and return (fixture_filters, race_filters)."""
        if filters is None:
            return {}, {}

        fixture_filters: FixtureFilters = {}
        race_filters: RaceFilters = {}

        if "fixture_types" in filters:
            types = filters["fixture_types"]
            if not isinstance(types, list):
                raise ValueError("fixture_types must be a list")
            valid_types = {"FLAT", "JUMP", "AWT"}
            for ft in types:
                if ft not in valid_types:
                    raise ValueError(f"Invalid fixture_type: {ft}. Must be one of {valid_types}")
            fixture_filters["fixture_types"] = types

        if "courses" in filters:
            courses = filters["courses"]
            if not isinstance(courses, list):
                raise ValueError("courses must be a list")
            fixture_filters["courses"] = courses

        if "race_type" in filters:
            value = filters["race_type"]
            if value not in {"FLAT", "JUMP"}:
                raise ValueError("race_type must be 'FLAT' or 'JUMP'")
            race_filters["race_type"] = value

        if "minimum_distance" in filters:
            value = filters["minimum_distance"]
            if not isinstance(value, int) or value < 0:
                raise ValueError("minimum_distance must be a positive integer")
            race_filters["minimum_distance"] = value

        if "maximum_distance" in filters:
            value = filters["maximum_distance"]
            if not isinstance(value, int) or value < 0:
                raise ValueError("maximum_distance must be a positive integer")
            race_filters["maximum_distance"] = value

        if "race_classes" in filters:
            classes = filters["race_classes"]
            if not isinstance(classes, list):
                raise ValueError("race_classes must be a list")
            for rc in classes:
                if not isinstance(rc, int) or not (1 <= rc <= 7):
                    raise ValueError(f"Invalid race_class: {rc}. Must be 1-7")
            race_filters["race_classes"] = classes

        return fixture_filters, race_filters

    def scrape_date_range(
        self,
        dates: list[str],
        run_horses: bool = True,
        batch_size: dict[str, int] | None = None,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run the full scraping workflow for a list of ISO dates."""
        if not dates:
            raise ValueError("No dates provided")

        for date_str in dates:
            try:
                datetime.fromisoformat(date_str)
            except ValueError as exc:
                raise ValueError(f"Invalid date format: {exc}") from None

        if batch_size is None:
            batch_size = {"races": 50, "results": 100, "horses": 100}

        stats: dict[str, Any] = {
            "dates_requested": len(dates),
            "fixtures_saved": 0,
            "races_saved": 0,
            "performances_saved": 0,
            "horses_saved": 0,
            "fixtures_completed": 0,
            "races_completed": 0,
        }

        self.fixture_filters, self.race_filters = self._validate_filters(filters)

        try:
            start_date = dates[0]
            end_date = dates[-1]

            fixtures_result = fetch_fixtures_range(
                start_date=start_date,
                end_date=end_date,
                token_manager=self.token_manager,
                filters=self.fixture_filters,
            )
            stats["fixtures_saved"] = fixtures_result.get("fixtures_saved", 0)

            if stats["fixtures_saved"] == 0:
                return {"success": True, "stats": stats, "error": None}

            races_result = self._run_batched_step(
                fetch_races_for_fixtures,
                batch_size["races"],
                "races",
                filters=self.fixture_filters,
            )
            stats["races_saved"] = races_result.get("races_saved", 0)
            stats["fixtures_completed"] = races_result.get("fixtures_completed", 0)

            if stats["races_saved"] == 0:
                return {"success": True, "stats": stats, "error": None}

            results_result = self._run_batched_step(
                fetch_results_for_races,
                batch_size["results"],
                "results",
                filters=self.race_filters,
            )
            stats["performances_saved"] = results_result.get("results_saved", 0)
            stats["races_completed"] = results_result.get("races_completed", 0)

            if run_horses:
                horses_result = self._run_batched_step(
                    fetch_horse_profiles,
                    batch_size["horses"],
                    "horses",
                )
                stats["horses_saved"] = horses_result.get("horses_saved", 0)

            self._report_progress("workflow_completed", stats)
            self._log_summary(stats)
            return {"success": True, "stats": stats, "error": None}

        except Exception as exc:
            error_msg = f"Scraping failed: {exc}"
            self._warn(error_msg)
            return {"success": False, "stats": stats, "error": error_msg}

    def _run_batched_step(
        self,
        step_function: Callable[..., dict[str, int]],
        batch_size: int,
        step_name: str,
        **step_kwargs: Any,
    ) -> dict[str, int]:
        """Run a step function until it reports no new saved items."""
        totals: dict[str, int] = {
            "races_saved": 0,
            "results_saved": 0,
            "fixtures_completed": 0,
            "races_completed": 0,
            "horses_saved": 0,
        }

        batch_num = 0
        while True:
            batch_num += 1

            batch_stats = step_function(
                token_manager=self.token_manager,
                limit=batch_size,
                **step_kwargs,
            )

            items_saved = batch_stats.get(f"{step_name}_saved", 0)
            if items_saved == 0:
                break

            for key, value in batch_stats.items():
                if key in totals:
                    totals[key] += value

            time.sleep(self.rate_limit_seconds)

        return totals

    def resume_scraping(
        self, run_horses: bool = True, batch_size: dict[str, int] | None = None
    ) -> dict[str, Any]:
        """Resume pending steps based on database progress."""
        if batch_size is None:
            batch_size = {"races": 50, "results": 100, "horses": 100}

        stats = {
            "races_saved": 0,
            "performances_saved": 0,
            "horses_saved": 0,
            "fixtures_completed": 0,
            "races_completed": 0,
        }

        progress = self.get_progress()

        if progress["fixtures"]["remaining"] > 0:
            races_result = self._run_batched_step(
                fetch_races_for_fixtures, batch_size["races"], "races"
            )
            stats["races_saved"] = races_result.get("races_saved", 0)
            stats["fixtures_completed"] = races_result.get("fixtures_completed", 0)

        if progress["races"]["remaining"] > 0:
            results_result = self._run_batched_step(
                fetch_results_for_races, batch_size["results"], "results"
            )
            stats["performances_saved"] = results_result.get("results_saved", 0)
            stats["races_completed"] = results_result.get("races_completed", 0)

        if run_horses:
            with get_connection() as conn:
                missing = get_unscraped_horses(conn, limit=1_000_000)
            if missing:
                horses_result = self._run_batched_step(
                    fetch_horse_profiles, batch_size["horses"], "horses"
                )
                stats["horses_saved"] = horses_result.get("horses_saved", 0)

        return {"success": True, "stats": stats, "error": None}

    def _log_summary(self, stats: dict[str, Any]) -> None:
        """Log a short workflow summary."""
        self._log(f"Fixtures saved:      {stats['fixtures_saved']:,}")
        self._log(f"Fixtures completed:  {stats['fixtures_completed']:,}")
        self._log(f"Races saved:         {stats['races_saved']:,}")
        self._log(f"Races completed:     {stats['races_completed']:,}")
        self._log(f"Performances saved:  {stats['performances_saved']:,}")
        if stats.get("horses_saved"):
            self._log(f"Horses saved:        {stats['horses_saved']:,}")

    def scrape_days_back(self, days_back: int, **kwargs: Any) -> dict[str, Any]:
        """Run workflow for last N days (inclusive)."""
        if days_back < 0:
            raise ValueError("days_back must be >= 0")

        today = datetime.now(UTC).date()
        start_date = today - timedelta(days=days_back)

        dates: list[str] = []
        current = start_date
        while current <= today:
            dates.append(current.strftime("%Y-%m-%d"))
            current += timedelta(days=1)

        return self.scrape_date_range(dates=dates, **kwargs)

    @staticmethod
    def get_progress() -> dict[str, Any]:
        """Return scraping progress counters from the database."""
        with get_connection() as conn:
            return get_scraping_stats(conn)

    def _report_progress(self, event: str, data: dict[str, Any]) -> None:
        """Emit progress callback event."""
        if self.progress_callback:
            self.progress_callback(event, data)
