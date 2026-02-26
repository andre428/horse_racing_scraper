"""
HTTP client for API requests.

Provides robust HTTP GET with retry logic and error handling.
Does NOT manage authentication - caller must provide token.
"""

import time
from typing import Any

import requests
from requests.exceptions import RequestException

from .config import BACKOFF_FACTOR, HEADERS, MAX_RETRIES, REQUEST_TIMEOUT


def fetch_json(url: str, token: str) -> dict[str, Any] | None:
    """
    Fetch JSON from URL with authentication.

    Makes HTTP GET request with bearer token and returns parsed JSON.
    Automatically retries on network errors with exponential backoff.

    Args:
        url: Full URL to fetch
        token: Bearer token for authentication (required)

    Returns:
        Parsed JSON response as dict

    Raises:
        RuntimeError: If request fails after all retries
        ValueError: If response is not valid JSON

    Example:
        token = token_manager.get_valid_token()
        data = fetch_json("https://api.example.com/data", token)
    """
    if not token or not isinstance(token, str):
        raise ValueError(f"Invalid token: {type(token)}")

    if not token.startswith("Bearer "):
        raise ValueError("Token must start with 'Bearer '")

    headers = HEADERS.copy()
    headers["Authorization"] = token

    attempt = 0

    while attempt < MAX_RETRIES:
        try:
            resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)

            # Check for auth failure
            if resp.status_code == 401:
                raise RuntimeError("Authentication failed (401)")

            # Raise for other HTTP errors
            resp.raise_for_status()

            # Parse JSON
            data = resp.json()

            # Validate structure
            if not isinstance(data, dict):
                raise ValueError(f"Expected dict, got {type(data)}")

            return data

        except RequestException as e:
            attempt += 1
            if attempt < MAX_RETRIES:
                wait = BACKOFF_FACTOR ** attempt
                time.sleep(wait)
            else:
                raise RuntimeError(f"Failed after {MAX_RETRIES} attempts: {e}") from e

        except (ValueError, RuntimeError):
            raise
    return None
