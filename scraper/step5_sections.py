"""
Step 5: Sectional times.

Pipeline role:
    Step 1 → fixtures
    Step 2 → races
    Step 3 → results
    Step 4 → horses
    Step 5 → sectionals (THIS FILE)

Behavior:
- Placeholder for future sectional timing ingestion.
- Keeps the ScraperService orchestration contract stable while implementation
  is still pending.

Key design decisions:
✔ Accepts the same batch-oriented call shape as other optional steps
✔ Requires the shared RateLimiter for consistency with the pipeline contract
✔ Returns stable stats so the orchestrator can run safely
"""

import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime, timedelta, UTC

from .rate_limiter import RateLimiter
from .schemas import SectionalStats
from .token_manager import TokenManager

from .config import (
    API_ADD,
    HEADERS_ATR,
    COURSE_NAME_MAPPINGS,
)
from .db_tool import get_connection, init_database


def fetch_section_times(
        token_manager: TokenManager,
        limit: int = 100,
        retry_cooldown_minutes: int = 60,
        max_attempts: int = 5,
        filters: dict | None = None,
        rate_limiter: RateLimiter | None = None,
) -> SectionalStats:
    _ = token_manager, limit, retry_cooldown_minutes, max_attempts, filters

    if rate_limiter is None:
        raise ValueError("RateLimiter is required for Step 5")

    return {
        "sectionals_checked": 0,
        "sectionals_saved": 0,
        "sectionals_failed": 0,
        "sectionals_skipped": 0,
    }


# === # === # === # === # === # === # === # === # === # === # === # === # === # ===
# === # === # === # === # === # === # === # === # === # === # === # === # === # ===
# === # === # === # === # === # === # === # === # === # === # === # === # === # ===

# ============================================================================
# Course Name Conversion
# ============================================================================


def _convert_course_name_to_atr_slug(bha_course_name: str) -> str:
    """
    Convert BHA course name to ATR URL format.

    Uses mapping dictionary for known exceptions, falls back to the first word
    for simple cases.

    Args:
        bha_course_name: Course name from BHA (e.g., "Chelmsford City")

    Returns:
        ATR URL slug (e.g., "Chelmsford")

    Examples:
        _convert_course_name_to_atr_slug("Chelmsford City")
        "Chelmsford"
        _convert_course_name_to_atr_slug("Newcastle (A.W)")
        "Newcastle"
        _convert_course_name_to_atr_slug("Ascot")
        "Ascot"

    Note:
        If a course name is not in COURSE_NAME_MAPPINGS, this function
        uses the first word as a fallback. If scraping fails, check the
        mapping dictionary and add the course manually.
    """
    # Try exact mapping first
    if bha_course_name in COURSE_NAME_MAPPINGS:
        return COURSE_NAME_MAPPINGS[bha_course_name]

    # Fallback: use first word and remove common suffixes
    course_slug = bha_course_name.split()[0]

    # Log for manual review if needed
    print(f"[INFO] Using fallback course slug '{course_slug}' for '{bha_course_name}'")

    return course_slug


# ============================================================================
# Date Formatting
# ============================================================================


def _format_date_for_atr(race_date: str) -> str:
    """
    Convert race date from database format to ATR URL format.

    Args:
        race_date: Date in "YYYY-MM-DD" format (from database)

    Returns:
        Date in "DD-Month-YYYY" format for ATR URLs

    Examples:
        _format_date_for_atr("2025-09-23")
        "23-September-2025"
        _format_date_for_atr("2025-01-05")
        "05-January-2025"

    Note:
        ATR uses full month names (September, not Sep) with leading
        zeros on day numbers (05, not 5).
    """
    date_obj = datetime.strptime(race_date, "%Y-%m-%d")
    return date_obj.strftime("%d-%B-%Y")


# ============================================================================
# ATR Race ID Extraction
# ============================================================================


