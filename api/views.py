"""
Django views for the API app - Updated with stop functionality
"""

import csv
import json
import logging
import sqlite3
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from typing import TYPE_CHECKING, Any

from django.conf import settings
from django.db import connection
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods

from .models import FilterPreset, ScrapeJob
from .tasks import start_scrape_job
from .course_list import available_courses

if TYPE_CHECKING:
    from django.http import HttpRequest


def _ok(data: Any = None, message: str | None = None, status: int = 200) -> JsonResponse:
    payload: dict[str, Any] = {"success": True}
    if data is not None:
        payload["data"] = data
    if message is not None:
        payload["message"] = message
    return JsonResponse(payload, status=status)


def _fail(error: str, status: int = 400, data: Any = None) -> JsonResponse:
    payload: dict[str, Any] = {"success": False, "error": error}
    if data is not None:
        payload["data"] = data
    return JsonResponse(payload, status=status)


def _normalize_start_filters(data: dict[str, Any]) -> dict[str, Any]:
    filters: dict[str, Any] = {}

    fixture_types = data.get("fixture_types")
    if fixture_types:
        filters["fixture_types"] = (
            fixture_types if isinstance(fixture_types, list) else [fixture_types]
        )

    courses = data.get("courses")
    if courses:
        filters["courses"] = courses if isinstance(courses, list) else [courses]

    race_type = data.get("race_type")
    if race_type:
        filters["race_type"] = race_type

    minimum_distance = data.get("minimum_distance")
    if minimum_distance not in (None, ""):
        filters["minimum_distance"] = int(minimum_distance)

    maximum_distance = data.get("maximum_distance")
    if maximum_distance not in (None, ""):
        filters["maximum_distance"] = int(maximum_distance)

    race_classes = data.get("race_classes")
    if race_classes:
        if isinstance(race_classes, list):
            filters["race_classes"] = [int(value) for value in race_classes]
        else:
            filters["race_classes"] = [int(race_classes)]

    return filters


@ensure_csrf_cookie
def index(request: "HttpRequest"):
    """Main page with a scraper form."""
    # Get recent jobs for display
    recent_jobs = ScrapeJob.objects.all()[:10]
    presets = FilterPreset.objects.all()

    return render(
        request,
        "api/index.html",
        {
            "recent_jobs": recent_jobs,
            "presets": presets,
            "available_courses": sorted(available_courses),
        },
    )


@require_http_methods(["POST"])
def start_scrape(request: "HttpRequest"):
    """Start a new scraping job."""
    try:
        data = json.loads(request.body)
        days_back = int(data.get("days_back", 7))

        if days_back < 0:
            return _fail("days_back must be >= 0", status=400)

        if days_back > 1095:
            return _fail("days_back cannot exceed 1095", status=400)

        filters = _normalize_start_filters(data)

        job_id = start_scrape_job(days_back=days_back, filters=filters or None)

        return _ok(
            data={"job_id": job_id, "days_back": days_back, "filters": filters},
            message=f"Scraping job started for {days_back} days",
        )

    except json.JSONDecodeError:
        return _fail("Invalid JSON in request body", status=400)
    except ValueError as exc:
        return _fail(f"Invalid value: {exc}", status=400)
    except Exception as exc:
        return _fail(str(exc), status=500)


@require_http_methods(["POST"])
def stop_scrape(_request: "HttpRequest", job_id: str):
    """
    Stop a running scrape job.

    Sets a stop flag that the worker checks periodically.
    The job status is updated to 'stopped' in the database.
    """
    try:
        job = ScrapeJob.objects.get(job_id=job_id)

        if job.status not in ["running", "pending"]:
            return _fail(f"Nie można zatrzymać zadania ze statusem '{job.status}'", status=400)

        from api.tasks import _stop_flags

        _stop_flags[job_id] = True

        job.status = "stopped"
        job.status_message = "Zatrzymane przez użytkownika"
        job.error_message = "Użytkownik zatrzymał zadanie"
        job.save()

        return _ok(data={"message": "Zadanie zostało zatrzymane"})

    except ScrapeJob.DoesNotExist:
        return _fail("Nie znaleziono zadania", status=404)
    except Exception as exc:
        logger = logging.getLogger(__name__)
        logger.error("Error stopping job %s: %s", job_id, exc, exc_info=True)
        return _fail("Błąd podczas zatrzymywania zadania", status=500)


