"""
URL configuration for API app.
"""

from django.urls import path

from . import views

app_name = "api"

urlpatterns = [
    path("", views.index, name="index"),
    path("scrape/start/", views.start_scrape, name="start_scrape"),
    path("scrape/stop/<str:job_id>/", views.stop_scrape, name="stop_scrape"),
    path("scrape/status/<str:job_id>/", views.job_status, name="job_status"),
    path("scrape/jobs/", views.job_list, name="job_list"),
    path("preset/<int:preset_id>/", views.get_preset, name="get_preset"),
    path("preset/save/", views.save_preset, name="save_preset"),
    path("database/", views.database_management, name="database_management"),
    path("database/wipe-postgresql/", views.wipe_postgresql, name="wipe_postgresql"),
    path("database/wipe-sqlite/", views.wipe_sqlite_buffer, name="wipe_sqlite_buffer"),
    path("browse/", views.browse_data, name="browse_data"),
    path("browse/search-horse/", views.search_horse, name="search_horse"),
    path("browse/search-races/", views.search_races, name="search_races"),
    path("browse/race/<int:race_id>/", views.race_detail, name="race_detail"),
    path("reports/", views.reports, name="reports"),
    path("reports/winning-positions/", views.generate_winning_positions_report,
         name="winning_positions_report",
         ),
    path("reports/export-csv/", views.export_report_csv, name="export_report_csv"),
]
