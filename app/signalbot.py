"""Signal listener — connects to the bbernhard/signal-cli-rest-api
container's WebSocket, applies the same filter pipeline as the Telegram
userbot, and sends auto-replies via the REST endpoint."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import aiohttp

from . import notify, state as st
from .config import Config

log = logging.getLogger(__name__)

_RECONNECT_DELAY_SECONDS = 10
_WS_HEARTBEAT_SECONDS = 30


async def run(cfg: Config) -> None:
    """Main loop. Reconnects every 10s on any WS error. Notifies the owner
    (throttled) the first time a disconnect happens within an hour."""
    if not cfg.signal_enabled:
        log.info("Signal disabled (SIGNAL_PHONE_NUMBER unset) — listener will not start")
        return

    ws_url = (
        cfg.signal_api_url.replace("http://", "ws://").replace("https://", "wss://")
        + f"/v1/receive/{cfg.signal_phone_number}"
    )
    log.info("Signal listener connecting to %s", ws_url)

    async with aiohttp.ClientSession() as session:
        while True:
            try:
                await _consume(session, ws_url, cfg)
            except asyncio.CancelledError:
                log.info("Signal listener shutting down")
                raise
            except Exception as exc:
                log.warning("Signal WS error: %s — reconnecting in %ss", exc, _RECONNECT_DELAY_SECONDS)
                await notify.notify(
                    "signalbot",
                    f"Signal listener disconnected ({exc.__class__.__name__}). Retrying.",
                )
                await asyncio.sleep(_RECONNECT_DELAY_SECONDS)


async def _consume(session: aiohttp.ClientSession, ws_url: str, cfg: Config) -> None:
    async with session.ws_connect(ws_url, heartbeat=_WS_HEARTBEAT_SECONDS) as ws:
        log.info("Signal listener connected")
        async for msg in ws:
            if msg.type != aiohttp.WSMsgType.TEXT:
                continue
            try:
                data = json.loads(msg.data)
            except json.JSONDecodeError:
                log.debug("ignoring non-JSON frame")
                continue
            envelope = data.get("envelope")
            if envelope:
                await _handle_envelope(session, envelope, cfg)


async def _handle_envelope(
    session: aiohttp.ClientSession, envelope: dict[str, Any], cfg: Config
) -> None:
    """Apply the same filter pipeline as the Telegram userbot, then send a
    reply over the REST endpoint."""
    msg = envelope.get("dataMessage")
    if not msg or not msg.get("message"):
        return  # typing indicator, receipt, sync, etc.
    if msg.get("groupInfo") or msg.get("groupV2"):
        return  # group message
    sender = envelope.get("source") or envelope.get("sourceNumber")
    if not sender or sender == cfg.signal_phone_number:
        return  # self / sync from another linked device

    state = await st.load()
    if not state["platforms"]["signal"]:
        return
    if not st.should_reply_now(state):
        return
    if not st.should_reply_to_user(state, "signal", sender):
        return

    await _send_message(session, cfg, sender, state["message"])
    st.record_reply(state, "signal", sender)
    await st.save(state)
    log.info("auto-replied to signal user %s", sender)


async def _send_message(
    session: aiohttp.ClientSession, cfg: Config, recipient: str, text: str
) -> None:
    url = f"{cfg.signal_api_url}/v2/send"
    payload = {"message": text, "number": cfg.signal_phone_number, "recipients": [recipient]}
    async with session.post(url, json=payload) as resp:
        if resp.status >= 300:
            body = await resp.text()
            log.error("signal send failed %s: %s", resp.status, body)
            await notify.notify(
                "signalbot",
                f"Signal send failed (HTTP {resp.status}). Check signal-api logs.",
            )