@require_http_methods(["GET"])
def get_preset(_request: "HttpRequest", preset_id: int):
    """Get preset configuration."""
    try:
        preset = FilterPreset.objects.get(id=preset_id)
        return _ok(
            data={
                "id": preset.id,
                "name": preset.name,
                "description": preset.description,
                "fixture_types": preset.fixture_types,
                "courses": preset.courses,
                "race_type": preset.race_type,
                "minimum_distance": preset.minimum_distance,
                "maximum_distance": preset.maximum_distance,
                "race_classes": preset.race_classes,
            }
        )
    except FilterPreset.DoesNotExist:
        return _fail("Preset not found", status=404)


@require_http_methods(["POST"])
def save_preset(request: "HttpRequest"):
    """Save a new custom preset."""
    try:
        data = json.loads(request.body)

        if not data.get("name"):
            return _fail("Preset name is required", status=400)

        if FilterPreset.objects.filter(name=data["name"]).exists():
            return _fail("A preset with this name already exists", status=400)

        preset = FilterPreset.objects.create(
            name=data["name"],
            description=data.get("description", ""),
            fixture_types=data.get("fixture_types", []),
            courses=data.get("courses", []),
            race_type=data.get("race_type", ""),
            minimum_distance=data.get("minimum_distance"),
            maximum_distance=data.get("maximum_distance"),
            race_classes=data.get("race_classes", []),
            is_system=False,
        )

        return _ok(data={"preset_id": preset.id, "message": f'Preset "{preset.name}" saved'})

    except json.JSONDecodeError:
        return _fail("Invalid JSON in request body", status=400)
    except Exception as exc:
        return _fail(str(exc), status=500)


@require_http_methods(["GET"])
def job_status(_request: "HttpRequest", job_id: str):
    """Get status of a scraping job."""
    job = get_object_or_404(ScrapeJob, job_id=job_id)

    return _ok(
        data={
            "job_id": job.job_id,
            "status": job.status,
            "days_back": job.days_back,
            "current_step": job.current_step,
            "total_steps": job.total_steps,
            "status_message": job.status_message,
            "progress_percent": job.progress_percent,
            "stats": job.stats,
            "error_message": job.error_message,
            "created_at": job.created_at.isoformat(),
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
            "duration": job.duration(),
        }
    )


@require_http_methods(["GET"])
def job_list(_request: "HttpRequest"):
    """List all scraping jobs."""
    jobs = ScrapeJob.objects.all()[:50]

    return _ok(
        data=[
            {
                "job_id": job.job_id,
                "status": job.status,
                "days_back": job.days_back,
                "created_at": job.created_at.isoformat(),
                "stats": job.stats,
                "status_message": job.status_message,
                "progress_percent": job.progress_percent,
            }
            for job in jobs
        ]
    )