def _extract_atr_race_id(racecard_url: str) -> str | None:
    """
    Extract ATR's internal race ID from a racecard page.

    ATR embeds their race ID in HTML links like:
    /ajax/racecard/pacesummary/<race_id>

    This function fetches the racecard page and searches for this pattern.

    Args:
        racecard_url: Full ATR racecard URL

    Returns:
        ATR race ID string, or None if not found

    Raises:
        None - failures are logged and return None

    Example:
        url = "https://www.attheraces.com/racecard/Beverley/23-September-2025/1408"
        _extract_atr_race_id(url)
        "1542949"

    Note:
        If this returns None, it likely means:
        - ATR doesn't have data for this race yet (delay)
        - Course name doesn't match ATR's format
        - Race time doesn't match
        - Page structure has changed
    """
    try:
        response = requests.get(racecard_url, headers=HEADERS_ATR, timeout=30)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] Failed to fetch ATR racecard: {e}")
        return None

    # Search for race ID in HTML
    # Pattern: /ajax/racecard/pacesummary/<race_id>
    html_content = response.text
    match = re.search(r"/ajax/racecard/pacesummary/(\d+)", html_content)

    if match:
        race_id = match.group(1)
        print(f"[INFO] Found ATR race ID: {race_id}")
        return race_id

    print("[WARN] ATR race ID not found in page HTML (data may not be available yet)")
    return None


# ============================================================================
# URL Building
# ============================================================================


def _build_atr_racecard_url(
        course_slug: str, date_formatted: str, race_time: str
) -> str:
    """
    Build ATR racecard URL from race parameters.

    Args:
        course_slug: ATR course name (e.g., "Beverley")
        date_formatted: Date in ATR format (e.g., "23-September-2025")
        race_time: Time in HHMM format (e.g., "1408")

    Returns:
        Complete ATR racecard URL

    Example:
        _build_atr_racecard_url("Beverley", "23-September-2025", "1408")
        "https://www.attheraces.com/racecard/Beverley/23-September-2025/1408"
    """
    return API_ADD["racecard"].format(
        course_slug=course_slug, date_formatted=date_formatted, race_time=race_time
    )


def _build_atr_sectionals_url(
        atr_race_id: str, course_slug: str, date_formatted: str, race_time: str
) -> str:
    """
    Build ATR sectionals API URL.

    Args:
        atr_race_id: ATR's internal race ID
        course_slug: ATR course name
        date_formatted: Date in ATR format
        race_time: Time in HHMM format

    Returns:
        Complete ATR sectionals API URL

    Example:
        _build_atr_sectionals_url("1542949", "Beverley", "23-September-2025", "1408")
        "https://www.attheraces.com/ajax/sectionals-razor/1542949/times?page=..."
    """
    return API_ADD["sections"].format(
        atr_race_id=atr_race_id,
        course_slug=course_slug,
        date_formatted=date_formatted,
        race_time=race_time,
    )


# ============================================================================
# Time Conversion
# ============================================================================


def _convert_time_to_seconds(time_str: str) -> float | None:
    """
    Convert ATR time string to seconds (float).

    Handles two formats:
    - "1m 50.42s" → 110.42 seconds
    - "50.42" → 50.42 seconds

    Args:
        time_str: Time string from ATR HTML

    Returns:
        Time in seconds as float, or None if parsing fails

    Examples:
        _convert_time_to_seconds("1m 50.42s")
        110.42
        _convert_time_to_seconds("50.42")
        50.42
        _convert_time_to_seconds("2m 5.3s")
        125.3

    Note:
        Handles optional 's' suffix and flexible whitespace.
        Returns None for invalid/empty strings.
    """
    if not time_str:
        return None

    time_str = time_str.strip()

    # Match pattern: optional minutes, required seconds
    # Pattern: (?:(\d+)m)?\s*(\d+(?:\.\d+)?)s?
    match = re.match(r"(?:(\d+)m)?\s*(\d+(?:\.\d+)?)s?", time_str)

    if not match:
        return None

    minutes = int(match.group(1)) if match.group(1) else 0
    seconds = float(match.group(2))

    return minutes * 60 + seconds


