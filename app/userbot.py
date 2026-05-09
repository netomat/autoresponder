"""Telegram userbot — listens for incoming DMs on the owner's personal
account and auto-replies according to the shared state."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from telethon import TelegramClient, events

from . import notify, state as st
from .config import Config

log = logging.getLogger(__name__)

# Telethon adds the .session suffix itself; the file ends up at /data/userbot.session
SESSION_PATH = "/data/userbot"


def _build_client(cfg: Config) -> TelegramClient:
    return TelegramClient(SESSION_PATH, cfg.tg_api_id, cfg.tg_api_hash)


async def run(cfg: Config) -> None:
    """Run the userbot. Reconnects internally via Telethon; if startup
    authentication fails (no session), we notify the owner and re-raise so
    main() can decide what to do."""
    client = _build_client(cfg)

    @client.on(events.NewMessage(incoming=True))
    async def _handler(event):  # type: ignore[no-untyped-def]
        try:
            await _handle_message(event)
        except Exception:
            log.exception("userbot handler raised")
            await notify.notify("userbot", "Telegram handler error — see logs.")

    await client.connect()
    if not await client.is_user_authorized():
        msg = (
            f"Telegram session at {SESSION_PATH}.session is missing or invalid. "
            "Run `make tg-login` to create it before starting the autoresponder."
        )
        log.error(msg)
        await notify.notify("userbot", msg)
        raise RuntimeError(msg)

    me = await client.get_me()
    log.info("userbot started as @%s (id=%s)", me.username, me.id)
    try:
        await client.run_until_disconnected()
    except asyncio.CancelledError:
        log.info("userbot shutting down")
        raise
    finally:
        await client.disconnect()


async def _handle_message(event) -> None:  # type: ignore[no-untyped-def]
    """Apply the filter pipeline and reply if appropriate.

    Filter order matches SPEC.md exactly:
      1. private chats only (no groups, no channels)
      2. no bots, no self
      3. master switch + per-platform switch must be on
      4. schedule must say we're active right now
      5. cooldown must have elapsed for this sender
    """
    if not event.is_private:
        return
    sender = await event.get_sender()
    if sender is None or getattr(sender, "bot", False) or getattr(sender, "is_self", False):
        return

    state = await st.load()
    if not state["platforms"]["telegram"]:
        return
    if not st.should_reply_now(state):
        return
    if not st.should_reply_to_user(state, "telegram", sender.id):
        return

    await event.reply(state["message"])
    st.record_reply(state, "telegram", sender.id)
    await st.save(state)
    log.info("auto-replied to telegram user %s", sender.id)
