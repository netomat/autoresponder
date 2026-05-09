"""Shared state management.

All three async tasks (Telegram userbot, Signal listener, control bot) read
and write the same state.json. A single asyncio.Lock serialises access, and
writes go through a temp file + rename so a crash mid-write cannot corrupt
the file.
"""

from __future__ import annotations

import asyncio
import json
import logging
from copy import deepcopy
from datetime import datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)

STATE_FILE = Path("/data/state.json")
_lock = asyncio.Lock()


def _default_state(timezone: str) -> dict[str, Any]:
    """The shape of state.json on first run."""
    return {
        "enabled": False,
        "message": "Hi! I'm currently away and will reply later.",
        "schedule": {
            "enabled": False,
            "timezone": timezone,
            "active_from": "18:00",
            "active_until": "08:00",
            "weekends_always": True,
        },
        "cooldown_hours": 6,
        "recently_replied": {"telegram": {}, "signal": {}},
        "platforms": {"telegram": True, "signal": True},
    }


async def init(timezone: str) -> None:
    """Create state.json with sensible defaults if it does not exist yet.

    Called once at startup. The TIMEZONE env var only seeds the file on
    first run — once the file exists the user controls the timezone via
    the control bot, so the env var is no longer authoritative.
    """
    async with _lock:
        if STATE_FILE.exists():
            return
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(_default_state(timezone))
        log.info("created fresh state at %s", STATE_FILE)


async def load() -> dict[str, Any]:
    """Read and return the full state dict. Caller may mutate freely;
    changes only persist when save() is called."""
    async with _lock:
        return json.loads(STATE_FILE.read_text())


async def save(state: dict[str, Any]) -> None:
    """Persist state atomically. Write to a temp file then rename so a
    crash mid-write leaves the previous version intact."""
    async with _lock:
        _atomic_write(state)


def _atomic_write(state: dict[str, Any]) -> None:
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(STATE_FILE)


def should_reply_now(state: dict[str, Any]) -> bool:
    """Decide whether the autoresponder is currently active.

    - False if the master switch is off.
    - In manual mode (schedule.enabled=False), always True when the master
      switch is on.
    - In scheduled mode, weekends are always-on if weekends_always is set,
      otherwise we check whether the current local time falls in the
      [active_from, active_until] window. Windows that cross midnight
      (e.g. 18:00–08:00) are handled.
    """
    if not state["enabled"]:
        return False
    sched = state["schedule"]
    if not sched["enabled"]:
        return True
    tz = ZoneInfo(sched["timezone"])
    now = datetime.now(tz)
    if sched["weekends_always"] and now.weekday() >= 5:
        return True
    start = time.fromisoformat(sched["active_from"])
    end = time.fromisoformat(sched["active_until"])
    cur = now.time()
    if start <= end:
        return start <= cur <= end
    # window crosses midnight
    return cur >= start or cur <= end


def should_reply_to_user(state: dict[str, Any], platform: str, user_key: str) -> bool:
    """True if we have not replied to this user within the cooldown window."""
    last = state["recently_replied"][platform].get(str(user_key))
    if not last:
        return True
    last_dt = datetime.fromisoformat(last)
    delta_hours = (datetime.now().astimezone() - last_dt).total_seconds() / 3600
    return delta_hours >= state["cooldown_hours"]


def record_reply(state: dict[str, Any], platform: str, user_key: str) -> None:
    """Stamp the current time as the last-replied timestamp for this user.
    Mutates `state` in place; caller is responsible for persisting it."""
    state["recently_replied"][platform][str(user_key)] = (
        datetime.now().astimezone().isoformat()
    )


def prune_recently_replied(state: dict[str, Any]) -> int:
    """Drop entries from recently_replied that are older than cooldown_hours * 2.

    Anything that old can no longer block a reply, so keeping it just bloats
    state.json. Returns the number of entries removed."""
    cutoff_hours = state["cooldown_hours"] * 2
    now = datetime.now().astimezone()
    removed = 0
    for platform_map in state["recently_replied"].values():
        stale = []
        for key, ts in platform_map.items():
            try:
                age_h = (now - datetime.fromisoformat(ts)).total_seconds() / 3600
            except ValueError:
                stale.append(key)
                continue
            if age_h >= cutoff_hours:
                stale.append(key)
        for key in stale:
            del platform_map[key]
            removed += 1
    return removed


def snapshot(state: dict[str, Any]) -> dict[str, Any]:
    """Deep copy of the state dict for safe inspection without mutation."""
    return deepcopy(state)