@ensure_csrf_cookie
def database_management(request: "HttpRequest"):
    """Database management page - view stats and wipe databases."""

    # Get PostgreSQL stats
    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM api_fixture")
        pg_fixtures = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM api_race")
        pg_races = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM api_horse")
        pg_horses = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM api_performance")
        pg_performances = cursor.fetchone()[0]

    pg_stats = {
        "fixtures": pg_fixtures,
        "races": pg_races,
        "horses": pg_horses,
        "performances": pg_performances,
        "total": pg_fixtures + pg_races + pg_horses + pg_performances,
    }

    # Get SQLite buffer stats
    sqlite_stats = {"fixtures": 0, "races": 0, "horses": 0, "performances": 0, "total": 0}
    try:
        db_path = Path(settings.SCRAPER_DB_PATH)
        if db_path.exists():
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM fixtures")
            sqlite_stats["fixtures"] = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM races")
            sqlite_stats["races"] = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM horses")
            sqlite_stats["horses"] = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM race_performances")
            sqlite_stats["performances"] = cursor.fetchone()[0]

            sqlite_stats["total"] = sum(
                [
                    sqlite_stats["fixtures"],
                    sqlite_stats["races"],
                    sqlite_stats["horses"],
                    sqlite_stats["performances"],
                ]
            )

            conn.close()
    except Exception as e:
        print(f"Error reading SQLite stats: {e}")

    return render(
        request, "api/database.html", {"pg_stats": pg_stats, "sqlite_stats": sqlite_stats}
    )


@require_http_methods(["POST"])
def wipe_postgresql(_request: "HttpRequest"):
    """Wipe all data from PostgreSQL main database."""
    try:
        from api.models import Fixture, Horse, Performance, Race

        # Delete it in the correct order (foreign keys)
        Performance.objects.all().delete()
        Race.objects.all().delete()
        Horse.objects.all().delete()
        Fixture.objects.all().delete()

        return _ok(data={"message": "Baza PostgreSQL została wyczyszczona"})
    except Exception as exc:
        return _fail(str(exc), status=500)


@require_http_methods(["POST"])
def wipe_sqlite_buffer(_request: "HttpRequest"):
    """Wipe all data from SQLite buffer database."""
    try:
        db_path = Path(settings.SCRAPER_DB_PATH)

        if not db_path.exists():
            return _fail("Buffer database not found", status=404)

        conn = sqlite3.connect(str(db_path))
        try:
            cursor = conn.cursor()

            cursor.execute("DELETE FROM section_times")
            cursor.execute("DELETE FROM race_performances")
            cursor.execute("DELETE FROM horses")
            cursor.execute("DELETE FROM races")
            cursor.execute("DELETE FROM fixtures")
            cursor.execute("DELETE FROM scrape_log")

            cursor.execute("DELETE FROM sqlite_sequence")

            conn.commit()
        finally:
            conn.close()

        return _ok(data={"message": "Bufor SQLite został wyczyszczony"})
    except Exception as exc:
        return _fail(str(exc), status=500)


@ensure_csrf_cookie
def browse_data(request: "HttpRequest"):
    """Data browsing page - search horses and races."""
    return render(request, "api/browse.html")


@require_http_methods(["GET"])
def search_horse(request: "HttpRequest"):
    """Search for a horse by name and return its race history."""
    query = request.GET.get("q", "").strip()

    if not query or len(query) < 2:
        return _fail("Query too short (minimum 2 characters)", status=400)

    try:
        from api.models import Horse, Performance

        horses = Horse.objects.filter(
            Q(name__icontains=query) | Q(raw__racehorse_name__icontains=query)
        )[:10]

        results = []

        for horse in horses:
            horse_data = {
                "id": horse.id,
                "name": horse.name or horse.raw.get("racehorse_name", "Unknown"),
                "dob": horse.dob.isoformat() if horse.dob else horse.raw.get("dob"),
                "age": horse.raw.get("age"),
                "sex": horse.raw.get("sex"),
                "trainer": horse.raw.get("trainer"),
                "total_wins": horse.raw.get("total_wins", 0),
                "total_runs": horse.raw.get("total_runs", 0),
                "total_places": horse.raw.get("total_places", 0),
            }

            performances = Performance.objects.filter(horse=horse).select_related(
                "race", "race__fixture"
            )

            race_history = []
            for perf in performances:
                if perf.race and perf.race.fixture:
                    race_history.append(
                        {
                            "race_date": perf.race.raw.get("race_date"),
                            "race_time": perf.race.raw.get("race_time"),
                            "course_name": perf.race.fixture.raw.get("course_name"),
                            "distance_value": perf.race.raw.get("distance_value"),
                            "distance_text": perf.race.raw.get("distance_text"),
                            "race_class": perf.race.raw.get("race_class"),
                            "age_limit": perf.race.raw.get("age_limit"),
                            "cloth_number": perf.raw.get("cloth_number"),
                            "final_position": perf.raw.get("final_position"),
                            "finish_time": perf.raw.get("finish_time"),
                            "jockey_name": perf.raw.get("jockey_name"),
                        }
                    )

            horse_data["race_history"] = race_history
            results.append(horse_data)

        return _ok(data={"count": len(results), "horses": results})

    except Exception as exc:
        return _fail(str(exc), status=500)


