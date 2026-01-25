"""
Django views for the API app.

[linter cries about request parameters not being used - leave it as is]
"""

import json

from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import ScrapeJob
from .tasks import start_scrape_job


def index(request):
    """Main page with a scraper form."""
    # Get recent jobs for display
    recent_jobs = ScrapeJob.objects.all()[:10]

    return render(request, "api/index.html", {"recent_jobs": recent_jobs})


@csrf_exempt  # For simplicity in v0.1 - add CSRF in v0.2
@require_http_methods(["POST"])
def start_scrape(request):
    """Start a new scraping job."""
    try:
        # Parse request data
        data = json.loads(request.body)
        days_back = int(data.get("days_back", 7))

        # Validate input
        if days_back < 0:
            return JsonResponse({"error": "days_back must be >= 0"}, status=400)

        if days_back > 365:
            return JsonResponse({"error": "days_back cannot exceed 365"}, status=400)

        # Start job
        job_id = start_scrape_job(days_back=days_back)

        return JsonResponse(
            {
                "success": True,
                "job_id": job_id,
                "message": f"Scraping job started for {days_back} days",
            }
        )

    except ValueError as e:
        return JsonResponse({"error": str(e)}, status=400)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)


@require_http_methods(["GET"])
def job_status(request, job_id):
    """Get status of a scraping job."""
    job = get_object_or_404(ScrapeJob, job_id=job_id)

    return JsonResponse(
        {
            "job_id": job.job_id,
            "status": job.status,
            "days_back": job.days_back,
            "current_step": job.current_step,
            "total_steps": job.total_steps,
            "stats": job.stats,
            "error_message": job.error_message,
            "created_at": job.created_at.isoformat(),
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
            "duration": job.duration(),
        }
    )


@require_http_methods(["GET"])
def job_list(request):
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
                }
                for job in jobs
            ]
        }
    )

