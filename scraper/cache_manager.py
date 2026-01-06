"""
Caching utilities: token cache and JSON cache files.

Provides simple functions to save/load token and arbitrary JSON objects to files.
Timestamping is handled via file modification times so uses filesystem to decide freshness.
"""

import json
from pathlib import Path
from typing import Any

from .config import DEFAULT_CACHE_DIR

# allow overriding cache dir via environment variable (useful in tests)
CACHE_DIR = Path(DEFAULT_CACHE_DIR)
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def load_from_cache(key: str) -> dict[str, Any] | None:
    """Load data from cache by key"""
    cache_file = CACHE_DIR / f"{key}.json"

    try:
        with open(cache_file, encoding="utf-8") as cf:
            return json.load(cf)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def save_to_cache(key: str, data: dict[str, Any]) -> None:
    """Save data to cache by key"""
    cache_file = CACHE_DIR / f"{key}.json"

    # Ensure parent directory exist
    cache_file.parent.mkdir(parents=True, exist_ok=True)

    try:
        with open(cache_file, mode="w", encoding="utf-8") as cf:
            json.dump(data, cf, indent=4)
    except (FileNotFoundError, json.JSONDecodeError, OSError) as err:
        raise RuntimeError(f"Failed to save data for '{key}': {err}") from err


def clear_cache(key: str) -> bool:
    """Clear cache file by key"""
    cache_file = CACHE_DIR / f"{key}.json"

    try:
        cache_file.unlink()
        return True
    except FileNotFoundError:
        return False