@require_http_methods(["GET"])
def search_races(request: "HttpRequest"):
    """Search for races by date."""
    date_str = request.GET.get("date", "").strip()

    if not date_str:
        return _fail("Date is required", status=400)

    try:
        from django.utils.dateparse import parse_date

        from api.models import Race

        search_date = parse_date(date_str)
        if not search_date:
            return _fail("Invalid date format (use YYYY-MM-DD)", status=400)

        races = Race.objects.filter(raw__race_date=date_str).select_related("fixture")[:50]

        results = []
        for race in races:
            if race.fixture:
                results.append(
                    {
                        "race_id": race.id,
                        "external_id": race.external_id,
                        "race_date": race.raw.get("race_date"),
                        "race_time": race.raw.get("race_time"),
                        "course_name": race.fixture.raw.get("course_name"),
                        "distance_value": race.raw.get("distance_value"),
                        "distance_text": race.raw.get("distance_text"),
                        "race_class": race.raw.get("race_class"),
                        "age_limit": race.raw.get("age_limit"),
                        "horse_count": race.raw.get("horse_count", 0),
                    }
                )

        return _ok(data={"date": date_str, "count": len(results), "races": results})

    except Exception as exc:
        return _fail(str(exc), status=500)


@require_http_methods(["GET"])
def race_detail(_request: "HttpRequest", race_id: int):
    """Get detailed information about a specific race."""
    try:
        from api.models import Performance, Race

        race = get_object_or_404(Race, id=race_id)

        race_info = {
            "race_id": race.id,
            "external_id": race.external_id,
            "race_date": race.raw.get("race_date"),
            "race_time": race.raw.get("race_time"),
            "course_name": race.fixture.raw.get("course_name") if race.fixture else "Unknown",
            "distance_value": race.raw.get("distance_value"),
            "distance_text": race.raw.get("distance_text"),
            "race_class": race.raw.get("race_class"),
            "age_limit": race.raw.get("age_limit"),
            "race_criteria_type": race.raw.get("race_criteria_type"),
        }

        performances = Performance.objects.filter(race=race).select_related("horse")

        horses = []
        for perf in performances:
            horses.append(
                {
                    "horse_name": perf.horse.name if perf.horse else perf.raw.get("horse_name"),
                    "cloth_number": perf.raw.get("cloth_number"),
                    "final_position": perf.raw.get("final_position"),
                    "finish_time": perf.raw.get("finish_time"),
                    "jockey_name": perf.raw.get("jockey_name"),
                    "trainer_name": perf.raw.get("trainer_name"),
                    "drawn_stall": perf.raw.get("drawn_stall"),
                    "age": perf.raw.get("age"),
                    "sex": perf.raw.get("sex"),
                }
            )

        horses.sort(
            key=lambda x: (
                int(x["final_position"])
                if x["final_position"] and x["final_position"].isdigit()
                else 999
            )
        )

        return _ok(data={"race": race_info, "horses": horses, "total_horses": len(horses)})

    except Exception as exc:
        return _fail(str(exc), status=500)


