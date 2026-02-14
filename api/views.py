"""
Django views for the API app - Updated with stop functionality
"""

import json
from typing import TYPE_CHECKING

from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods

from .models import FilterPreset, ScrapeJob
from .tasks import start_scrape_job, stop_scrape_job

if TYPE_CHECKING:
    from django.http import HttpRequest


@ensure_csrf_cookie
def index(request: "HttpRequest"):
    """Main page with a scraper form."""
    # Get recent jobs for display
    recent_jobs = ScrapeJob.objects.all()[:10]
    presets = FilterPreset.objects.all()

    # Hardcoded list of available courses
    available_courses = [
        "Ascot",
        "Newmarket",
        "York",
        "Goodwood",
        "Epsom",
        "Doncaster",
        "Chester",
        "Haydock Park",
        "Sandown Park",
        "Newbury",
        "Curragh",
        "Newcastle",
        "Kempton Park",
        "Lingfield Park",
        "Cheltenham",
        "Aintree",
        "Carlisle",
        "Catterick Bridge",
        "Chepstow",
        "Exeter",
        "Fakenham",
        "Ffos Las",
        "Fontwell Park",
        "Hexham",
        "Hereford",
        "Huntingdon",
        "Kelso",
        "Leicester",
        "Ludlow",
        "Market Rasen",
        "Musselburgh",
        "Newton Abbot",
        "Perth",
        "Plumpton",
        "Pontefract",
        "Redcar",
        "Ripon",
        "Salisbury",
        "Sedgefield",
        "Southwell",
        "Stratford-on-Avon",
        "Taunton",
        "Thirsk",
        "Towcester",
        "Uttoxeter",
        "Warwick",
        "Wetherby",
        "Wincanton",
        "Windsor",
        "Wolverhampton",
        "Worcester",
    ]

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
            return JsonResponse({"error": "days_back must be >= 0"}, status=400)

        if days_back > 1095:
            return JsonResponse({"error": "days_back cannot exceed 1095"}, status=400)

        # Build filters from form data
        filters = {}

        if data.get("fixture_types"):
            filters["fixture_types"] = data["fixture_types"]

        if data.get("courses"):
            filters["courses"] = data["courses"]

        if data.get("race_type"):
            filters["race_type"] = data["race_type"]

        if data.get("minimum_distance"):
            filters["minimum_distance"] = int(data["minimum_distance"])

        if data.get("maximum_distance"):
            filters["maximum_distance"] = int(data["maximum_distance"])

        if data.get("race_classes"):
            if isinstance(data["race_classes"], list):
                filters["race_classes"] = [int(c) for c in data["race_classes"]]
            else:
                filters["race_classes"] = [int(data["race_classes"])]

        job_id = start_scrape_job(
            days_back=days_back, filters=filters if filters else None
        )

        return JsonResponse(
            {
                "success": True,
                "job_id": job_id,
                "message": f"Scraping job started for {days_back} days",
                "filters": filters,
            }
        )

    except ValueError as e:
        return JsonResponse({"error": f"Invalid value: {str(e)}"}, status=400)
    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON in request body"}, status=400)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@require_http_methods(["POST"])
def stop_scrape(request: "HttpRequest", job_id: str):
    """
    Stop a running scraping job.

    Note: This marks the job as stopped in the database.
    The actual thread cannot be forcefully stopped, but it will
    check the status and exit gracefully.
    """
    try:
        job = get_object_or_404(ScrapeJob, job_id=job_id)

        if job.status != "running":
            return JsonResponse(
                {"error": f"Job is not running (status: {job.status})"}, status=400
            )

        # Mark job as stopped
        result = stop_scrape_job(job_id)

        return JsonResponse(
            {
                "success": True,
                "message": "Job stop requested",
                "job_id": job_id,
                "stopped": result,
            }
        )

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@require_http_methods(["GET"])
def get_preset(_request: "HttpRequest", preset_id: int):
    """Get preset configuration."""
    try:
        preset = FilterPreset.objects.get(id=preset_id)
        return JsonResponse(
            {
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
        return JsonResponse({"error": "Preset not found"}, status=404)


@require_http_methods(["POST"])
def save_preset(request: "HttpRequest"):
    """Save a new custom preset."""
    try:
        data = json.loads(request.body)

        if not data.get("name"):
            return JsonResponse({"error": "Preset name is required"}, status=400)

        if FilterPreset.objects.filter(name=data["name"]).exists():
            return JsonResponse(
                {"error": "A preset with this name already exists"}, status=400
            )

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

        return JsonResponse(
            {
                "success": True,
                "preset_id": preset.id,
                "message": f'Preset "{preset.name}" saved',
            }
        )

    except json.JSONDecodeError:
        return JsonResponse({"error": "Invalid JSON in request body"}, status=400)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@require_http_methods(["GET"])
def job_status(_request: "HttpRequest", job_id: str):
    """Get status of a scraping job."""
    job = get_object_or_404(ScrapeJob, job_id=job_id)

    return JsonResponse(
        {
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

    return JsonResponse(
        {
            "jobs": [
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
        }
    )
