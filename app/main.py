"""asyncio entry point.

Boots all three concurrent tasks (Telegram userbot, Signal listener,
control bot) plus a periodic prune of the cooldown map. Handles SIGTERM
so `docker compose down` shuts everything down cleanly without corrupting
state.json mid-write.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from datetime import datetime
from zoneinfo import ZoneInfo

from . import config as cfgmod
from . import controlbot, signalbot, state as st, userbot

log = logging.getLogger(__name__)

PRUNE_INTERVAL_SECONDS = 3600  # once per hour


async def _prune_loop() -> None:
    """Drop expired entries from recently_replied so state.json doesn't grow
    forever. Cheap, idempotent, runs while the cooldown map is unlocked."""
    while True:
        try:
            await asyncio.sleep(PRUNE_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            return
        try:
            state = await st.load()
            removed = st.prune_recently_replied(state)
            if removed:
                await st.save(state)
                log.info("pruned %d stale cooldown entries", removed)
        except Exception:
            log.exception("prune_loop failed")


async def _run_all(cfg: cfgmod.Config) -> None:
    tasks = [
        asyncio.create_task(userbot.run(cfg), name="userbot"),
        asyncio.create_task(controlbot.run(cfg), name="controlbot"),
        asyncio.create_task(_prune_loop(), name="prune_loop"),
    ]
    if cfg.signal_enabled:
        tasks.append(asyncio.create_task(signalbot.run(cfg), name="signalbot"))
    else:
        log.warning("Signal disabled (SIGNAL_PHONE_NUMBER unset)")

    stop = asyncio.Event()

    def _on_signal() -> None:
        log.info("shutdown signal received")
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _on_signal)
        except NotImplementedError:
            # Signal handlers not available on this platform (e.g. Windows).
            pass

    waiter = asyncio.create_task(stop.wait(), name="signal_waiter")
    done, _ = await asyncio.wait(
        [*tasks, waiter], return_when=asyncio.FIRST_COMPLETED
    )

    # If a task crashed (not the signal_waiter), surface its exception after cleanup.
    crashed: BaseException | None = None
    for t in done:
        if t is waiter:
            continue
        exc = t.exception()
        if exc is not None:
            log.error("task %s exited with %r — initiating shutdown", t.get_name(), exc)
            crashed = exc

    log.info("cancelling remaining tasks")
    for t in tasks:
        if not t.done():
            t.cancel()
    waiter.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

    if crashed is not None:
        raise crashed


def main() -> None:
    cfg = cfgmod.load()
    cfgmod.setup_logging(cfg.log_level)
    log.info(
        "starting autoresponder — timezone=%s, signal=%s, current local time=%s",
        cfg.timezone,
        "enabled" if cfg.signal_enabled else "disabled",
        datetime.now(ZoneInfo(cfg.timezone)).isoformat(timespec="seconds"),
    )
    asyncio.run(_init_then_run(cfg))


async def _init_then_run(cfg: cfgmod.Config) -> None:
    await st.init(cfg.timezone)
    await _run_all(cfg)


if __name__ == "__main__":
    main()
