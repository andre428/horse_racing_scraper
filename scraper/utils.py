"""
Utility helpers for the scraper package.

Provides:
- date_range generator
- lightweight structured logging
- payload validation helpers (shared across steps)
"""

import logging
from datetime import datetime, timedelta
from typing import Any

# =========================================================
# 🔹 DATE HELPERS
# =========================================================


def date_range(start: str, end: str):
    """
    Yield ISO date strings from start to end inclusive.
    Format: YYYY-MM-DD
    """
    s = datetime.fromisoformat(start)
    e = datetime.fromisoformat(end)

    d = s
    while d <= e:
        yield d.strftime("%Y-%m-%d")
        d += timedelta(days=1)


# =========================================================
# 🔹 LOGGING
# =========================================================

logger = logging.getLogger("scraper")


def _log(level: str, event: str, **data: Any) -> None:
    """
    Structured logging (lightweight).

    Example:
        info("step_started", step=1)
    """
    payload = {
        "event": event,
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        **data,
    }

    if level == "info":
        logger.info(payload)
    elif level == "warn":
        logger.warning(payload)
    elif level == "error":
        logger.error(payload)
    else:
        logger.debug(payload)


def info(event: str, **data: Any) -> None:
    _log("info", event, **data)


def warn(event: str, **data: Any) -> None:
    _log("warn", event, **data)


def error(event: str, **data: Any) -> None:
    _log("error", event, **data)


# =========================================================
# 🔹 VALIDATORS (payload guards)
# =========================================================


def expect_dict(value: Any, context: str) -> dict:
    """
    Ensure value is a dict, otherwise raise.

    Args:
        value: object to validate
        context: string describing where validation happens

    Returns:
        dict
    """
    if not isinstance(value, dict):
        raise ValueError(f"{context}: expected dict, got {type(value)}")
    return value


def expect_list(value: Any, context: str) -> list:
    """
    Ensure value is a list, otherwise raise.
    """
    if not isinstance(value, list):
        raise ValueError(f"{context}: expected list, got {type(value)}")
    return value


def get_data_list(payload: dict, context: str) -> list:
    """
    Extract payload['data'] safely.

    Returns empty list if missing, but validates type.
    """
    data = payload.get("data") or []
    return expect_list(data, f"{context}.data")