@ensure_csrf_cookie
def reports(request: "HttpRequest"):
    """Reports generation page."""
    from api.models import Fixture

    # Get available courses for dropdown
    courses = Fixture.objects.values_list("raw__course_name", flat=True).distinct()
    unique_courses = sorted({course for course in courses if course})

    return render(request, "api/reports.html", {"available_courses": unique_courses})


@require_http_methods(["POST"])
def generate_winning_positions_report(request: "HttpRequest"):
    """
    Generate a report analyzing winning starting positions.

    Shows which cloth numbers (starting positions) most frequently
    finish in the top 4 positions across filtered races.
    """
    try:
        data = json.loads(request.body)

        # Extract filters
        date_from = data.get("date_from")
        date_to = data.get("date_to")
        course_name = data.get("course_name")
        min_distance = data.get("min_distance")
        max_distance = data.get("max_distance")

        # ============================================
        # VALIDATION: Dates are required
        # ============================================
        if not date_from or not date_to:
            return JsonResponse({"error": "Zakres dat jest wymagany"}, status=400)

        # ============================================
        # VALIDATION: Date format and order
        # ============================================
        try:
            from datetime import datetime

            # Parse dates
            from_dt = datetime.strptime(date_from, "%Y-%m-%d")
            to_dt = datetime.strptime(date_to, "%Y-%m-%d")

            # Check order
            if from_dt > to_dt:
                return JsonResponse(
                    {
                        "error": f"Nieprawidłowy zakres dat: data początkowa ({date_from}) "
                                 f"jest późniejsza niż data końcowa ({date_to}). "
                                 f"Ustaw daty w prawidłowej kolejności."
                    },
                    status=400,
                )

            # Check if the range isn't too large (optional)
            days_diff = (to_dt - from_dt).days
            if days_diff > 1095:  # 3 years
                return _fail("Maksymalny zakres to 1095 dni (3 lata).", status=400)

        except ValueError:
            return _fail(
                "Nieprawidłowy format daty. Użyj formatu YYYY-MM-DD (np. 2026-02-14)", status=400
            )

        # ============================================
        # VALIDATION: Distance order
        # ============================================
        if min_distance and max_distance:
            try:
                min_d = int(min_distance)
                max_d = int(max_distance)

                if min_d > max_d:
                    return _fail(
                        f"Nieprawidłowy zakres dystansu: minimum ({min_d}y) "
                        f"jest większe niż maximum ({max_d}y).",
                        status=400,
                    )

                # Optional: Check reasonable ranges
                if min_d < 0 or max_d > 10000:
                    return _fail("Dystans musi być w zakresie 0-10000 jardów", status=400)

            except ValueError:
                return _fail("Dystans musi być liczbą całkowitą", status=400)

        # ============================================
        # REST OF THE FUNCTION (unchanged)
        # ============================================
        from collections import defaultdict

        from django.db.models import Q

        from api.models import Performance, Race

        # Build query for races
        race_query = Q()
        race_query &= Q(raw__race_date__gte=date_from)
        race_query &= Q(raw__race_date__lte=date_to)

        if course_name:
            race_query &= Q(fixture__raw__course_name=course_name) | Q(raw__course_name=course_name)

        if min_distance:
            try:
                race_query &= Q(raw__distance_value__gte=int(min_distance))
            except (ValueError, TypeError):
                pass

        if max_distance:
            try:
                race_query &= Q(raw__distance_value__lte=int(max_distance))
            except (ValueError, TypeError):
                pass

        races = Race.objects.filter(race_query)
        total_races = races.count()

        if total_races == 0:
            return _fail(
                "Nie znaleziono wyścigów spełniających kryteria. "
                "Spróbuj rozszerzyć zakres dat lub zmienić filtry."
            )

        position_counts = defaultdict(lambda: {1: 0, 2: 0, 3: 0, 4: 0})

        race_ids = [race.id for race in races]
        all_performances = Performance.objects.filter(race_id__in=race_ids)

        total_performances = 0
        valid_performances = 0

        for perf in all_performances:
            total_performances += 1

            cloth_number = perf.raw.get("cloth_number")
            final_position = perf.raw.get("final_position")

            if not cloth_number or not final_position:
                continue

            try:
                pos = int(final_position)
                if 1 <= pos <= 4:
                    position_counts[cloth_number][pos] += 1
                    valid_performances += 1
            except (ValueError, TypeError):
                continue

        if not position_counts:
            return _fail(
                f"Nie znaleziono danych o pozycjach startowych w {total_races} "
                f"wyścigach ({total_performances} występów)."
            )

        results = []
        for cloth_number, positions in position_counts.items():
            results.append(
                {
                    "cloth_number": cloth_number,
                    "first": positions[1],
                    "second": positions[2],
                    "third": positions[3],
                    "fourth": positions[4],
                    "total_top_4": sum(positions.values()),
                }
            )

        results.sort(key=lambda x: (x["first"], x["second"], x["third"], x["fourth"]), reverse=True)

        return _ok(
            data={
                "success": True,
                "report": {
                    "filters": {
                        "date_from": date_from,
                        "date_to": date_to,
                        "course_name": course_name or "Wszystkie",
                        "min_distance": min_distance,
                        "max_distance": max_distance,
                    },
                    "total_races": total_races,
                    "total_performances": total_performances,
                    "valid_performances": valid_performances,
                    "results": results,
                },
            }
        )

    except json.JSONDecodeError:
        return _fail("Nieprawidłowy format danych JSON", status=400)

    except Exception as exc:
        logger = logging.getLogger(__name__)
        logger.error("Error generating report: %s", exc, exc_info=True)

        return _fail(
            "Wystąpił błąd podczas generowania raportu. Spróbuj ponownie lub skontaktuj się z administratorem.",
            status=500,
        )


