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
    # Telethon userbot is optional — when disabled, the control bot's
    # Telegram Business handler is the only Telegram reply path.
    userbot_enabled: bool
    tg_api_id: int | None
    tg_api_hash: str | None
    control_bot_token: str
    owner_user_id: int
    signal_api_url: str
    signal_phone_number: str  # empty string means: skip Signal listener
    timezone: str
    log_level: str

    @property
    def signal_enabled(self) -> bool:
        return bool(self.signal_phone_number)


_REQUIRED_ALWAYS = (
    "TG_CONTROL_BOT_TOKEN",
    "TG_OWNER_USER_ID",
)
_REQUIRED_IF_USERBOT = (
    "TG_USER_BOT_API_ID",
    "TG_USER_BOT_API_HASH",
)


def _parse_bool(raw: str | None, default: bool) -> bool:
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _fatal(msg: str) -> "None":
    print(f"FATAL: {msg}", file=sys.stderr)
    sys.exit(1)


def load() -> Config:
    """Read env vars, validate, return a frozen Config. Exits on error."""
    # Smart default for userbot mode: if both API_ID and API_HASH are present
    # we assume userbot is wanted; if either is missing we assume Chat
    # Automation only. Explicit TG_USERBOT_ENABLED still wins. This prevents
    # the 'FATAL: missing required env vars' crash when someone removes the
    # userbot credentials without also setting the flag.
    creds_present = bool(
        os.environ.get("TG_USER_BOT_API_ID") and os.environ.get("TG_USER_BOT_API_HASH")
    )
    userbot_enabled = _parse_bool(
        os.environ.get("TG_USERBOT_ENABLED"), default=creds_present
    )

    required = list(_REQUIRED_ALWAYS)
    if userbot_enabled:
        required.extend(_REQUIRED_IF_USERBOT)
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        _fatal(f"missing required env vars: {', '.join(missing)}")

    tg_api_id: int | None = None
    tg_api_hash: str | None = None
    if userbot_enabled:
        try:
            tg_api_id = int(os.environ["TG_USER_BOT_API_ID"])
        except ValueError:
            _fatal("TG_USER_BOT_API_ID must be an integer")
        tg_api_hash = os.environ["TG_USER_BOT_API_HASH"]
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
        userbot_enabled=userbot_enabled,
        tg_api_id=tg_api_id,
        tg_api_hash=tg_api_hash,
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
