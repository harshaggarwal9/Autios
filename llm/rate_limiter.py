
"""
llm/rate_limiter.py
────────────────────
RateLimiter — token-bucket rate limiter for the Gemini API.

Paper connection (§III.C — LLM Inference):
  The paper uses Gemini via the Google AI Studio free tier, which has a
  rate limit of 15 requests per minute. The RateLimiter ensures the
  OperatorAgent never exceeds this limit, preventing 429 errors that
  would interrupt the agent loop.

Design — token bucket algorithm:
  A token bucket is refilled at a fixed rate (tokens_per_second). Each
  LLM call consumes one token. If the bucket is empty, the caller awaits
  until enough tokens have accumulated.

  Advantages over a simple sleep-between-calls approach:
    - Handles burst traffic: if the agent hasn't called the LLM for a
      while, the bucket accumulates tokens up to `burst` capacity,
      allowing several rapid calls before throttling kicks in.
    - More accurate than a fixed inter-call delay because it tracks the
      actual time elapsed since the last refill.

Usage:
  The RateLimiter supports use as an async context manager:

    async with rate_limiter:
        response = await client.generate(prompt)

  Or explicit acquire():

    await rate_limiter.acquire()
    response = await client.generate(prompt)

Dependencies:
  asyncio (stdlib only)
"""

import asyncio
import logging
import time

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    Token-bucket rate limiter for async code.

    One instance per agent. Shared instances are safe (asyncio.Lock
    ensures only one coroutine acquires at a time).

    Args:
        requests_per_minute: Maximum sustained request rate.
        burst:               Maximum tokens that can accumulate in the
                             bucket (allows short bursts above the
                             sustained rate). Defaults to 1.
    """

    def __init__(self, requests_per_minute: float, burst: int = 1) -> None:
        if requests_per_minute <= 0:
            raise ValueError(
                f"requests_per_minute must be > 0, got {requests_per_minute}"
            )
        if burst < 1:
            raise ValueError(f"burst must be >= 1, got {burst}")

        self._rate = requests_per_minute / 60.0  # tokens per second
        self._burst = burst
        self._tokens = float(burst)               # start full
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """
        Acquire one token, waiting if the bucket is empty.

        Blocks for at most ceil(1 / rate) seconds when the bucket is
        empty. For a 14 req/min rate limit that is ~4.3 seconds.
        """
        async with self._lock:
            self._refill()
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return

            # Calculate how long to wait for one token to accumulate
            wait_seconds = (1.0 - self._tokens) / self._rate
            logger.debug(
                "RateLimiter: bucket empty, waiting %.2fs.", wait_seconds
            )
            await asyncio.sleep(wait_seconds)
            self._refill()
            self._tokens -= 1.0

    def _refill(self) -> None:
        """Add tokens based on elapsed time since last refill."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(
            self._burst,
            self._tokens + elapsed * self._rate,
        )
        self._last_refill = now

    # ── Async context manager support ────────────────────────────────────────

    async def __aenter__(self) -> "RateLimiter":
        await self.acquire()
        return self

    async def __aexit__(self, *args: object) -> None:
        pass  # nothing to release — tokens are consumed at acquire time