@require_http_methods(["POST"])
def export_report_csv(request: "HttpRequest"):
    """Export winning positions report to CSV."""
    try:
        data = json.loads(request.body)

        report_data = data.get("report_data")
        if not report_data:
            return _fail("No report data provided", status=400)

        # Create CSV
        output = StringIO()
        writer = csv.writer(output)

        # Header with report info
        writer.writerow(["RAPORT: WYGRYWAJĄCE POZYCJE STARTOWE"])
        writer.writerow([])
        writer.writerow(
            [
                "Okres:",
                f"{report_data['filters']['date_from']} do {report_data['filters']['date_to']}",
            ]
        )
        writer.writerow(["Tor:", report_data["filters"]["course_name"]])

        if report_data["filters"].get("min_distance") or report_data["filters"].get("max_distance"):
            min_d = report_data["filters"].get("min_distance", "-")
            max_d = report_data["filters"].get("max_distance", "-")
            writer.writerow(["Dystans:", f"{min_d} - {max_d} jardów"])

        writer.writerow(["Liczba wyścigów:", report_data["total_races"]])
        writer.writerow([])

        # Table header
        writer.writerow(
            ["Numer Startowy", "1. miejsce", "2. miejsce", "3. miejsce", "4. miejsce", "Suma Top 4"]
        )

        # Data rows
        for row in report_data["results"]:
            writer.writerow(
                [
                    row["cloth_number"],
                    row["first"],
                    row["second"],
                    row["third"],
                    row["fourth"],
                    row["total_top_4"],
                ]
            )

        # Create response
        response = HttpResponse(output.getvalue(), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = (
            f'attachment; filename="raport_pozycje_startowe_{datetime.now(UTC).strftime("%Y%m%d_%H%M%S")}.csv"'
        )

        # Add BOM for Excel compatibility with Polish characters
        response.write("\ufeff")

        return response

    except Exception as e:
        return _fail(str(e), status=500)
