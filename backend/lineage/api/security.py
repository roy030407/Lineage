"""Request-level guards: an environment-gated API key check, a single-flight
lock, and a small in-process rate limiter.

All three keep their state in-process by design. AppState is already a
process-wide global and render.yaml pins --workers 1 for exactly that
reason (see api/deps.py's own note), so per-process state here adds no
constraint that does not already exist. Anything multi-instance needs
shared state first, which is a separate change entirely.
"""

import hmac
import os
import threading
import time
from collections.abc import Awaitable, Callable

from fastapi import Request
from fastapi.responses import JSONResponse, Response

API_KEY_HEADER = "X-Lineage-Key"

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
"""OPTIONS is exempt so CORS preflight still reaches CORSMiddleware. A
browser never attaches custom headers to a preflight request, so gating it
would break every cross-origin write before the real request was ever
sent."""

GATED_READ_PREFIXES = ("/api/predict/metrics",)
"""GETs that are not cheap. The prediction ledger's first build assesses
every car in a run against every inspection station it reached, a
documented ~105s job, so the usual "reads are free" assumption behind
method-based gating does not hold for it."""


def _configured_key() -> str | None:
    """Read per request rather than at import, so a test can set and unset
    the variable without rebuilding the app."""
    key = os.environ.get("LINEAGE_API_KEY")
    return key or None


def _requires_key(request: Request) -> bool:
    if request.method not in SAFE_METHODS:
        return True
    return request.url.path.startswith(GATED_READ_PREFIXES)


async def api_key_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Reject unauthenticated writes and expensive reads when a key is
    configured. A no-op when LINEAGE_API_KEY is unset, which is local
    development, the whole test suite, and the Playwright harness.

    Middleware rather than a per-route dependency on purpose: there are 17
    mutating routes across 6 route modules today, and a dependency list has
    to be remembered at every one of them. A method check cannot miss a
    route somebody adds next month.
    """
    expected = _configured_key()
    if expected is None or not _requires_key(request):
        return await call_next(request)

    supplied = request.headers.get(API_KEY_HEADER, "")
    # compare_digest rather than ==, so rejection time does not vary with
    # how many leading characters of the key happened to be correct.
    if not hmac.compare_digest(supplied, expected):
        return JSONResponse(
            status_code=401,
            content={"detail": f"missing or invalid {API_KEY_HEADER}"},
        )
    return await call_next(request)


class SingleFlight:
    """Refuses a second concurrent entry rather than queueing it.

    Queueing would be worse here: the caller is an HTTP request with a
    client-side timeout and the work takes ~11s, so a queue just converts
    one honestly-refused request into two slow ones on a single worker.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()

    def acquire(self) -> bool:
        return self._lock.acquire(blocking=False)

    def release(self) -> None:
        self._lock.release()


class RateLimiter:
    """A token bucket keyed by caller. Dependency-free on purpose: adding a
    rate-limiting package for one bucket would be a new runtime dependency
    for about twenty lines of arithmetic."""

    def __init__(self, capacity: int, refill_per_second: float) -> None:
        self.capacity = capacity
        self.refill_per_second = refill_per_second
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            tokens, last = self._buckets.get(key, (float(self.capacity), now))
            tokens = min(float(self.capacity), tokens + (now - last) * self.refill_per_second)
            if tokens < 1.0:
                self._buckets[key] = (tokens, now)
                return False
            self._buckets[key] = (tokens - 1.0, now)
            return True


SIMULATE_SINGLE_FLIGHT = SingleFlight()
"""Guards /api/datagen/simulate. Module-level so the single worker shares
one lock across every request thread FastAPI dispatches."""