# ============================================================================
# HTML Scraping
# ============================================================================


def _scrape_atr_sectionals(sectionals_url: str) -> dict[str, dict[str, str]]:
    """
    Scrape sectional times from ATR HTML page.

    Parses the ATR sectionals page and extracts:
    - Horse names
    - Official placing
    - Adjusted placing
    - Section times (typically 7-8 sections)
    - Total time
    - Position comments (Front/Mid-division/Rear)

    Args:
        sectionals_url: ATR sectionals API URL

    Returns:
        Dictionary mapping horse names to their sectional data:
        {
            "Mariotto": {
                "official_placing": "1",
                "adj_placing": "8",
                "sectional_times": {
                    "section1": {"time": 21.09, "comment": "Front"},
                    ...
                    "total_time": 110.42
                }
            }
        }

    Returns empty dict if scraping fails or no data available.

    Note:
        - Skips first card-body (duplicate data)
        - Handles variable section counts (7-9 sections typical)
        - Last section is always total_time
        - Times are converted to seconds (float)
    """
    try:
        response = requests.get(sectionals_url, headers=HEADERS_ATR, timeout=30)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"[ERROR] Failed to fetch ATR sectionals: {e}")
        return {}

    html = response.text
    soup = BeautifulSoup(html, "html.parser")

    # Find all card-body sections
    card_bodies = soup.find_all("div", class_="card-body")

    # ATR duplicates first card-body, so we use the second one
    if len(card_bodies) < 2:
        print("[WARN] No second card-body found (expected ATR page structure)")
        return {}

    target_body = card_bodies[1]
    horse_entries = target_body.find_all("div", class_="card-entry")

    if not horse_entries:
        print("[WARN] No horse entries found in ATR sectionals page")
        return {}

    race_data = {}

    for entry in horse_entries:
        # Extract horse name
        horse_tag = entry.find("a", class_="horse__link")
        if not horse_tag:
            continue

        horse_name = horse_tag.get_text(strip=True)

        # Skip duplicates (ATR sometimes lists horses multiple times)
        if horse_name in race_data:
            continue

        # Extract placing data
        horse_info = {
            "official_placing": entry.get("data-officialplacing"),
            "adj_placing": entry.get("data-adjplacing"),
        }

        # Extract sectional times
        sectionals = {}
        sections = entry.find_all("div", class_="card-cell--sectional-time")

        for i, sec in enumerate(sections):
            # Check if this is the total time section (last one)
            section_classes = sec.get("class", [])
            is_total_time = any("sectionals" in cls for cls in section_classes)

            if is_total_time:
                # Special handling for total time
                total_time_div = sec.find("div", class_="card-sectional__inner")
                total_time_str = (
                    total_time_div.get_text(strip=True) if total_time_div else None
                )
                sectionals["total_time"] = _convert_time_to_seconds(total_time_str)
            else:
                # Regular section time
                # Extract numeric time
                time_span = sec.find("span", class_="visible")
                time_val = time_span.get_text(strip=True) if time_span else None

                # Extract position comment (Front/Rear/Mid-division)
                comment_span = sec.find("span", class_="text-pill")
                comment_val = (
                    comment_span.get_text(strip=True) if comment_span else None
                )

                # Convert time to seconds
                time_seconds = _convert_time_to_seconds(time_val) if time_val else None

                # Label section automatically (section1, section2, etc.)
                section_label = f"section{i + 1}"
                sectionals[section_label] = {
                    "time": time_seconds,
                    "comment": comment_val,
                }

        horse_info["sectional_times"] = sectionals
        race_data[horse_name] = horse_info

    print(f"[INFO] Scraped sectional data for {len(race_data)} horse(s)")
    return race_data


