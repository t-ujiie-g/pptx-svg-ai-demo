"""Shared google-genai SDK client + retry helpers.

Several services (style_extractor, entity_extractor, critic, ...) call Gemini
directly — bypassing the ADK Runner — for structured-output extraction. They
all use the same auth profile, so a single lazily-initialised client is shared.

Also exposes `with_genai_retry()` which wraps a coroutine factory with
exponential-backoff retries on transient failures. The PPTX pipeline issues
8-10 LLM calls per request burst, so 429 (RESOURCE_EXHAUSTED) and 503/504 are
common when running near a quota — the retry shields the user from those.

Note: the ADK Runner has its own retry/streaming logic; this helper is only
for the direct SDK calls outside the agent flow.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar

from google import genai
from google.api_core import exceptions as g_api_exc
from google.genai import errors as genai_errors

from src.config import settings
from src.constants import (
    GENAI_RETRY_BASE_DELAY_SECONDS,
    GENAI_RETRY_JITTER_SECONDS,
    GENAI_RETRY_MAX_ATTEMPTS,
    GENAI_RETRY_MAX_DELAY_SECONDS,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")

_client: genai.Client | None = None


def get_genai_client() -> genai.Client:
    """Lazy-init a single Gemini client matching the rest of the app's config."""
    global _client
    if _client is not None:
        return _client
    if settings.google_genai_use_vertexai:
        _client = genai.Client(
            vertexai=True,
            project=settings.google_cloud_project,
            location=settings.google_cloud_location,
        )
    else:
        _client = genai.Client(api_key=settings.google_api_key)
    return _client


# HTTP codes that are worth retrying for. 429 = quota / RPM, 503/504 = upstream
# blip, 500 = sometimes transient on Vertex. 4xx other than 429 = client bug,
# do NOT retry.
_RETRYABLE_HTTP_CODES = frozenset({429, 500, 503, 504})


def _is_retryable_error(exc: BaseException) -> bool:
    """Return True for transient errors that benefit from retry-with-backoff."""
    # google-genai SDK's APIError has a .code attribute (HTTP status).
    if isinstance(exc, genai_errors.APIError):
        return exc.code in _RETRYABLE_HTTP_CODES
    # google.api_core.exceptions hierarchy (used by some ADK paths).
    if isinstance(exc, (
        g_api_exc.ResourceExhausted,
        g_api_exc.ServiceUnavailable,
        g_api_exc.DeadlineExceeded,
        g_api_exc.InternalServerError,
    )):
        return True
    return False


async def with_genai_retry(
    coro_factory: Callable[[], Awaitable[T]],
    *,
    label: str = "genai",
    max_attempts: int | None = None,
) -> T:
    """Call a coroutine factory with exponential-backoff retries.

    `coro_factory` is a zero-arg callable that returns a fresh coroutine per
    attempt — needed because awaiting a coroutine consumes it. Use a lambda:

        result = await with_genai_retry(
            lambda: client.aio.models.generate_content(...),
            label="critic",
        )

    Backoff: base=GENAI_RETRY_BASE_DELAY_SECONDS, doubled each attempt,
    capped at GENAI_RETRY_MAX_DELAY_SECONDS, plus jitter to avoid thundering
    herd when multiple in-flight requests retry against the same quota.
    """
    attempts = max_attempts or GENAI_RETRY_MAX_ATTEMPTS
    delay = GENAI_RETRY_BASE_DELAY_SECONDS

    for attempt in range(1, attempts + 1):
        try:
            return await coro_factory()
        except Exception as e:
            if attempt >= attempts or not _is_retryable_error(e):
                raise
            jitter = random.uniform(0, GENAI_RETRY_JITTER_SECONDS)
            sleep_for = min(delay + jitter, GENAI_RETRY_MAX_DELAY_SECONDS)
            logger.warning(
                f"[{label}] retryable error on attempt {attempt}/{attempts}: "
                f"{type(e).__name__}: {e}. Sleeping {sleep_for:.1f}s before retry."
            )
            await asyncio.sleep(sleep_for)
            delay = min(delay * 2, GENAI_RETRY_MAX_DELAY_SECONDS)
    # Unreachable — the loop either returns on success or raises on the
    # final attempt. Make type-checkers happy.
    raise RuntimeError(f"with_genai_retry: exhausted attempts for {label}")
