"""Cross-module error notification with per-source throttling.

The Telegram and Signal listeners need to push warnings to the owner via
the control bot when they hit unrecoverable errors (e.g. a disconnect that
keeps retrying). Without throttling, a flapping connection would spam the
owner. We throttle to one notification per `source` per hour.

The control bot registers a delivery callback at startup via
`set_delivery()`. If no callback is registered (e.g. the control bot has
not started yet), the message is dropped after a log entry — better than
blocking the listener.
"""

from __future__ import annotations

import logging
import time
from typing import Awaitable, Callable

log = logging.getLogger(__name__)

_THROTTLE_SECONDS = 3600
_last_sent: dict[str, float] = {}
_delivery: Callable[[str], Awaitable[None]] | None = None


def set_delivery(fn: Callable[[str], Awaitable[None]]) -> None:
    """Called by the control bot once it's ready to send messages."""
    global _delivery
    _delivery = fn


async def notify(source: str, message: str) -> None:
    """Send a warning to the owner, throttled to 1/hour per source.

    `source` is a stable identifier like "userbot" or "signalbot" — all
    errors from the same source share one throttle bucket regardless of
    exception type.
    """
    now = time.monotonic()
    last = _last_sent.get(source)
    if last is not None and (now - last) < _THROTTLE_SECONDS:
        log.debug("notify suppressed (throttled) for %s: %s", source, message)
        return
    _last_sent[source] = now
    if _delivery is None:
        log.warning("notify dropped (no delivery yet) for %s: %s", source, message)
        return
    try:
        await _delivery(f"⚠️ {message}")
    except Exception:
        log.exception("failed to deliver notification from %s", source)
