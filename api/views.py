"""
Django views for the API app.
"""

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from scraper.service import ScraperService


@require_http_methods(["GET"])
def scrape_days_back(request, days_back: int):
    """
    API endpoint to trigger scraping for last N days.
    
    Example: GET /api/scrape/3
    """
    try:
        service = ScraperService(enable_logging=True)
        result = service.scrape_days_back(days_back=days_back)
        
        return JsonResponse(result)
    except Exception as e:
        return JsonResponse(
            {"success": False, "error": str(e)},
            status=500
        )


@require_http_methods(["GET"])
def scrape_status(request):
    """
    API endpoint to check scraper status.
    
    Example: GET /api/status
    """
    return JsonResponse({
        "status": "ok",
        "message": "Scraper service is available"
    })
