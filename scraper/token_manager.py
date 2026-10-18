"""
Token functions

Handles fetching, caching, and validating authentication tokens
using Playwright to capture bearer tokens from the website.
"""

import asyncio
import time

from playwright.async_api import TimeoutError, async_playwright

from .cache_manager import clear_cache, load_from_cache, save_to_cache
from .config import BACKOFF_FACTOR, MAX_RETRIES, TIMEOUT_MS


async def _fetch_token_playwright() -> str:
    """
    Use Playwright to capture bearer token from website.

    Opens the results page in headless browser and intercepts
    API requests to capture the Authorization header.

    Returns:
        Bearer token string

    Raises:
        RuntimeError: If no token captured
    """
    token: str | None = None

    async with async_playwright() as p:
        browser = await p.firefox.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        # Intercept requests to capture token
        async def capture_token(request) -> None:
            nonlocal token

            try:
                # Only check API requests
                if not hasattr(request, "url") or not hasattr(request, "headers"):
                    return

                url = getattr(request, "url", None)
                if not url or "api09.horseracing.software" not in url:
                    return

                # Get authorization header
                headers = getattr(request, "headers", None)
                if not headers:
                    return

                auth = headers.get("authorization") or headers.get("Authorization")

                # Validate and store
                if auth and isinstance(auth, str) and auth.startswith("Bearer "):
                    token = auth

            except (AttributeError, TypeError, KeyError):
                # Ignore malformed requests
                pass

        page.on("request", capture_token)

        try:
            # Visit page that triggers API calls
            await page.goto(
                "https://www.britishhorseracing.com/racing/results/", timeout=TIMEOUT_MS
            )

            # Wait for requests to fire
            await page.wait_for_timeout(3000)

        except TimeoutError:
            # Page might timeout but token still captured
            pass
        finally:
            await browser.close()

    if not token:
        raise RuntimeError("No bearer token captured from website")

    return token


class TokenManager:
    """Manages token lifecycle"""

    CACHE_KEY = "auth_token"

    def __init__(self) -> None:
        self._token: str | None = None

    def get_valid_token(self) -> str:
        """
        Get a valid authentication token.

        Checks cache first, fetches new if needed.

        Returns:
            Valid bearer token string

        Raises:
            RuntimeError: If token cannot be obtained after retries
        """
        # Check memory cache first
        if self._token:
            return self._token

        # Check disk cache
        cached = load_from_cache(self.CACHE_KEY)
        if cached:
            token = cached.get("value")
            if token and token.startswith("Bearer "):
                self._token = token
                return token

        # No valid cache, fetch new token
        return self.refresh_token()

    def refresh_token(self) -> str:
        """
        Force fetch a new token (bypasses cache).

        Returns:
            New bearer token string

        Raises:
            RuntimeError: If token fetch fails after retries
        """
        print("[TokenManager] Fetching new token...")

        attempt = 0
        last_error = None

        while attempt < MAX_RETRIES:
            try:
                token = asyncio.run(_fetch_token_playwright())

                # Validate token format
                if not token or not token.startswith("Bearer "):
                    raise ValueError(f"Invalid token format: {token[:20]}...")

                # Cache it
                save_to_cache(self.CACHE_KEY, {"value": token})
                self._token = token

                print("[TokenManager] Token fetched successfully")
                return token

            except Exception as e:
                attempt += 1
                last_error = e

                if attempt < MAX_RETRIES:
                    wait = BACKOFF_FACTOR**attempt
                    print(f"[TokenManager] Token fetch failed: {e}")
                    print(f"[TokenManager] Retry {attempt}/{MAX_RETRIES} in {wait}s...")
                    time.sleep(wait)

        # All retries exhausted
        raise RuntimeError(
            f"Failed to fetch token after {MAX_RETRIES} attempts. Last error: {last_error}"
        )

    def clear_cache(self) -> None:
        """Clear cached token (forces fresh fetch on next get)."""

        clear_cache(self.CACHE_KEY)
        self._token = None
        print("[TokenManager] Token cache cleared")
