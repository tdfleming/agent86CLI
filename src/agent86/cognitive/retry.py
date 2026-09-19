"""Retry with exponential backoff (Tier 3).

Hosted inference endpoints fail transiently: a 429 while a rate-limit bucket refills, a 503
from a gateway shedding load, a connection reset before the first byte. Failing the whole turn
for those is wasteful — the harness has already paid for the prompt — but retrying blindly is
worse, so this module is the single place that decides *whether* a failure is worth another
attempt and *how long* to wait.

Two rules the providers must honour:

- **Never retry after a delta has been yielded.** The consumer has already seen that text; a
  second attempt would duplicate it in the transcript. Once the stream is flowing, a failure
  is surfaced as a :class:`~agent86.cognitive.base.ProviderError` instead.
- **Honour ``Retry-After``.** When a server tells us when to come back, arguing with it just
  burns the budget on responses we know will be rejected.

The Anthropic SDK has its own retry layer, so that provider passes ``max_retries`` to the
client constructor rather than using this module.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

logger = logging.getLogger("agent86.cognitive")

#: Status codes worth another attempt: rate limiting and transient upstream failures.
#: Everything else (400 bad request, 401 bad key, 404 unknown model) is a caller error that
#: would fail identically on every retry.
RETRYABLE_STATUS: frozenset[int] = frozenset({429, 500, 502, 503, 504})

#: Transport failures worth another attempt. RemoteProtocolError qualifies only *before* any
#: bytes were streamed — the provider enforces that via the ``emitted`` flag.
RETRYABLE_EXCEPTIONS: tuple[type[Exception], ...] = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.RemoteProtocolError,
)

#: Default when the provider config predates ``max_retries``.
DEFAULT_MAX_RETRIES = 2

_BASE_DELAY_S = 0.5
_MAX_DELAY_S = 30.0
#: A server may name an absurd Retry-After (or an hours-away HTTP-date); an interactive CLI
#: must not silently sit on it.
_MAX_RETRY_AFTER_S = 60.0


def sleep(seconds: float) -> None:
    """Indirection so tests can make backoff instant without touching :mod:`time` globally."""
    time.sleep(seconds)


def max_retries_for(config: Any) -> int:
    """``config.max_retries``, tolerating a ProviderConfig that does not have it yet."""
    value = getattr(config, "max_retries", DEFAULT_MAX_RETRIES)
    try:
        return max(0, int(value))
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return DEFAULT_MAX_RETRIES


def is_retryable_status(status: int) -> bool:
    return status in RETRYABLE_STATUS


def is_retryable_exception(exc: BaseException) -> bool:
    return isinstance(exc, RETRYABLE_EXCEPTIONS)


def retry_after_header(response: Any) -> str | None:
    """The ``Retry-After`` header of a response, or None (also for header-less test doubles)."""
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    try:
        return headers.get("retry-after") or headers.get("Retry-After")
    except AttributeError:  # pragma: no cover - defensive
        return None


def parse_retry_after(value: str | float | None, *, now: datetime | None = None) -> float | None:
    """Seconds to wait per a ``Retry-After`` value: delta-seconds or an HTTP-date."""
    if value is None:
        return None
    if isinstance(value, int | float):
        return max(0.0, min(float(value), _MAX_RETRY_AFTER_S))
    raw = value.strip()
    if not raw:
        return None
    try:
        return max(0.0, min(float(raw), _MAX_RETRY_AFTER_S))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if when is None:  # pragma: no cover - parsedate_to_datetime contract
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    reference = now or datetime.now(UTC)
    return max(0.0, min((when - reference).total_seconds(), _MAX_RETRY_AFTER_S))


def backoff_delay(attempt: int, *, jitter: Callable[[float, float], float] | None = None) -> float:
    """Exponential backoff with equal jitter: half the window fixed, half random.

    Jitter matters more than the curve: without it every client that hit the same 429 comes
    back in the same millisecond and re-creates the overload it is backing off from.
    """
    window = min(_BASE_DELAY_S * (2**attempt), _MAX_DELAY_S)
    rand = jitter or random.uniform
    return window / 2 + rand(0.0, window / 2)


class RetryPolicy:
    """Per-request retry budget. One instance per :meth:`ModelProvider.stream` call."""

    def __init__(
        self,
        max_retries: int = DEFAULT_MAX_RETRIES,
        *,
        provider: str = "",
        model: str = "",
        sleeper: Callable[[float], None] | None = None,
    ):
        self.max_retries = max(0, max_retries)
        self.provider = provider
        self.model = model
        self.retries = 0
        self._sleeper = sleeper

    @classmethod
    def from_config(cls, config: Any, *, provider: str = "", model: str = "") -> RetryPolicy:
        return cls(max_retries_for(config), provider=provider, model=model)

    def attempts(self) -> Iterator[int]:
        """0, 1, ... max_retries — the attempt numbers this budget allows."""
        yield from range(self.max_retries + 1)

    def retry_status(
        self,
        status: int,
        attempt: int,
        *,
        retry_after: str | float | None = None,
        emitted: bool = False,
    ) -> bool:
        """True (after waiting) if this HTTP status deserves another attempt."""
        if emitted or attempt >= self.max_retries or not is_retryable_status(status):
            return False
        self._wait(attempt, parse_retry_after(retry_after), f"HTTP {status}")
        return True

    def retry_exception(
        self, exc: BaseException, attempt: int, *, emitted: bool = False
    ) -> bool:
        """True (after waiting) if this transport failure deserves another attempt.

        ``emitted=True`` means deltas already reached the consumer, which vetoes the retry:
        re-running the request would duplicate that text.
        """
        if emitted or attempt >= self.max_retries or not is_retryable_exception(exc):
            return False
        self._wait(attempt, None, type(exc).__name__)
        return True

    def _wait(self, attempt: int, retry_after: float | None, cause: str) -> None:
        delay = retry_after if retry_after is not None else backoff_delay(attempt)
        self.retries += 1
        logger.warning(
            "%s: retrying %s in %.2fs after %s (attempt %d of %d)%s",
            self.provider or "provider",
            self.model or "model",
            delay,
            cause,
            attempt + 1,
            self.max_retries,
            " [Retry-After]" if retry_after is not None else "",
        )
        (self._sleeper or sleep)(delay)


__all__ = [
    "DEFAULT_MAX_RETRIES",
    "RETRYABLE_EXCEPTIONS",
    "RETRYABLE_STATUS",
    "RetryPolicy",
    "backoff_delay",
    "is_retryable_exception",
    "is_retryable_status",
    "max_retries_for",
    "parse_retry_after",
    "retry_after_header",
    "sleep",
]
