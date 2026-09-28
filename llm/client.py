import asyncio
import logging
import time
from dataclasses import dataclass

from google import genai
from google.genai import types
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    raw_text: str
    model_name: str
    prompt_tokens: int | None
    response_tokens: int | None
    latency_ms: float


class GeminiClient:
    def __init__(self) -> None:
        from config.settings import get_settings

        settings = get_settings()

        if not settings.gemini_api_key:
            raise ValueError(
                "GEMINI_API_KEY is not set. "
                "Add it to your .env file or set the environment variable."
            )

        self._model_name = settings.gemini_model_name

        self._client = genai.Client(
            api_key=settings.gemini_api_key
        )

        logger.info(
            "GeminiClient initialised with model '%s'.",
            self._model_name,
        )

    async def generate(self, prompt: str) -> LLMResponse:
        return await asyncio.to_thread(
            self._generate_sync,
            prompt,
        )

    @retry(
        retry=retry_if_exception_type(Exception),
        wait=wait_exponential(
            multiplier=1,
            min=2,
            max=30,
        ),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    def _generate_sync(self, prompt: str) -> LLMResponse:
        start_ms = time.monotonic() * 1000

        response = self._client.models.generate_content(
            model=self._model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0,
                max_output_tokens=512,
            ),
        )

        elapsed_ms = time.monotonic() * 1000 - start_ms

        raw_text = response.text or ""

        prompt_tokens = None
        response_tokens = None

        if response.usage_metadata:
            prompt_tokens = getattr(
                response.usage_metadata,
                "prompt_token_count",
                None,
            )

            response_tokens = getattr(
                response.usage_metadata,
                "candidates_token_count",
                None,
            )

        logger.debug(
            "GeminiClient: generated %d chars in %.0fms "
            "(prompt_tokens=%s, response_tokens=%s).",
            len(raw_text),
            elapsed_ms,
            prompt_tokens,
            response_tokens,
        )

        return LLMResponse(
            raw_text=raw_text,
            model_name=self._model_name,
            prompt_tokens=prompt_tokens,
            response_tokens=response_tokens,
            latency_ms=elapsed_ms,
        )