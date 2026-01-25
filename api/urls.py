"""
URL configuration for API app.
"""

from django.urls import path

from . import views

app_name = "api"

urlpatterns = [
    path("", views.index, name="index"),
    path("scrape/start/", views.start_scrape, name="start_scrape"),
    path("scrape/status/<str:job_id>/", views.job_status, name="job_status"),
    path("scrape/jobs/", views.job_list, name="job_list"),
]

