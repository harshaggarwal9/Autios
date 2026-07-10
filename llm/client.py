"""
llm/client.py
──────────────
GeminiClient — async wrapper around the Google Generative AI SDK.

Paper connection (§III.C — LLM Inference):
  "We use Google's Gemini model family for all LLM inference."
  The client wraps the blocking google-genai SDK call in asyncio.to_thread()
  so it never blocks the event loop, which is critical since the OperatorAgent
  and SummarizationAgent run as persistent asyncio background tasks.

Design decisions:
  1. asyncio.to_thread() — the google-genai SDK is synchronous. Running it
     in a thread pool prevents blocking the event loop during LLM calls.
  2. @retry (tenacity) — transient API errors (rate limits, network blips)
     are retried with exponential backoff. The agent loop is designed to
     tolerate retries since cursor advancement only happens after a
     successful inference.
  3. temperature=0 — matches the paper's evaluation setup for reproducibility.
     Set to 0 for deterministic outputs during testing and benchmarking.
  4. LLMResponse — a typed dataclass returned to callers so they have access
     to token counts and latency for the llm_inference_log table.

Dependencies:
  google-genai, tenacity, asyncio (stdlib)
"""

import asyncio
import logging
import time
from dataclasses import dataclass

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

# Lazy import to avoid import-time errors if the API key is not set.
# GeminiClient.__init__ will raise a clear ValueError if the key is missing.
try:
    import google.generativeai as genai
    _GENAI_AVAILABLE = True
except ImportError:
    _GENAI_AVAILABLE = False
    logger.warning(
        "google-generativeai package not installed. "
        "Install it with: pip install google-generativeai"
    )


@dataclass
class LLMResponse:
    """Typed response from the Gemini API."""
    raw_text: str
    model_name: str
    prompt_tokens: int | None
    response_tokens: int | None
    latency_ms: float


class GeminiClient:
    """
    Async Gemini API client with retry logic and response typing.

    Usage:
        client = GeminiClient()  # reads GEMINI_API_KEY from settings
        response = await client.generate(prompt)
        print(response.raw_text)
    """

    def __init__(self) -> None:
        from config.settings import get_settings
        settings = get_settings()

        if not settings.gemini_api_key:
            raise ValueError(
                "GEMINI_API_KEY is not set. "
                "Add it to your .env file or set the environment variable."
            )

        if not _GENAI_AVAILABLE:
            raise ImportError(
                "google-generativeai package is required. "
                "Install it with: pip install google-generativeai"
            )

        genai.configure(api_key=settings.gemini_api_key)

        self._model_name = settings.gemini_model_name
        self._model = genai.GenerativeModel(
            model_name=self._model_name,
            generation_config=genai.GenerationConfig(
                temperature=0,          # deterministic outputs (paper §V setup)
                max_output_tokens=512,  # function calls are short; cap tokens
            ),
        )

        logger.info(
            "GeminiClient initialised with model '%s'.", self._model_name
        )

    async def generate(self, prompt: str) -> LLMResponse:
        """
        Send a prompt to Gemini and return the response.

        Runs the blocking SDK call in a thread pool via asyncio.to_thread()
        to avoid blocking the event loop. Retries on transient errors.

        Args:
            prompt: The full assembled prompt text (all five sections
                    for OperatorAgent, or a summary prompt for
                    SummarizationAgent).

        Returns:
            LLMResponse with the raw text, model name, token counts,
            and wall-clock latency.

        Raises:
            Exception: if all retry attempts are exhausted.
        """
        return await asyncio.to_thread(self._generate_sync, prompt)

    @retry(
        retry=retry_if_exception_type(Exception),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    def _generate_sync(self, prompt: str) -> LLMResponse:
        """
        Synchronous Gemini call (runs in a thread pool).

        The @retry decorator handles transient errors with exponential
        backoff: 2s, 4s, 8s (capped at 30s), then reraises.
        """
        start_ms = time.monotonic() * 1000

        response = self._model.generate_content(prompt)

        elapsed_ms = time.monotonic() * 1000 - start_ms

        raw_text = response.text if response.text else ""

        # Extract token counts if available (not all response types include them)
        prompt_tokens = None
        response_tokens = None
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            prompt_tokens = getattr(
                response.usage_metadata, "prompt_token_count", None
            )
            response_tokens = getattr(
                response.usage_metadata, "candidates_token_count", None
            )

        logger.debug(
            "GeminiClient: generated %d chars in %.0fms "
            "(prompt_tokens=%s, response_tokens=%s).",
            len(raw_text), elapsed_ms, prompt_tokens, response_tokens,
        )

        return LLMResponse(
            raw_text=raw_text,
            model_name=self._model_name,
            prompt_tokens=prompt_tokens,
            response_tokens=response_tokens,
            latency_ms=elapsed_ms,
        )