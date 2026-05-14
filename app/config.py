"""Environment configuration for the autoresponder.

Loaded once at startup. Missing required variables cause the process to exit
with a clear message rather than crashing later in an obscure place.
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True)
class Config:
    tg_api_id: int
    tg_api_hash: str
    control_bot_token: str
    owner_user_id: int
    signal_api_url: str
    signal_phone_number: str  # empty string means: skip Signal listener
    timezone: str
    log_level: str

    @property
    def signal_enabled(self) -> bool:
        return bool(self.signal_phone_number)


_REQUIRED = (
    "TG_USER_BOT_API_ID",
    "TG_USER_BOT_API_HASH",
    "TG_CONTROL_BOT_TOKEN",
    "TG_OWNER_USER_ID",
)


def _fatal(msg: str) -> "None":
    print(f"FATAL: {msg}", file=sys.stderr)
    sys.exit(1)


def load() -> Config:
    """Read env vars, validate, return a frozen Config. Exits on error."""
    missing = [k for k in _REQUIRED if not os.environ.get(k)]
    if missing:
        _fatal(f"missing required env vars: {', '.join(missing)}")

    try:
        tg_api_id = int(os.environ["TG_USER_BOT_API_ID"])
    except ValueError:
        _fatal("TG_USER_BOT_API_ID must be an integer")
    try:
        owner_user_id = int(os.environ["TG_OWNER_USER_ID"])
    except ValueError:
        _fatal("TG_OWNER_USER_ID must be an integer (Telegram user id)")

    timezone = os.environ.get("TIMEZONE", "Europe/Berlin")
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        _fatal(f"TIMEZONE '{timezone}' is not a valid IANA zone name")

    signal_phone = os.environ.get("SIGNAL_PHONE_NUMBER", "").strip()
    if signal_phone and not signal_phone.startswith("+"):
        _fatal("SIGNAL_PHONE_NUMBER must be in E.164 format (e.g. +491701234567)")

    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
    if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        _fatal(f"LOG_LEVEL '{log_level}' is not a valid logging level")

    return Config(
        tg_api_id=tg_api_id,
        tg_api_hash=os.environ["TG_USER_BOT_API_HASH"],
        control_bot_token=os.environ["TG_CONTROL_BOT_TOKEN"],
        owner_user_id=owner_user_id,
        signal_api_url=os.environ.get("SIGNAL_API_URL", "http://signal-api:8080"),
        signal_phone_number=signal_phone,
        timezone=timezone,
        log_level=log_level,
    )


def setup_logging(level: str) -> None:
    """Configure root logger. Each module gets its own named logger."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    # Telethon and httpx are very chatty at INFO; bump them down a notch.
    logging.getLogger("telethon").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
