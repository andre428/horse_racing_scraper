"""
URL configuration for API app.
"""
from django.urls import path

from . import views

app_name = "api"

urlpatterns = [
    path("scrape/<int:days_back>/", views.scrape_days_back, name="scrape_days_back"),
    path("status/", views.scrape_status, name="status"),
]
