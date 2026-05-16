"""Telegram control bot — the friend's only interface.

Exposes both slash commands and an inline-keyboard menu. Every handler is
gated by the TG_OWNER_USER_ID check, so messages from anyone else are
silently ignored. Also runs the daily heartbeat task and provides the
delivery callback used by `notify` for error pushes from the listeners.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time as dtime, timedelta
from functools import wraps
from typing import Awaitable, Callable
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    ApplicationBuilder,
    BusinessConnectionHandler,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from . import notify, state as st
from .config import Config

log = logging.getLogger(__name__)

# Keys used in context.user_data to remember a multi-step flow.
AWAIT_MESSAGE = "awaiting_message"
AWAIT_FROM = "awaiting_from"
AWAIT_UNTIL = "awaiting_until"


def _owner_only(handler: Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]):
    """Decorator: drop messages from anyone except TG_OWNER_USER_ID."""

    @wraps(handler)
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        cfg: Config = ctx.application.bot_data["cfg"]
        user = update.effective_user
        if not user or user.id != cfg.owner_user_id:
            log.warning(
                "rejected control-bot access from user_id=%s (@%s)",
                user.id if user else "?",
                user.username if user else "?",
            )
            return
        await handler(update, ctx)

    return wrapper


# ---------------------------------------------------------------------------
# Menus
# ---------------------------------------------------------------------------

def _main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🟢 On", callback_data="on"),
                InlineKeyboardButton("🔴 Off", callback_data="off"),
            ],
            [
                InlineKeyboardButton("⏰ Schedule", callback_data="schedule_menu"),
                InlineKeyboardButton("📊 Status", callback_data="status"),
            ],
            [
                InlineKeyboardButton("✏️ Message", callback_data="message"),
                InlineKeyboardButton("⚙️ Platforms", callback_data="platforms_menu"),
            ],
        ]
    )


def _schedule_menu(state: dict) -> InlineKeyboardMarkup:
    sched = state["schedule"]
    weekend_label = "✅ Weekends always on" if sched["weekends_always"] else "⬜ Weekends always on"
    activate_label = (
        "✅ Scheduled mode active"
        if sched["enabled"]
        else "Activate scheduled mode"
    )
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(f"Edit start ({sched['active_from']})", callback_data="edit_from")],
            [InlineKeyboardButton(f"Edit end ({sched['active_until']})", callback_data="edit_until")],
            [InlineKeyboardButton(weekend_label, callback_data="toggle_weekends")],
            [InlineKeyboardButton(activate_label, callback_data="schedule_on")],
            [InlineKeyboardButton("⬅ Back", callback_data="main_menu")],
        ]
    )


def _platforms_menu(state: dict) -> InlineKeyboardMarkup:
    tg = "🟢" if state["platforms"]["telegram"] else "🔴"
    sg = "🟢" if state["platforms"]["signal"] else "🔴"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(f"{tg} Telegram", callback_data="toggle_telegram")],
            [InlineKeyboardButton(f"{sg} Signal", callback_data="toggle_signal")],
            [InlineKeyboardButton("⬅ Back", callback_data="main_menu")],
        ]
    )


def _format_status(state: dict, cfg: Config) -> str:
    sched = state["schedule"]
    tz = ZoneInfo(sched["timezone"])
    now_local = datetime.now(tz).strftime("%H:%M %Z")
    active = "✅ active right now" if st.should_reply_now(state) else "⏸ not active right now"
    mode = "scheduled" if sched["enabled"] else "manual"
    weekends = "always on" if sched["weekends_always"] else "off"
    msg_preview = state["message"]
    if len(msg_preview) > 200:
        msg_preview = msg_preview[:200] + "…"
    return (
        f"<b>Status</b>\n"
        f"Master switch: {'ON' if state['enabled'] else 'OFF'}\n"
        f"Mode: {mode}\n"
        f"Schedule: {sched['active_from']}–{sched['active_until']} {sched['timezone']} (weekends {weekends})\n"
        f"Telegram: {'on' if state['platforms']['telegram'] else 'off'}\n"
        f"Signal: {'on' if state['platforms']['signal'] else 'off'}\n"
        f"Cooldown: {state['cooldown_hours']}h\n"
        f"Now: {now_local} → {active}\n"
        f"\n<b>Auto-reply text:</b>\n<code>{msg_preview}</code>"
    )


# ---------------------------------------------------------------------------
# Slash commands
# ---------------------------------------------------------------------------

@_owner_only
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Hi! I'm your autoresponder control bot. Use the menu below or /help for commands.",
        reply_markup=_main_menu(),
    )


@_owner_only
async def cmd_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("What would you like to do?", reply_markup=_main_menu())


@_owner_only
async def cmd_on(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    state = await st.load()
    state["enabled"] = True
    state["schedule"]["enabled"] = False
    await st.save(state)
    await update.message.reply_text("🟢 Autoresponder is now ON (manual mode).")


@_owner_only
async def cmd_off(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    state = await st.load()
    state["enabled"] = False
    await st.save(state)
    await update.message.reply_text("🔴 Autoresponder is now OFF.")


@_owner_only
async def cmd_schedule(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    state = await st.load()
    state["enabled"] = True
    state["schedule"]["enabled"] = True
    await st.save(state)
    sched = state["schedule"]
    await update.message.reply_text(
        f"⏰ Scheduled mode active: {sched['active_from']}–{sched['active_until']} "
        f"{sched['timezone']} (weekends "
        f"{'always on' if sched['weekends_always'] else 'off'})."
    )


@_owner_only
async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    state = await st.load()
    cfg: Config = ctx.application.bot_data["cfg"]
    await update.message.reply_text(_format_status(state, cfg), parse_mode=ParseMode.HTML)


@_owner_only
async def cmd_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text or ""
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        ctx.user_data[AWAIT_MESSAGE] = True
        await update.message.reply_text(
            "Send me the new auto-reply text in your next message."
        )
        return
    new = parts[1].strip()
    state = await st.load()
    state["message"] = new
    await st.save(state)
    await update.message.reply_text("✏️ Auto-reply text updated.")


@_owner_only
async def cmd_platforms(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text or ""
    parts = text.split()
    if len(parts) != 3 or parts[1] not in ("telegram", "signal") or parts[2] not in ("on", "off"):
        await update.message.reply_text("Usage: /platforms <telegram|signal> <on|off>")
        return
    platform, mode = parts[1], parts[2]
    state = await st.load()
    state["platforms"][platform] = mode == "on"
    await st.save(state)
    await update.message.reply_text(f"⚙️ {platform} is now {mode}.")


@_owner_only
async def cmd_setschedule(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text or ""
    parts = text.split()
    if len(parts) != 3:
        await update.message.reply_text("Usage: /setschedule HH:MM HH:MM (e.g. /setschedule 18:00 08:00)")
        return
    try:
        dtime.fromisoformat(parts[1])
        dtime.fromisoformat(parts[2])
    except ValueError:
        await update.message.reply_text("Times must be HH:MM, e.g. 18:00.")
        return
    state = await st.load()
    state["schedule"]["active_from"] = parts[1]
    state["schedule"]["active_until"] = parts[2]
    await st.save(state)
    await update.message.reply_text(
        f"⏰ Schedule window updated: {parts[1]}–{parts[2]} {state['schedule']['timezone']}."
    )


@_owner_only
async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Here's what I can do:\n\n"
        "/menu — show buttons for everything below\n"
        "/on — start replying now (manual mode)\n"
        "/off — stop replying\n"
        "/schedule — use the schedule (evenings + weekends by default)\n"
        "/status — what's happening right now\n"
        "/message <text> — change the auto-reply text\n"
        "/setschedule HH:MM HH:MM — change the active window\n"
        "/platforms <telegram|signal> <on|off> — turn one platform on/off\n"
        "\nIf you stop seeing my daily 'running' message, something is wrong — call your tech helper."
    )


# ---------------------------------------------------------------------------
# Inline keyboard callbacks
# ---------------------------------------------------------------------------

@_owner_only
async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None:
        return
    await query.answer()
    data = query.data or ""
    cfg: Config = ctx.application.bot_data["cfg"]

    if data == "main_menu":
        await query.edit_message_text("What would you like to do?", reply_markup=_main_menu())
        return
    if data == "on":
        state = await st.load()
        state["enabled"] = True
        state["schedule"]["enabled"] = False
        await st.save(state)
        await query.edit_message_text(
            "🟢 Autoresponder is now ON (manual mode).", reply_markup=_main_menu()
        )
        return
    if data == "off":
        state = await st.load()
        state["enabled"] = False
        await st.save(state)
        await query.edit_message_text("🔴 Autoresponder is now OFF.", reply_markup=_main_menu())
        return
    if data == "status":
        state = await st.load()
        await query.edit_message_text(
            _format_status(state, cfg), parse_mode=ParseMode.HTML, reply_markup=_main_menu()
        )
        return
    if data == "message":
        ctx.user_data[AWAIT_MESSAGE] = True
        await query.edit_message_text(
            "Send me the new auto-reply text in your next message.\n\n(Or send /menu to cancel.)"
        )
        return
    if data == "schedule_menu":
        state = await st.load()
        await query.edit_message_text(
            f"⏰ Schedule settings (timezone {state['schedule']['timezone']}):",
            reply_markup=_schedule_menu(state),
        )
        return
    if data == "edit_from":
        ctx.user_data[AWAIT_FROM] = True
        await query.edit_message_text(
            "Send the new <b>start</b> time as HH:MM (e.g. <code>18:00</code>).",
            parse_mode=ParseMode.HTML,
        )
        return
    if data == "edit_until":
        ctx.user_data[AWAIT_UNTIL] = True
        await query.edit_message_text(
            "Send the new <b>end</b> time as HH:MM (e.g. <code>08:00</code>).",
            parse_mode=ParseMode.HTML,
        )
        return
    if data == "toggle_weekends":
        state = await st.load()
        state["schedule"]["weekends_always"] = not state["schedule"]["weekends_always"]
        await st.save(state)
        await query.edit_message_text(
            f"⏰ Schedule settings (timezone {state['schedule']['timezone']}):",
            reply_markup=_schedule_menu(state),
        )
        return
    if data == "schedule_on":
        state = await st.load()
        state["enabled"] = True
        state["schedule"]["enabled"] = True
        await st.save(state)
        await query.edit_message_text(
            "✅ Scheduled mode active.\n\n"
            f"Window: {state['schedule']['active_from']}–{state['schedule']['active_until']} "
            f"{state['schedule']['timezone']}",
            reply_markup=_main_menu(),
        )
        return
    if data == "platforms_menu":
        state = await st.load()
        await query.edit_message_text(
            "⚙️ Tap a platform to toggle it:",
            reply_markup=_platforms_menu(state),
        )
        return
    if data == "toggle_telegram":
        state = await st.load()
        state["platforms"]["telegram"] = not state["platforms"]["telegram"]
        await st.save(state)
        await query.edit_message_text(
            "⚙️ Tap a platform to toggle it:", reply_markup=_platforms_menu(state)
        )
        return
    if data == "toggle_signal":
        state = await st.load()
        state["platforms"]["signal"] = not state["platforms"]["signal"]
        await st.save(state)
        await query.edit_message_text(
            "⚙️ Tap a platform to toggle it:", reply_markup=_platforms_menu(state)
        )
        return

    log.warning("unhandled callback_data=%r", data)


# ---------------------------------------------------------------------------
# Free-text capture for multi-step flows (✏️ Message, edit start/end times)
# ---------------------------------------------------------------------------

@_owner_only
async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip()

    if ctx.user_data.pop(AWAIT_MESSAGE, False):
        state = await st.load()
        state["message"] = text
        await st.save(state)
        await update.message.reply_text(
            "✏️ Auto-reply text updated.", reply_markup=_main_menu()
        )
        return

    if ctx.user_data.pop(AWAIT_FROM, False):
        try:
            dtime.fromisoformat(text)
        except ValueError:
            await update.message.reply_text(
                "That doesn't look like HH:MM. Try again from the ⏰ Schedule menu.",
                reply_markup=_main_menu(),
            )
            return
        state = await st.load()
        state["schedule"]["active_from"] = text
        await st.save(state)
        await update.message.reply_text(
            f"⏰ Start time set to {text}.", reply_markup=_schedule_menu(state)
        )
        return

    if ctx.user_data.pop(AWAIT_UNTIL, False):
        try:
            dtime.fromisoformat(text)
        except ValueError:
            await update.message.reply_text(
                "That doesn't look like HH:MM. Try again from the ⏰ Schedule menu.",
                reply_markup=_main_menu(),
            )
            return
        state = await st.load()
        state["schedule"]["active_until"] = text
        await st.save(state)
        await update.message.reply_text(
            f"⏰ End time set to {text}.", reply_markup=_schedule_menu(state)
        )
        return

    # No flow expected — just show the menu so the user has something to do.
    await update.message.reply_text("Use the menu:", reply_markup=_main_menu())


# ---------------------------------------------------------------------------
# Telegram Business / Chat Automation — the auto-reply path
# ---------------------------------------------------------------------------
# To attach this bot to a user account via Settings → Chat Automation:
#   1. Enable Business Mode in @BotFather
#      (/mybots → bot → Bot Settings → Business Mode → Enable).
#   2. The bot's allowed_updates list (set in start_polling below) must
#      declare business_connection and business_message — Telegram otherwise
#      rejects attachment with "this bot doesn't support Telegram business
#      yet".
#
# Note: the per-permission UI checkboxes ("Reply to Messages", "Mark as
# Read"…) may visually bounce back unchecked. That's a Telegram client-side
# display issue; the underlying can_reply=True flag in the business_connection
# update is the actual API gate, and sendMessage(business_connection_id=...)
# is accepted regardless of the UI state.


async def on_business_connection(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    bc = update.business_connection
    if bc is None:
        return
    cfg: Config = ctx.application.bot_data["cfg"]
    if bc.user.id != cfg.owner_user_id:
        log.warning(
            "business_connection from non-owner user_id=%s ignored", bc.user.id
        )
        return
    log.info(
        "business_connection: id=%s is_enabled=%s can_reply=%s user_chat_id=%s",
        bc.id, bc.is_enabled, bc.can_reply, bc.user_chat_id,
    )


async def on_business_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Auto-reply to incoming DMs delivered via Chat Automation.

    Filter pipeline mirrors the legacy userbot.py exactly:
      1. skip if sender info is missing (Telegram quirk)
      2. skip bots and the owner's own outgoing messages
      3. master switch + per-platform switch must be on
      4. schedule must say we're active right now
      5. cooldown must have elapsed for this sender
    """
    msg = update.business_message
    if msg is None or msg.from_user is None:
        return
    cfg: Config = ctx.application.bot_data["cfg"]

    text = msg.text or msg.caption or ""
    log.info(
        "business_message: connection_id=%s from_user_id=%s chat_id=%s text=%r",
        msg.business_connection_id,
        msg.from_user.id,
        msg.chat.id if msg.chat else None,
        text[:200],
    )

    # Bot-to-bot loops are bad; the owner's own outgoing messages would
    # otherwise trigger replies to whoever they were writing to.
    if msg.from_user.is_bot or msg.from_user.id == cfg.owner_user_id:
        return

    state = await st.load()
    if not state["platforms"]["telegram"]:
        return
    if not st.should_reply_now(state):
        return
    if not st.should_reply_to_user(state, "telegram", msg.from_user.id):
        return

    try:
        await ctx.bot.send_message(
            business_connection_id=msg.business_connection_id,
            chat_id=msg.chat.id,
            text=state["message"],
        )
    except Exception:
        log.exception("failed to send business auto-reply to user %s", msg.from_user.id)
        return

    st.record_reply(state, "telegram", msg.from_user.id)
    await st.save(state)
    log.info("auto-replied to telegram user %s via business connection", msg.from_user.id)


