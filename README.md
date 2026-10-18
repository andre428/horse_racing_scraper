# Horse racer scraper + Django

British Horseracing Authority — scraper and analyzer.

This here small application is used to scan a specified date range in order to collect data about races that took place
during the selected time period.

The results can then be sorted in one of several predefined ways for analysis and drawing your own conclusions, whatever
they may be.

The data collected is rather raw, and the ready-made sorters may not necessarily be sufficient for your analysis, so you
may want to create your own statistics system.

Go ahead.
And if you come up with something interesting, please share your idea with me.

## What it is

Two cooperating parts:

- **`scraper/`** — a framework-agnostic 5-step pipeline
  (fixtures → races → results → horses → sectionals) that talks to the BHA API,
  authenticates via a bearer token captured with a headless Playwright/Firefox
  session, and writes everything into a SQLite staging database
  (`cache/scraper_dump.db`).
- **`horseracer/` + `api/`** — a Django project that provides a small web UI to
  launch and monitor scrape jobs (run as Celery tasks), imports the staging data
  into the main Django database (`api/sync.py`), and offers browsing, search and
  a winning-starting-positions report over the imported data.

## Requirements

- Python 3.14+ (see `pyproject.toml`)
- [uv](https://docs.astral.sh/uv/) for dependency and virtualenv management
- Redis — only needed for scrape jobs launched from the web UI (Celery broker)

## Install

```bash
git clone git@github.com:andre428/horse_racing_scraper.git
cd horse_racing_scraper

uv sync                              # creates .venv, installs runtime + dev deps
uv run playwright install firefox    # headless browser used to capture the BHA bearer token
```

Notes:

- `uv sync` installs the `dev` group (pytest, ruff, mypy, …) by default.
  Use `uv sync --no-group dev` for a runtime-only environment, and
  `uv sync --extra prod` for deployment extras (gunicorn, whitenoise, sentry-sdk).
- `cache/` and `main_db/` are gitignored local runtime artifacts — the databases
  are created in place.

## First run

```bash
uv run manage.py migrate
uv run manage.py load_presets        # system filter presets for the UI
uv run manage.py runserver
```

Then open <http://127.0.0.1:8000/api/> (admin lives at `/admin/`).

The first scrape launches a headless Firefox to capture a bearer token from
britishhorseracing.com; the token is cached in `cache/auth_token.json` and
refreshed automatically on 401 responses.

## Background jobs

Scrapes started from the web UI run as Celery tasks, so a broker and a worker
must be running:

```bash
redis-server                         # or your system's redis service
uv run celery -A horseracer worker
```

## Management commands

| Command | What it does |
| --- | --- |
| `uv run manage.py scrape --days-back 7 [--course Ascot]` | run a scrape from the CLI, synchronously (no Redis/Celery needed) |
| `uv run manage.py sync_scraper [--limit N]` | import the staging SQLite DB into the main Django DB |
| `uv run manage.py cleanup_jobs [--days 3] [--fix-stale] [--dry-run]` | prune stale and old scrape jobs |
| `uv run manage.py load_presets [--clear]` | (re)load system filter presets |
| `uv run manage.py reset_presets [--confirm]` | delete all presets |
| `uv run manage.py debug_presets` | inspect presets and URL wiring |

## Configuration (environment variables)

| Variable | Default | Purpose |
| --- | --- | --- |
| `SCRAPER_DB_PATH` | `<project>/cache/scraper_dump.db` | scraper staging SQLite DB location |
| `DJANGO_DB_NAME` | `<project>/main_db/django_main.db` | main database path (a filesystem path, despite the name, while on SQLite) |
| `DJANGO_DB_ENGINE` | `django.db.backends.sqlite3` | set to `django.db.backends.postgresql` for PostgreSQL (`psycopg2-binary` ships as a dependency) |
| `DJANGO_DB_USER` / `DJANGO_DB_PASSWORD` / `DJANGO_DB_HOST` / `DJANGO_DB_PORT` | empty | PostgreSQL credentials when applicable |

## Testing

```bash
uv run pytest
```
