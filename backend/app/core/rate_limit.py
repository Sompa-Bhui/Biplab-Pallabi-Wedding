from collections import defaultdict, deque
from threading import Lock
from time import monotonic


class InMemoryRateLimiter:
    """A small per-process limiter; use a shared store for multi-instance deployments."""

    def __init__(self, limit: int, window_seconds: int) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, client: str) -> bool:
        now = monotonic()
        with self._lock:
            if len(self._requests) > 10_000:
                stale_clients = [
                    key
                    for key, timestamps in self._requests.items()
                    if not timestamps or now - timestamps[-1] >= self.window_seconds
                ]
                for key in stale_clients:
                    del self._requests[key]
            requests = self._requests[client]
            while requests and now - requests[0] >= self.window_seconds:
                requests.popleft()
            if len(requests) >= self.limit:
                return False
            requests.append(now)
            return True