# ---------------------------------------------------------------------------
# A note on platform-level access restriction (not possible for this bot)
# ---------------------------------------------------------------------------
# Telegram's Bot API has setManagedBotAccessSettings (Bot API 10.0, May
# 2026), but it only applies to "managed bots" — sub-bots created and owned
# programmatically by another bot. Regular bots created via @BotFather are
# not managed bots; calling the method on them returns BOT_ACCESS_FORBIDDEN.
#
# There is no API to hide or platform-restrict a normal bot. Anyone who
# knows the @handle can find it and start a chat. Access control therefore
# happens at the handler level: the _owner_only decorator above silently
# drops every update whose effective_user.id is not TG_OWNER_USER_ID. The
# rejection is logged, the sender sees no reply, the bot performs no work
# on their behalf — which is the strongest restriction available for a
# BotFather-created bot.


# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------

async def _heartbeat_loop(cfg: Config, app: Application) -> None:
    """Send the daily 'still running' DM at 00:00 in cfg.timezone."""
    tz = ZoneInfo(cfg.timezone)
    while True:
        now = datetime.now(tz)
        next_midnight = (now + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        wait_seconds = (next_midnight - now).total_seconds()
        log.info(
            "heartbeat scheduled for %s (in %.0fs)", next_midnight.isoformat(), wait_seconds
        )
        try:
            await asyncio.sleep(wait_seconds)
        except asyncio.CancelledError:
            return
        try:
            state = await st.load()
            await app.bot.send_message(
                chat_id=cfg.owner_user_id,
                text="✅ Autoresponder running.\n\n" + _format_status(state, cfg),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            log.exception("heartbeat send failed")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def run(cfg: Config) -> None:
    """Build the Application, register handlers, run polling, run heartbeat.

    Cancels cleanly on asyncio.CancelledError (SIGTERM) so docker compose
    down doesn't lose state."""
    app: Application = ApplicationBuilder().token(cfg.control_bot_token).build()
    app.bot_data["cfg"] = cfg

    # All owner-facing handlers must be restricted to UpdateType.MESSAGE,
    # otherwise PTB's MessageHandler/CommandHandler also matches
    # update.business_message (via update.effective_message). Without this
    # filter, a stranger DMing your business-connected account would route
    # to on_text/cmd_*, hit _owner_only, and get logged as a rejected access
    # — while on_business_message (registered later in the same group) would
    # never run. That's exactly the symptom we saw in the logs.
    msg_only = filters.UpdateType.MESSAGE
    app.add_handler(CommandHandler("start", cmd_start, filters=msg_only))
    app.add_handler(CommandHandler("menu", cmd_menu, filters=msg_only))
    app.add_handler(CommandHandler("on", cmd_on, filters=msg_only))
    app.add_handler(CommandHandler("off", cmd_off, filters=msg_only))
    app.add_handler(CommandHandler("schedule", cmd_schedule, filters=msg_only))
    app.add_handler(CommandHandler("status", cmd_status, filters=msg_only))
    app.add_handler(CommandHandler("message", cmd_message, filters=msg_only))
    app.add_handler(CommandHandler("platforms", cmd_platforms, filters=msg_only))
    app.add_handler(CommandHandler("setschedule", cmd_setschedule, filters=msg_only))
    app.add_handler(CommandHandler("help", cmd_help, filters=msg_only))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(
        MessageHandler(msg_only & filters.TEXT & ~filters.COMMAND, on_text)
    )
    # Chat Automation (Telegram Business) — separate update types, routed
    # exclusively to the business handlers thanks to the msg_only filter above.
    app.add_handler(BusinessConnectionHandler(on_business_connection))
    app.add_handler(
        MessageHandler(filters.UpdateType.BUSINESS_MESSAGE, on_business_message)
    )

    async def _on_error(_update: object, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        exc = ctx.error
        if isinstance(exc, BadRequest) and "Message is not modified" in str(exc):
            return  # benign: user tapped the same button twice
        log.exception("unhandled error in control bot", exc_info=exc)

    app.add_error_handler(_on_error)

    async def _deliver(message: str) -> None:
        await app.bot.send_message(chat_id=cfg.owner_user_id, text=message)

    notify.set_delivery(_deliver)

    heartbeat_task: asyncio.Task[None] | None = None
    try:
        await app.initialize()
        await app.start()
        await app.updater.start_polling(
            drop_pending_updates=True,
            allowed_updates=[
                Update.MESSAGE,
                Update.CALLBACK_QUERY,
                Update.BUSINESS_CONNECTION,
                Update.BUSINESS_MESSAGE,
                Update.EDITED_BUSINESS_MESSAGE,
                Update.DELETED_BUSINESS_MESSAGES,
            ],
        )
        log.info("control bot started")
        heartbeat_task = asyncio.create_task(_heartbeat_loop(cfg, app))
        # Block until cancelled by main()'s shutdown handler.
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        log.info("control bot shutting down")
        raise
    finally:
        if heartbeat_task is not None:
            heartbeat_task.cancel()
        try:
            if app.updater and app.updater.running:
                await app.updater.stop()
        except Exception:
            log.exception("error stopping updater")
        try:
            if app.running:
                await app.stop()
        except Exception:
            log.exception("error stopping application")
        try:
            await app.shutdown()
        except Exception:
            log.exception("error during application shutdown")
