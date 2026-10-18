"""
Adaptive rate limiter used by the scraper HTTP layer.

Pipeline role:
    Shared infrastructure used by all scraper steps through `fetch_with_retry()`.

Behavior:
- Adds a delay before each outbound request
- Applies small random jitter to avoid perfectly regular request timing
- Slows down after failures
- Speeds back up gradually after successful requests

Key design decisions:
✔ Shared by ScraperService across all steps
✔ Thread-safe delay state via a lock
✔ No HTTP knowledge here; only pacing state
✔ Used centrally by the unified HTTP layer
"""
# TODO: create one limiter per step
"""
 ->Potential problems:
reset_current=True means each step starts fresh. That is usually good.
If you want throttling state to carry from Step 3 into Step 4, use reset_current=False. I would not do that yet.
"""

import random
import threading
import time
from typing import Any


class RateLimiter:
    def __init__(
            self,
            base_delay: float = 1.0,
            max_delay: float = 20.0,
            backoff_factor: float = 2.0,
            jitter_min: float = 0.2,
            jitter_max: float = 0.7,
    ) -> None:
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.backoff_factor = backoff_factor
        self.jitter_min = jitter_min
        self.jitter_max = jitter_max

        self.current_delay = base_delay
        self.lock = threading.Lock()

    def configure(
            self,
            *,
            base_delay: float | None = None,
            max_delay: float | None = None,
            backoff_factor: float | None = None,
            jitter_min: float | None = None,
            jitter_max: float | None = None,
            reset_current: bool = True,
    ) -> None:
        with self.lock:
            if base_delay is not None:
                self.base_delay = base_delay
            if max_delay is not None:
                self.max_delay = max_delay
            if backoff_factor is not None:
                self.backoff_factor = backoff_factor
            if jitter_min is not None:
                self.jitter_min = jitter_min
            if jitter_max is not None:
                self.jitter_max = jitter_max

            if reset_current:
                self.current_delay = self.base_delay
            else:
                self.current_delay = min(max(self.current_delay, self.base_delay), self.max_delay)

    def wait(self) -> None:
        with self.lock:
            delay = self.current_delay + random.uniform(self.jitter_min, self.jitter_max)

        time.sleep(delay)

    def success(self) -> None:
        with self.lock:
            self.current_delay = max(self.base_delay, self.current_delay / self.backoff_factor)

    def failure(self) -> None:
        with self.lock:
            self.current_delay = min(self.max_delay, self.current_delay * self.backoff_factor)

    def reset(self) -> None:
        with self.lock:
            self.current_delay = self.base_delay

    def get_delay(self) -> float:
        with self.lock:
            return self.current_delay

    def get_state(self) -> dict[str, Any]:
        with self.lock:
            return {
                "base_delay": self.base_delay,
                "max_delay": self.max_delay,
                "backoff_factor": self.backoff_factor,
                "jitter_min": self.jitter_min,
                "jitter_max": self.jitter_max,
                "current_delay": self.current_delay,
            }
