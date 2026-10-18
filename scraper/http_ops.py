"""
HTTP Operations Layer

This module provides a unified HTTP interface for the scraper.

Design principles:
- fetch_json(): performs a SINGLE HTTP request (no retries)
- fetch_with_retry(): handles ALL retry logic, backoff, token refresh and rate limiting

Responsibilities:
✔ Token-aware requests
✔ Centralized retry strategy
✔ Adaptive rate-limiting integration
✔ Proper HTTP error propagation (401, 429, network)

This is the ONLY place where HTTP retry logic should exist.
All scraper steps MUST use fetch_with_retry().
"""

import random
import time
from typing import Any

import requests

from .config import HEADERS, REQUEST_TIMEOUT
from .rate_limiter import RateLimiter
from .token_manager import TokenManager
from .utils import warn


# =========================================================
# 🔹 LOW LEVEL REQUEST (NO RETRIES)
# =========================================================


def fetch_json(url: str, token: str) -> dict[str, Any]:
    """
    Perform a single HTTP GET request.

    Raises:
        RuntimeError with explicit status info (401, 429, network errors)
    """
    if not token or not isinstance(token, str):
        raise ValueError(f"Invalid token: {type(token)}")

    if not token.startswith("Bearer "):
        raise ValueError("Token must start with 'Bearer '")

    headers = HEADERS.copy()
    headers["Authorization"] = token

    try:
        resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)

        if resp.status_code == 401:
            raise RuntimeError("401 Unauthorized")

        if resp.status_code == 429:
            raise RuntimeError("429 Too Many Requests")

        resp.raise_for_status()

        data = resp.json()

        if not isinstance(data, dict):
            raise RuntimeError(f"Invalid JSON structure: {type(data)}")

        return data

    except requests.RequestException as exc:
        raise RuntimeError(f"HTTP request failed: {exc}") from exc


# =========================================================
# 🔹 UNIFIED RETRY LAYER
# =========================================================


def fetch_with_retry(
        url: str,
        token_manager: TokenManager,
        rate_limiter: RateLimiter,
        *,
        max_retries: int = 5,
        cooldown_after_429s: int = 3,
        cooldown_seconds: int = 1800,
) -> dict[str, Any]:
    """
    Unified HTTP execution layer.

    Handles:
    - global pacing (rate limiter)
    - retries
    - 401 token refresh
    - 429 adaptive slowdown
    - network failures
    - workflow cooldown when rate limiting persists

    This function MUST be used by all scraping steps.
    """
    rate_limit_hits = 0

    for attempt in range(max_retries):
        try:
            #  GLOBAL pacing BEFORE request
            rate_limiter.wait()

            token = token_manager.get_valid_token()
            payload = fetch_json(url, token)

            # ✅ success → speed up slightly
            rate_limiter.success()

            return payload

        except RuntimeError as exc:
            msg = str(exc)

            #  TOKEN EXPIRED
            if "401" in msg:
                token_manager.refresh_token()
                continue

            #  RATE LIMITED
            if "429" in msg:
                rate_limit_hits += 1
                rate_limiter.failure()

                backoff = min(30, (2 ** attempt) + random.uniform(1.0, 3.0))

                warn(
                    "http_rate_limited",
                    attempt=attempt + 1,
                    max_retries=max_retries,
                    rate_limit_hits=rate_limit_hits,
                    cooldown_after_429s=cooldown_after_429s,
                    backoff_seconds=round(backoff, 2),
                    url=url,
                )

                if rate_limit_hits >= cooldown_after_429s:
                    raise ScraperCooldownRequired(
                        "API rate limit persisted; scraper cooldown required",
                        cooldown_seconds=cooldown_seconds,
                    ) from exc

                time.sleep(backoff)
                continue

            #  NETWORK / TRANSIENT
            if "HTTP request failed" in msg:
                rate_limiter.failure()

                backoff = min(15, (2 ** attempt) + random.uniform(0.5, 2.0))

                warn(
                    "http_network_retry",
                    attempt=attempt + 1,
                    max_retries=max_retries,
                    backoff_seconds=round(backoff, 2),
                    error=msg,
                    url=url,
                )
                time.sleep(backoff)
                continue

            # ❌ UNKNOWN → fail fast
            raise

    raise RuntimeError(f"Failed after {max_retries} attempts: {url}")


"""
Custom scraper exceptions.

These exceptions are used to distinguish ordinary item/request failures from
workflow-level conditions, such as API throttling that requires a longer pause.
"""


class ScraperCooldownRequired(RuntimeError):
    """Raised when scraping should pause and resume later."""

    def __init__(self, message: str, cooldown_seconds: int) -> None:
        super().__init__(message)
        self.cooldown_seconds = cooldown_seconds
