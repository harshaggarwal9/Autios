import asyncio
import logging
import time

logger = logging.getLogger(__name__)


class RateLimiter:


    def __init__(self, requests_per_minute: float, burst: int = 1) -> None:
        if requests_per_minute <= 0:
            raise ValueError(
                f"requests_per_minute must be > 0, got {requests_per_minute}"
            )
        if burst < 1:
            raise ValueError(f"burst must be >= 1, got {burst}")

        self._rate = requests_per_minute / 60.0
        self._burst = burst
        self._tokens = float(burst)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:

        async with self._lock:
            self._refill()
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return


            wait_seconds = (1.0 - self._tokens) / self._rate
            logger.debug(
                "RateLimiter: bucket empty, waiting %.2fs.", wait_seconds
            )
            await asyncio.sleep(wait_seconds)
            self._refill()
            self._tokens -= 1.0

    def _refill(self) -> None:

        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(
            self._burst,
            self._tokens + elapsed * self._rate,
        )
        self._last_refill = now



    async def __aenter__(self) -> "RateLimiter":
        await self.acquire()
        return self

    async def __aexit__(self, *args: object) -> None:
        pass
