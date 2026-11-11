"""In-memory limits: per IP per minute, per IP per day, and a global daily quota that protects the Groq budget.

Fine for one instance (Cloud Run max-instances=1). With more than one, move the counters to a shared store (e.g. Upstash Redis).
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable
from datetime import UTC, datetime


class RateLimiter:
    def __init__(self, per_minute: int, per_day: int, daily_quota: int, clock: Callable[[], float] = time.time) -> None:
        self.per_minute, self.per_day, self.daily_quota = per_minute, per_day, daily_quota
        self._clock = clock
        self._lock = threading.Lock()
        self._recent: dict[str, deque[float]] = defaultdict(deque)
        self._day = ""
        self._per_ip_today: dict[str, int] = defaultdict(int)
        self._total_today = 0

    def check(self, ip: str) -> str | None:
        """Count a request. Returns None if allowed, or which limit was hit."""
        now = self._clock()
        day = datetime.fromtimestamp(now, UTC).strftime("%Y-%m-%d")
        with self._lock:
            if day != self._day:
                self._day, self._total_today = day, 0
                self._per_ip_today.clear()
            recent = self._recent[ip]
            while recent and now - recent[0] >= 60:
                recent.popleft()
            if self._total_today >= self.daily_quota:
                return "daily_quota"
            if self._per_ip_today[ip] >= self.per_day:
                return "per_ip_per_day"
            if len(recent) >= self.per_minute:
                return "per_ip_per_minute"
            recent.append(now)
            self._per_ip_today[ip] += 1
            self._total_today += 1
            return None

    @property
    def remaining_today(self) -> int:
        with self._lock:
            return max(0, self.daily_quota - self._total_today)