# ============================================================================
# Database Operations
# ============================================================================


def _get_race_data_from_database(race_key: str) -> dict[str, str | int] | None:
    """
    Retrieve race details from database needed for ATR scraping.

    Args:
        race_key: Composite key "{race_id}_{division_sequence}"

    Returns:
        Dictionary with race details, or None if not found:
        {
            "race_key": "12345_0",
            "race_id": 12345,
            "division_sequence": 0,
            "race_date": "2025-09-23",
            "race_time": "1408",
            "course_name": "Beverley"
        }

    Note:
        Joins races and fixtures tables to get course_name.
    """
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT
            r.race_key,
            r.race_id,
            r.division_sequence,
            r.race_date,
            r.race_time,
            f.course_name
        FROM races r
        JOIN fixtures f ON r.fixture_id = f.fixture_id
        WHERE r.race_key = ?
        """,
        (race_key,),
    )

    row = cur.fetchone()
    conn.close()

    if not row:
        print(f"[ERROR] Race {race_key} not found in database")
        return None

    return {
        "race_key": row["race_key"],
        "race_id": row["race_id"],
        "division_sequence": row["division_sequence"],
        "race_date": row["race_date"],
        "race_time": row["race_time"],
        "course_name": row["course_name"],
    }


def _normalize_horse_name_for_matching(horse_name: str) -> str:
    """
    Normalize horse name for fuzzy matching between BHA and ATR.

    BHA often adds nationality markers like "(IRE)" or "(FR)" that ATR omits.
    This function removes those markers for better matching.

    Args:
        horse_name: Horse name from either BHA or ATR

    Returns:
        Normalized name for comparison

    Examples:
        _normalize_horse_name_for_matching("Desert King (IRE)")
        "desert king"
        _normalize_horse_name_for_matching("SECRETARIAT")
        "secretariat"

    Note:
        - Removes nationality markers: (IRE), (FR), (USA), etc.
        - Converts to lowercase
        - Strips whitespace
    """
    # Remove nationality markers in parentheses
    normalized = re.sub(r"\s*\([A-Z]+\)\s*", "", horse_name)

    # Convert to lowercase and strip whitespace
    normalized = normalized.lower().strip()

    return normalized


def _find_performance_id_by_horse_name(race_key: str, horse_name: str) -> int | None:
    """
    Find performance_id by matching horse name in race_performances table.

    Uses fuzzy matching to handle name variations between BHA and ATR.

    Args:
        race_key: Race identifier
        horse_name: Horse name from ATR (to match against BHA names)

    Returns:
        performance_id if match found, None otherwise

    Note:
        Matching strategy:
        1. Query joins race_performances with horses to get names
        2. Normalize both ATR and BHA names (removes nationality markers)
        3. Compare normalized names (case-insensitive)
        4. Log warning if no match found
    """
    conn = get_connection()
    cur = conn.cursor()

    # Get all horses in this race with their names
    # Fix: Specify table aliases to avoid ambiguous column names
    cur.execute(
        """
        SELECT rp.performance_id, rp.animal_id, h.racehorse_name
        FROM race_performances rp
        JOIN horses h ON rp.animal_id = h.animal_id
        WHERE rp.race_key = ?
        """,
        (race_key,),
    )

    performances = cur.fetchall()
    conn.close()

    if not performances:
        print(f"[WARN] No performances found for race {race_key}")
        return None

    # Normalize the ATR horse name for matching
    normalized_search = _normalize_horse_name_for_matching(horse_name)

    # Try to match against each horse in this race
    for perf in performances:
        bha_name = perf["racehorse_name"]
        normalized_bha = _normalize_horse_name_for_matching(bha_name)

        if normalized_bha == normalized_search:
            return perf["performance_id"]

    # No match found - log for debugging
    print(
        f"[WARN] No performance match found for ATR horse '{horse_name}' in race {race_key}"
    )
    print(
        f"       Available horses in race: {[p['racehorse_name'] for p in performances]}"
    )
    return None


def _save_section_times_to_database(
        performance_id: int,
        horse_name: str,
        animal_id: str,
        sectionals_data: dict[str, str | int],
) -> int:
    """
    Save section times to section_times table.

    Args:
        performance_id: Foreign key to race_performances
        horse_name: Horse name (for easier querying)
        animal_id: Horse identifier (foreign key to horses)
        sectionals_data: Dictionary with sectional_times data

    Returns:
        Number of section time records saved

    Structure of sectionals_data:
        {
            "official_placing": "1",
            "adj_placing": "8",
            "sectional_times": {
                "section1": {"time": 21.09, "comment": "Front"},
                "section2": {"time": 12.43, "comment": "Front"},
                ...
                "total_time": 110.42
            }
        }

    Database Operation:
        - Deletes existing section times for this performance (if re-running)
        - Inserts new section time records
        - marker_number: 1-8 for sections, 9 for total_time

    Note:
        Uses DELETE + INSERT pattern to handle re-runs cleanly.
        Section count varies by race (typically 7-9 markers total).
    """
    conn = get_connection()
    cur = conn.cursor()

    # Delete existing section times for this performance (if re-running)
    cur.execute("DELETE FROM section_times WHERE performance_id = ?", (performance_id,))

    timestamp = datetime.now(UTC).isoformat(timespec="seconds")
    sectional_times = sectionals_data.get("sectional_times", {})
    official_placing = sectionals_data.get("official_placing")
    adj_placing = sectionals_data.get("adj_placing")

    saved_count = 0

    # Process regular sections (section1, section2, etc.)
    marker_number = 1
    while f"section{marker_number}" in sectional_times:
        section_data = sectional_times[f"section{marker_number}"]

        time_at_marker = section_data.get("time")
        comment = section_data.get("comment")

        if time_at_marker is not None:
            cur.execute(
                """
                INSERT INTO section_times
                (performance_id, animal_id, racehorse_name, marker_number,
                 time_at_marker, comment, official_placing, adj_placing, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    performance_id,
                    animal_id,
                    horse_name,
                    marker_number,
                    time_at_marker,
                    comment,
                    official_placing,
                    adj_placing,
                    timestamp,
                ),
            )
            saved_count += 1

        marker_number += 1

    # Process total_time as the last marker
    total_time = sectional_times.get("total_time")
    if total_time is not None:
        cur.execute(
            """
            INSERT INTO section_times
            (performance_id, animal_id, racehorse_name, marker_number,
             time_at_marker, comment, official_placing, adj_placing, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                performance_id,
                animal_id,
                horse_name,
                marker_number,  # Next marker number (e.g., 9 if 8 sections)
                total_time,
                "Total",  # Label for total time
                official_placing,
                adj_placing,
                timestamp,
            ),
        )
        saved_count += 1

    conn.commit()
    conn.close()

    return saved_count


# ============================================================================
# Main Entry Points
# ============================================================================


def fetch_section_times_for_single_race(race_key: str) -> dict[str, int | str]:
    """
    Fetch and save section times for a single race from ATR.

    This is the main entry point for processing one race at a time.

    Args:
        race_key: Race identifier "{race_id}_{division_sequence}"

    Returns:
        Dictionary with results, or None if failed:
        {
            "race_key": "12345_0",
            "atr_race_id": "1542949",
            "horses_matched": 10,
            "sections_saved": 90
        }

    Raises:
        None - all failures are logged and return None

    Example Usage:
        from scraper.fetch_section_times import fetch_section_times_for_single_race

        result = fetch_section_times_for_single_race("12345_0")
        if result:
            print(f"Saved {result['sections_saved']} section times")

    Pipeline Context:
        This is STEP 4 (final step) of the scraping pipeline:
        Step 1 (fixtures) → Step 2 (races) → Step 3 (results) → Step 4 (this)

        Input from: races + race_performances tables
        Output to: section_times table
        Next step: Django import to PostgreSQL

    Workflow:
        1. Get race details from database
        2. Convert course name to ATR format
        3. Format date for ATR
        4. Build racecard URL and extract ATR race_id
        5. Build sectionals URL and scrape data
        6. Match horses to performances in database
        7. Save section times to database

    Note:
        - ATR data may not be available immediately (delay)
        - Returns None if ATR has no data yet (not an error)
        - Safe to re-run - will update existing data
    """
    # Step 4.1: Ensure database is initialized
    init_database()

    # Step 4.2: Get race details from database
    race_data = _get_race_data_from_database(race_key)
    if not race_data:
        return None

    # Step 4.3: Convert course name to ATR format
    course_slug = _convert_course_name_to_atr_slug(race_data["course_name"])

    # Step 4.4: Format date for ATR
    date_formatted = _format_date_for_atr(race_data["race_date"])

    # Step 4.5: Build racecard URL
    racecard_url = _build_atr_racecard_url(
        course_slug, date_formatted, race_data["race_time"]
    )

    print(f"[INFO] Checking ATR racecard: {racecard_url}")

    # Step 4.6: Extract ATR race_id
    atr_race_id = _extract_atr_race_id(racecard_url)
    if not atr_race_id:
        print(f"[INFO] ATR data not available for race {race_key} (may arrive later)")
        return None

    # Step 4.7: Build sectionals URL
    sectionals_url = _build_atr_sectionals_url(
        atr_race_id, course_slug, date_formatted, race_data["race_time"]
    )

    # Step 4.8: Scrape section times from ATR
    race_sectionals = _scrape_atr_sectionals(sectionals_url)
    if not race_sectionals:
        print(f"[WARN] No sectional data scraped for race {race_key}")
        return None

    # Step 4.9: Match horses and save section times
    horses_matched = 0
    sections_saved = 0

    for horse_name, horse_data in race_sectionals.items():
        # Find performance_id by matching horse name
        performance_id = _find_performance_id_by_horse_name(race_key, horse_name)

        if not performance_id:
            # Horse name mismatch - skip this horse
            continue

        # Get animal_id for this performance
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT animal_id FROM race_performances WHERE performance_id = ?",
            (performance_id,),
        )
        row = cur.fetchone()
        conn.close()

        if not row:
            continue

        animal_id = row["animal_id"]

        # Save section times
        count = _save_section_times_to_database(
            performance_id, horse_name, animal_id, horse_data
        )

        horses_matched += 1
        sections_saved += count

    print(
        f"[INFO] Saved {sections_saved} section times for {horses_matched} horse(s) in race {race_key}"
    )

    return {
        "race_key": race_key,
        "atr_race_id": atr_race_id,
        "horses_matched": horses_matched,
        "sections_saved": sections_saved,
    }


def fetch_section_times_for_all_races(
        only_missing: bool = True, max_age_days: int = 7
) -> dict[str, dict[str, str | int] | None]:
    """
    Fetch and save section times for multiple races from ATR.

    This is a batch processing function that handles multiple races
    in one call. Useful for daily runs or backfilling data.

    Args:
        only_missing: If True, only process races with no section times yet
        max_age_days: Only process races within this many days old
                      (ATR data unlikely available for very old races)

    Returns:
        Dictionary mapping race_key to results:
        {
            "12345_0": {"horses_matched": 10, "sections_saved": 90},
            "12346_0": None,  # ATR data not available
            ...
        }

    Example Usage:
        from scraper.fetch_section_times import fetch_section_times_for_all_races

        # Daily run: check last 7 days for missing data
        results = fetch_section_times_for_all_races(only_missing=True, max_age_days=7)

        # Full backfill: process everything
        results = fetch_section_times_for_all_races(only_missing=False, max_age_days=365)

        # Check results
        for race_key, result in results.items():
            if result:
                print(f"Race {race_key}: {result['sections_saved']} sections")

    Pipeline Context:
        Use this after Steps 1-3 complete to add section times data.

        Typical workflow:
        1. Run Steps 1-3 to get race results
        2. Wait a day or two for ATR data to become available
        3. Run this function to backfill section times
        4. Re-run daily to catch newly available data

    Strategy:
        - Filters races by date to avoid processing very old races
        - Optionally skips races that already have section times
        - Processes races sequentially (not parallel)
        - Continues on error (doesn't stop entire batch)
        - Returns None for races where ATR data unavailable

    Note:
        - ATR data has 1-3 day delay typically
        - Safe to re-run - will update existing data
        - Consider running daily with only_missing=True
    """
    print("=" * 70)
    print("STEP 4: SECTION TIMES (ATR)")
    print("=" * 70)
    print(f"Mode: {'Only missing data' if only_missing else 'All races'}")
    print(f"Max age: {max_age_days} days")

    # Step 4.1: Ensure database is initialized
    init_database()

    # Step 4.2: Calculate date cutoff
    cutoff_date = (datetime.now() - timedelta(days=max_age_days)).strftime("%Y-%m-%d")

    # Step 4.3: Query races from database
    conn = get_connection()
    cur = conn.cursor()

    if only_missing:
        # Only get races that don't have section times yet
        query = """
            SELECT DISTINCT r.race_key, r.race_date, r.race_time, f.course_name
            FROM races r
            JOIN fixtures f ON r.fixture_id = f.fixture_id
            LEFT JOIN race_performances rp ON r.race_key = rp.race_key
            LEFT JOIN section_times st ON rp.performance_id = st.performance_id
            WHERE r.race_date >= ?
              AND st.section_id IS NULL
            ORDER BY r.race_date DESC, r.race_time
        """
    else:
        # Get all races within date range
        query = """
            SELECT r.race_key, r.race_date, r.race_time, f.course_name
            FROM races r
            JOIN fixtures f ON r.fixture_id = f.fixture_id
            WHERE r.race_date >= ?
            ORDER BY r.race_date DESC, r.race_time
        """

    cur.execute(query, (cutoff_date,))
    races = cur.fetchall()
    conn.close()

    if not races:
        print(f"[INFO] No races found matching criteria")
        print("=" * 70)
        return {}

    print(f"[INFO] Found {len(races)} race(s) to process")

    # Step 4.4: Process each race
    results = {}
    successful = 0
    failed = 0
    no_data = 0

    for idx, race_row in enumerate(races, 1):
        race_key = race_row["race_key"]
        race_date = race_row["race_date"]
        race_time = race_row["race_time"]
        course_name = race_row["course_name"]

        print(
            f"\n[{idx}/{len(races)}] Processing: {course_name} on {race_date} at {race_time}"
        )

        try:
            result = fetch_section_times_for_single_race(race_key)

            if result:
                results[race_key] = result
                successful += 1
            else:
                results[race_key] = None
                no_data += 1

        except Exception as e:
            print(f"[ERROR] Failed to process race {race_key}: {e}")
            results[race_key] = None
            failed += 1
            # Continue processing other races

    print("\n" + "=" * 70)
    print(f"STEP 4 COMPLETE:")
    print(f"  - Successful: {successful} races")
    print(f"  - No ATR data: {no_data} races")
    print(f"  - Failed: {failed} races")
    print("=" * 70)

    return results


if __name__ == "__main__":
    # Daily run: check last 7 days for missing data
    results = fetch_section_times_for_all_races(only_missing=True, max_age_days=7)

    # Check results
    for race_key, result in results.items():
        if result:
            print(f"Race {race_key}: {result['sections_saved']} sections")
