"""
Scraper service class for Django integration.
"""
import time
from datetime import datetime, timedelta
from typing import Any

from .step1_fixtures import fetch_fixtures_range
from .step2_races import fetch_races_for_fixtures
from .step3_results import fetch_results_for_races
from .step4_horses import fetch_horse_profiles
from .db_tool import get_connection, get_unscraped_horses, get_scraping_stats
from .token_manager import TokenManager
from .utils import info, warn


class ScraperService:
    """
    Production-grade service for orchestrating multi-step scraping.

    Handles token management, progress tracking, and error recovery.
    """

    def __init__(self, enable_logging: bool = True, rate_limit_seconds: int = 2):
        """
        Initialize the scraper service.

        Args:
            enable_logging: If True, log progress messages
            rate_limit_seconds: Number of seconds to wait between API calls
        """
        self.enable_logging = enable_logging
        self.rate_limit_seconds = rate_limit_seconds
        self._log = info if enable_logging else lambda x: None
        self._warn = warn if enable_logging else lambda x: None

        # FIXED: Initialize filters attribute in __init__
        self.filters: dict[str, Any] = {}

        # Initialize token manager
        self._log("Initializing token manager...")
        self.token_manager = TokenManager()

        # Pre-fetch token to fail fast
        try:
            self.token_manager.get_valid_token()
            self._log("Token ready")
        except Exception as e:
            self._warn(f"Token initialization failed: {e}")
            raise

    @staticmethod
    def _validate_filters(filters: dict | None) -> dict:
        """
        Validate and normalize filter configuration.

        FIXED: Made static method since it doesn't use instance state.

        Args:
            filters: Optional filter dictionary

        Returns:
            Validated filter dictionary

        Raises:
            ValueError: If any filter is invalid
        """
        if filters is None:
            return {}

        valid_filters = {}

        # Fixture-level filters
        if "fixture_types" in filters:
            types = filters["fixture_types"]
            if not isinstance(types, list):
                raise ValueError("fixture_types must be a list")
            valid_types = {"FLAT", "JUMP", "AWT"}
            for ft in types:
                if ft not in valid_types:
                    raise ValueError(f"Invalid fixture_type: {ft}. Must be one of {valid_types}")
            valid_filters["fixture_types"] = types

        if "courses" in filters:
            courses = filters["courses"]
            if not isinstance(courses, list):
                raise ValueError("courses must be a list")
            valid_filters["courses"] = courses

        # Race-level filters
        if "race_type" in filters:
            if filters["race_type"] not in {"FLAT", "JUMP"}:
                raise ValueError("race_type must be 'FLAT' or 'JUMP'")
            valid_filters["race_type"] = filters["race_type"]

        if "min_distance" in filters:
            if not isinstance(filters["min_distance"], int) or filters["min_distance"] < 0:
                raise ValueError("min_distance must be a positive integer")
            valid_filters["min_distance"] = filters["min_distance"]

        if "max_distance" in filters:
            if not isinstance(filters["max_distance"], int) or filters["max_distance"] < 0:
                raise ValueError("max_distance must be a positive integer")
            valid_filters["max_distance"] = filters["max_distance"]

        if "race_classes" in filters:
            classes = filters["race_classes"]
            if not isinstance(classes, list):
                raise ValueError("race_classes must be a list")
            for rc in classes:
                if not isinstance(rc, int) or rc < 1 or rc > 7:
                    raise ValueError(f"Invalid race_class: {rc}. Must be 1-7")
            valid_filters["race_classes"] = classes

        return valid_filters

    def scrape_date_range(
            self,
            dates: list[str],
            run_horses: bool = True,
            batch_size: dict[str, int] | None = None,
            filters: dict | None = None
    ) -> dict[str, Any]:
        """
        Complete scraping workflow: fixtures → races → results → horses.

        Args:
            dates: List of date strings in "YYYY-MM-DD" format
            run_horses: If True, also scrape horse profiles (Step 4)
            batch_size: Dict with limits for each step, e.g.:
                {"races": 50, "results": 100, "horses": 100}
            filters: Dict with optional filtering criteria

        Returns:
            Dictionary with:
                - success: bool
                - stats: dict with counts for each step
                - error: str | None
        """
        if not dates:
            raise ValueError("No dates provided")

        # Validate dates
        try:
            for date_str in dates:
                datetime.fromisoformat(date_str)
        except ValueError as e:
            raise ValueError(f"Invalid date format: {e}") from None

        # Default batch sizes
        if batch_size is None:
            batch_size = {"races": 50, "results": 100, "horses": 100}

        # Initialize stats
        stats = {
            "dates_requested": len(dates),
            "fixtures_saved": 0,
            "races_saved": 0,
            "performances_saved": 0,
            "horses_saved": 0,
            "fixtures_completed": 0,
            "races_completed": 0,
        }

        # FIXED: Now calls static method and assigns to instance attribute
        try:
            self.filters = self._validate_filters(filters)
        except ValueError as e:
            self._warn(f"Filter validation failed: {e}")
            raise

        try:
            start_date = dates[0]
            end_date = dates[-1]

            # STEP 1: Fetch fixtures
            self._log("=" * 60)
            self._log(f"STEP 1: Fetching fixtures ({start_date} to {end_date})")
            self._log("=" * 60)

            fixtures_result = fetch_fixtures_range(
                start_date=start_date, end_date=end_date, token_manager=self.token_manager, filters=self.filters
            )

            stats["fixtures_saved"] = fixtures_result.get("fixtures_saved", 0)
            self._log(f"✓ Step 1 complete: {stats['fixtures_saved']} fixtures saved")

            if stats["fixtures_saved"] == 0:
                self._warn("No fixtures found - stopping workflow")
                return {
                    "success": True,
                    "stats": stats,
                    "error": None,
                }

            # STEP 2: Fetch races (batched with filters)
            self._log("\n" + "=" * 60)
            self._log("STEP 2: Fetching races for fixtures")
            if self.filters.get("fixture_types"):
                self._log(f"  Filtering: fixture_types={self.filters['fixture_types']}")
            if self.filters.get("courses"):
                self._log(f"  Filtering: courses={self.filters['courses']}")
            self._log("=" * 60)

            races_result = self._run_batched_step(
                fetch_races_for_fixtures,
                batch_size["races"],
                "races",
                filters=self.filters
            )

            stats["races_saved"] = races_result["races_saved"]
            stats["fixtures_completed"] = races_result["fixtures_completed"]
            self._log(f"✓ Step 2 complete: {stats['races_saved']} races saved")

            if stats["races_saved"] == 0:
                self._warn("No races found - stopping workflow")
                return {
                    "success": True,
                    "stats": stats,
                    "error": None,
                }

            # STEP 3: Fetch results (batched)
            self._log("\n" + "=" * 60)
            self._log("STEP 3: Fetching results for races")
            if self.filters.get("race_type"):
                self._log(f"  Filtering: race_type={self.filters['race_type']}")
            if self.filters.get("min_distance") or self.filters.get("max_distance"):
                self._log(
                    f"  Filtering: distance={self.filters.get('min_distance')}-{self.filters.get('max_distance')}m")
            self._log("=" * 60)

            results_result = self._run_batched_step(
                fetch_results_for_races,
                batch_size["results"],
                "results",
                filters=self.filters
            )

            stats["performances_saved"] = results_result["results_saved"]
            stats["races_completed"] = results_result["races_completed"]
            self._log(f"✓ Step 3 complete: {stats['performances_saved']} performances saved")

            # STEP 4: Fetch horse profiles (optional, batched)
            if run_horses:
                self._log("\n" + "=" * 60)
                self._log("STEP 4: Fetching horse profiles")
                self._log("=" * 60)

                horses_result = self._run_batched_step(
                    fetch_horse_profiles, batch_size["horses"], "horses"
                )

                stats["horses_saved"] = horses_result.get("horses_saved", 0)
                self._log(f"✓ Step 4 complete: {stats['horses_saved']} horses saved")

            # Final summary
            self._log("\n" + "=" * 60)
            self._log("WORKFLOW COMPLETE")
            self._log("=" * 60)
            self._log_summary(stats)

            return {
                "success": True,
                "stats": stats,
                "error": None,
            }

        except Exception as e:
            error_msg = f"Scraping failed: {e}"
            self._warn(error_msg)
            return {
                "success": False,
                "stats": stats,
                "error": error_msg,
            }

    def _run_batched_step(
            self,
            step_function,
            batch_size: int,
            step_name: str,
            filters: dict = None
    ) -> dict[str, int]:
        """
        Run a step function in batches until no more items to process.

        Args:
            step_function: The step function to call
            batch_size: Number of items per batch
            step_name: Name for logging
            filters: Optional filters to pass to step function

        Returns:
            Aggregated stats from all batches
        """
        total_stats = {
            "races_saved": 0,
            "results_saved": 0,
            "fixtures_completed": 0,
            "races_completed": 0,
            "horses_saved": 0,
        }

        batch_num = 0

        while True:
            batch_num += 1
            self._log(f"  Processing batch {batch_num} ({batch_size} items)...")

            try:
                # Run one batch with filters
                batch_stats = step_function(
                    token_manager=self.token_manager,
                    limit=batch_size,
                    filters=filters
                )
                # Check if any work was done
                items_processed = batch_stats.get(f"{step_name}_saved", 0)
                if items_processed == 0:
                    self._log(f"  Batch {batch_num}: No more items to process")
                    break

                # Aggregate stats
                for key, value in batch_stats.items():
                    if key in total_stats:
                        total_stats[key] += value

                self._log(f"  Batch {batch_num}: Processed {items_processed} items")

                # Progress logging for large batches
                if batch_num % 10 == 0:
                    self._log(f"  Progress: {batch_num} batches completed")

                time.sleep(self.rate_limit_seconds)

            except Exception as e:
                self._warn(f"Batch {batch_num} failed: {e}")
                raise

        return total_stats

    def resume_scraping(self, run_horses: bool = True, batch_size: dict = None):
        """
        Resume scraping from where it left off.

        Automatically detects which steps need completion:
        - If unprocessed fixtures → run Step 2
        - If unprocessed races → run Step 3
        - If missing horses → run Step 4
        """
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

        # Step 2: Races
        if progress["fixtures"]["remaining"] > 0:
            self._log(f"Resuming Step 2: {progress['fixtures']['remaining']} fixtures need races")
            races_result = self._run_batched_step(
                fetch_races_for_fixtures, batch_size["races"], "races"
            )
            stats["races_saved"] = races_result["races_saved"]
            stats["fixtures_completed"] = races_result["fixtures_completed"]

        # Step 3: Results
        if progress["races"]["remaining"] > 0:
            self._log(f"Resuming Step 3: {progress['races']['remaining']} races need results")
            results_result = self._run_batched_step(
                fetch_results_for_races, batch_size["results"], "results"
            )
            stats["performances_saved"] = results_result["results_saved"]
            stats["races_completed"] = results_result["races_completed"]

        # Step 4: Horses
        if run_horses:
            # Check how many horses are missing
            with get_connection() as conn:
                missing = get_unscraped_horses(conn, limit=1000000)  # Get count

            if len(missing) > 0:
                self._log(f"Resuming Step 4: {len(missing)} horses need profiles")
                horses_result = self._run_batched_step(
                    fetch_horse_profiles, batch_size["horses"], "horses"
                )
                stats["horses_saved"] = horses_result["horses_saved"]

        return {"success": True, "stats": stats, "error": None}

    def _log_summary(self, stats: dict[str, int]) -> None:
        """Log final summary statistics."""
        self._log(f"Fixtures saved:      {stats['fixtures_saved']:,}")
        self._log(f"Fixtures completed:  {stats['fixtures_completed']:,}")
        self._log(f"Races saved:         {stats['races_saved']:,}")
        self._log(f"Races completed:     {stats['races_completed']:,}")
        self._log(f"Performances saved:  {stats['performances_saved']:,}")
        if stats.get("horses_saved"):
            self._log(f"Horses saved:        {stats['horses_saved']:,}")

    def scrape_single_date(self, date: str, **kwargs) -> dict[str, Any]:
        """Convenience method for a single date."""
        return self.scrape_date_range(dates=[date], **kwargs)

    def scrape_days_back(self, days_back: int, **kwargs) -> dict[str, Any]:
        """Scrape last N days (inclusive)."""
        if days_back < 0:
            raise ValueError("days_back must be >= 0")

        today = datetime.now().date()
        start_date = today - timedelta(days=days_back)

        dates = []
        current = start_date
        while current <= today:
            dates.append(current.strftime("%Y-%m-%d"))
            current += timedelta(days=1)

        self._log(f"Scraping {len(dates)} days: {dates[0]} to {dates[-1]}")
        return self.scrape_date_range(dates=dates, **kwargs)

    def get_progress(self) -> dict[str, Any]:
        """
        Get current scraping progress from database.
        """
        with get_connection() as conn:
            stats = get_scraping_stats(conn)

        return stats