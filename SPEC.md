# Specification: Telegram + Signal Autoresponder

## Architecture

```
┌──────────────────────┐    ┌──────────────────────┐    ┌──────────────────────┐
│  TG Userbot          │    │  Signal Listener     │    │  Control Bot         │
│  (Telethon)          │    │  (WebSocket → REST) │    │  (python-telegram-   │
│  - listens to DMs    │    │  - listens to DMs    │    │   bot)               │
│  - sends auto-reply  │    │  - sends auto-reply  │    │  - /on /off /status  │
│                      │    │                      │    │  - inline keyboard   │
└──────────┬───────────┘    └──────────┬───────────┘    └──────────┬───────────┘
           │                            │                            │
           └────────────────┬───────────┴────────────────────────────┘
                            │
                      shared state.json
                      (asyncio.Lock-protected)

                  ┌────────────────────────────────────┐
                  │  signal-cli-rest-api (separate     │
                  │  container, exposes :8080,         │
                  │  MODE=json-rpc)                    │
                  └────────────────────────────────────┘
```

All three async tasks run in **one Python process** via `asyncio.gather`, sharing one state file. The Signal CLI runs in a **separate container** (`bbernhard/signal-cli-rest-api`).

## Project layout

```
autoresponder/
├── README.md
├── SPEC.md                  # this file
├── TESTING.md
├── DEPLOYMENT.md
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── Makefile                 # dev convenience commands
├── .env.example
├── .gitignore
├── app/
│   ├── __init__.py
│   ├── main.py              # asyncio entry point
│   ├── userbot.py           # Telethon handler (Telegram userbot)
│   ├── signalbot.py         # Signal WebSocket listener + REST sender
│   ├── controlbot.py        # python-telegram-bot control interface
│   ├── state.py             # shared state, schedule logic, cooldowns
│   └── config.py            # env var loading & validation
├── data/                    # mounted volume (gitignored)
│   ├── userbot.session      # created on first login
│   └── state.json           # created on first run
└── signal-data/             # mounted volume for signal-cli (gitignored)
```

## Configuration (env vars)

| Var | Description |
|---|---|
| `TG_API_ID` | Telegram app ID from my.telegram.org |
| `TG_API_HASH` | Telegram app hash from my.telegram.org |
| `CONTROL_BOT_TOKEN` | Token from @BotFather for the control bot |
| `OWNER_USER_ID` | Owner's Telegram user ID (for control bot access) |
| `SIGNAL_API_URL` | Default `http://signal-api:8080` (Docker network) |
| `SIGNAL_PHONE_NUMBER` | E.164 format, e.g. `+491701234567` |
| `TIMEZONE` | Default `Europe/Berlin`, used for schedule |
| `LOG_LEVEL` | Default `INFO` |

`config.py` should validate these at startup and fail fast with a clear error if missing.

## State schema (`data/state.json`)

```json
{
  "enabled": false,
  "message": "Hi! I'm currently away and will reply later.",
  "schedule": {
    "enabled": false,
    "timezone": "Europe/Berlin",
    "active_from": "18:00",
    "active_until": "08:00",
    "weekends_always": true
  },
  "cooldown_hours": 6,
  "recently_replied": {
    "telegram": {},
    "signal": {}
  },
  "platforms": {
    "telegram": true,
    "signal": true
  }
}
```

## Core logic — `state.py`

Implement these functions with an `asyncio.Lock` to make load/save concurrency-safe:

```python
async def load() -> dict
async def save(state: dict) -> None

def should_reply_now(state: dict) -> bool
    # False if state["enabled"] is False
    # If schedule disabled: True (manual mode)
    # If schedule enabled: check timezone-aware current time
    #   - If weekends_always and weekday in (5,6): True
    #   - Otherwise: time-window check; handle windows that cross midnight
    #     (e.g. 18:00–08:00 means current >= 18:00 OR current <= 08:00)

def should_reply_to_user(state: dict, platform: str, user_key: str) -> bool
    # Check recently_replied[platform][user_key] vs cooldown_hours
    # Returns True if no record or older than cooldown
```

After replying, update `state["recently_replied"][platform][user_key] = now_iso` and save.

Periodically (e.g. every hour) prune entries older than `cooldown_hours * 2` from `recently_replied` to prevent unbounded growth.

## Telegram userbot — `userbot.py`

- Use Telethon `TelegramClient` with session file at `/data/userbot`.
- Register a `@client.on(events.NewMessage(incoming=True))` handler.
- **Filter rules** in this order:
  - Skip if not `event.is_private` (groups, channels)
  - Skip if `sender.bot` or `sender.is_self`
  - Skip if `not should_reply_now(state)` or `not state["platforms"]["telegram"]`
  - Skip if `not should_reply_to_user(state, "telegram", sender.id)`
- Reply via `event.reply(state["message"])`.
- **Do NOT** call `mark_read` / `send_read_acknowledge` — let the message stay marked unread on the linked phone so the owner sees it later.
- On first run, `client.start()` will prompt for phone + SMS code interactively. Document this in DEPLOYMENT.md.

## Signal listener — `signalbot.py`

The `bbernhard/signal-cli-rest-api` container in `MODE=json-rpc` exposes:
- WebSocket: `ws://signal-api:8080/v1/receive/{phone_number}` — streams envelopes
- REST send: `POST http://signal-api:8080/v2/send` with body `{"message": str, "number": str, "recipients": [str]}`

Implementation:

- Connect to the WebSocket with `aiohttp.ClientSession.ws_connect`, `heartbeat=30`.
- On each text frame, parse JSON, extract `data["envelope"]`.
- **Filter rules:**
  - Skip if no `dataMessage` or no `dataMessage.message` (it's a typing indicator, receipt, etc.)
  - Skip if `groupInfo` or `groupV2` present (group message)
  - Skip if `source == SIGNAL_PHONE_NUMBER` (self)
  - Skip if `not state["platforms"]["signal"]`
  - Skip if `not should_reply_now(state)`
  - Skip if `not should_reply_to_user(state, "signal", sender_number)`
- Send reply via REST POST.
- **Reconnection logic:** wrap the whole WS connect in a `while True` with `try/except` and `await asyncio.sleep(10)` on failure. Log reconnects.

## Control bot — `controlbot.py`

This is the friend's primary interface. **Must be friendly to a non-technical user.**

### Owner-only decorator

Every handler must be wrapped to ignore messages from anyone other than `OWNER_USER_ID`. Failed access attempts should be logged but not replied to.

### Required commands & UI

Implement BOTH slash commands AND an inline-keyboard menu. Slash commands for power use, menu for the friend.

| Command | Behavior |
|---|---|
| `/start` | Welcome + show menu |
| `/menu` | Show inline keyboard with buttons: **🟢 On**, **🔴 Off**, **⏰ Schedule**, **📊 Status**, **✏️ Message**, **⚙️ Platforms** |
| `/on` | Enable manually (disables schedule mode) |
| `/off` | Disable autoresponder entirely |
| `/schedule` | Enable scheduled mode using current schedule settings |
| `/status` | Show: enabled?, schedule on/off, **active right now?**, per-platform on/off, current message |
| `/message <text>` | Update auto-reply text |
| `/platforms <telegram\|signal> <on\|off>` | Toggle a single platform |
| `/setschedule HH:MM HH:MM` | Update active_from / active_until |
| `/help` | Plain-language explanation of each command |

### Inline keyboard flow

Tapping **🟢 On** → calls the same logic as `/on`, edits the message to confirm "Autoresponder is now ON" and re-renders the menu below.

Tapping **✏️ Message** → bot replies "Send me the new auto-reply text in your next message" and uses `ConversationHandler` (or a simple per-user state dict) to capture the next message as the new template.

Tapping **⏰ Schedule** → submenu with "Edit start time", "Edit end time", "Toggle weekends", "Activate scheduled mode".

### Heartbeat (required)

Every 24 hours, the control bot DMs the owner: "✅ Autoresponder running. Status: …". Use `asyncio.create_task` with a sleep loop. If the owner stops seeing this, something's wrong.

### Error notifications (required)

When the Telegram or Signal listener catches an exception in its main loop, push a message to the owner via the control bot: "⚠️ Signal listener disconnected, retrying…". Throttle to at most one notification per error type per hour to avoid spam.

## Polish requirements

- **Logging**: Python `logging` module, format `%(asctime)s [%(levelname)s] %(name)s: %(message)s`. Levels controlled by `LOG_LEVEL`. Each module gets its own logger.
- **Graceful shutdown**: Handle SIGTERM cleanly so `docker compose down` doesn't lose state mid-write.
- **Atomic state writes**: Write `state.json` via temp file + rename to avoid corruption on crash.
- **Type hints** throughout. The user is learning Python — clean, well-typed code matters.
- **Docstrings** on every public function explaining what and why.

## Code sketches

Use these as **starting points only**. Improve, harden, add error handling.

### `app/state.py` (sketch)

```python
import json
import asyncio
from pathlib import Path
from datetime import datetime, time
from zoneinfo import ZoneInfo

STATE_FILE = Path("/data/state.json")
_lock = asyncio.Lock()

DEFAULT_STATE = {
    "enabled": False,
    "message": "Hi! I'm currently away and will reply later.",
    "schedule": {
        "enabled": False,
        "timezone": "Europe/Berlin",
        "active_from": "18:00",
        "active_until": "08:00",
        "weekends_always": True,
    },
    "cooldown_hours": 6,
    "recently_replied": {"telegram": {}, "signal": {}},
    "platforms": {"telegram": True, "signal": True},
}


async def load() -> dict:
    async with _lock:
        if not STATE_FILE.exists():
            STATE_FILE.write_text(json.dumps(DEFAULT_STATE, indent=2))
            return dict(DEFAULT_STATE)
        return json.loads(STATE_FILE.read_text())


async def save(state: dict) -> None:
    async with _lock:
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2))
        tmp.replace(STATE_FILE)


def should_reply_now(state: dict) -> bool:
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
    return cur >= start or cur <= end


def should_reply_to_user(state: dict, platform: str, user_key: str) -> bool:
    last = state["recently_replied"][platform].get(str(user_key))
    if not last:
        return True
    last_dt = datetime.fromisoformat(last)
    hours = (datetime.now().astimezone() - last_dt).total_seconds() / 3600
    return hours >= state["cooldown_hours"]
```

### `app/userbot.py` (sketch)

```python
import os
from datetime import datetime
from telethon import TelegramClient, events
from . import state as st

API_ID = int(os.environ["TG_API_ID"])
API_HASH = os.environ["TG_API_HASH"]
SESSION = "/data/userbot"

client = TelegramClient(SESSION, API_ID, API_HASH)


@client.on(events.NewMessage(incoming=True))
async def handler(event):
    if not event.is_private:
        return
    sender = await event.get_sender()
    if sender.bot or sender.is_self:
        return

    state = await st.load()
    if not state["platforms"]["telegram"]:
        return
    if not st.should_reply_now(state):
        return
    if not st.should_reply_to_user(state, "telegram", sender.id):
        return

    await event.reply(state["message"])
    state["recently_replied"]["telegram"][str(sender.id)] = (
        datetime.now().astimezone().isoformat()
    )
    await st.save(state)


async def run_userbot():
    await client.start()
    print("Userbot started")
    await client.run_until_disconnected()
```

### `app/signalbot.py` (sketch)

```python
import os
import json
import asyncio
import aiohttp
from datetime import datetime
from . import state as st

SIGNAL_API = os.environ.get("SIGNAL_API_URL", "http://signal-api:8080")
SIGNAL_NUMBER = os.environ["SIGNAL_PHONE_NUMBER"]


async def send_message(session: aiohttp.ClientSession, recipient: str, text: str):
    url = f"{SIGNAL_API}/v2/send"
    payload = {"message": text, "number": SIGNAL_NUMBER, "recipients": [recipient]}
    async with session.post(url, json=payload) as resp:
        if resp.status >= 300:
            print(f"Signal send failed: {resp.status} {await resp.text()}")


async def handle_envelope(session, envelope):
    msg = envelope.get("dataMessage")
    if not msg or not msg.get("message"):
        return
    if msg.get("groupInfo") or msg.get("groupV2"):
        return
    sender = envelope.get("source") or envelope.get("sourceNumber")
    if not sender or sender == SIGNAL_NUMBER:
        return

    state = await st.load()
    if not state["platforms"]["signal"]:
        return
    if not st.should_reply_now(state):
        return
    if not st.should_reply_to_user(state, "signal", sender):
        return

    await send_message(session, sender, state["message"])
    state["recently_replied"]["signal"][sender] = (
        datetime.now().astimezone().isoformat()
    )
    await st.save(state)


async def run_signalbot():
    ws_url = SIGNAL_API.replace("http://", "ws://").replace("https://", "wss://")
    ws_url = f"{ws_url}/v1/receive/{SIGNAL_NUMBER}"
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                async with session.ws_connect(ws_url, heartbeat=30) as ws:
                    print("Signal listener connected")
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = json.loads(msg.data)
                            envelope = data.get("envelope")
                            if envelope:
                                await handle_envelope(session, envelope)
            except Exception as e:
                print(f"Signal WS error, reconnecting in 10s: {e}")
                await asyncio.sleep(10)
```

### `app/controlbot.py` (sketch — extend with inline keyboards)

```python
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes
from . import state as st

BOT_TOKEN = os.environ["CONTROL_BOT_TOKEN"]
OWNER_ID = int(os.environ["OWNER_USER_ID"])


def owner_only(func):
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if not user or user.id != OWNER_ID:
            return
        return await func(update, ctx)
    return wrapper


def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🟢 On", callback_data="on"),
         InlineKeyboardButton("🔴 Off", callback_data="off")],
        [InlineKeyboardButton("⏰ Schedule", callback_data="schedule"),
         InlineKeyboardButton("📊 Status", callback_data="status")],
        [InlineKeyboardButton("✏️ Message", callback_data="message"),
         InlineKeyboardButton("⚙️ Platforms", callback_data="platforms")],
    ])


@owner_only
async def cmd_menu(update, ctx):
    await update.message.reply_text("What would you like to do?", reply_markup=main_menu())

# ... callback query handler that dispatches by callback_data
# ... slash commands as listed in the table above
```

### `app/main.py` (sketch)

```python
import asyncio
import logging
from .userbot import run_userbot
from .signalbot import run_signalbot
from .controlbot import run_controlbot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


async def main():
    await asyncio.gather(
        run_userbot(),
        run_signalbot(),
        run_controlbot(),
    )


if __name__ == "__main__":
    asyncio.run(main())
```

### `requirements.txt`

```
telethon==1.36.0
python-telegram-bot==21.6
aiohttp==3.10.5
```

(Pin to current versions; update once on first build.)

### `Dockerfile`

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ ./app/
CMD ["python", "-m", "app.main"]
```

### `docker-compose.yml`

```yaml
services:
  signal-api:
    image: bbernhard/signal-cli-rest-api:latest
    container_name: signal-api
    restart: unless-stopped
    environment:
      MODE: json-rpc
    volumes:
      - ./signal-data:/home/.local/share/signal-cli
    ports:
      - "8080:8080"   # needed during linking; can be removed afterward

  autoresponder:
    build: .
    container_name: autoresponder
    restart: unless-stopped
    depends_on:
      - signal-api
    environment:
      TG_API_ID: "${TG_API_ID}"
      TG_API_HASH: "${TG_API_HASH}"
      CONTROL_BOT_TOKEN: "${CONTROL_BOT_TOKEN}"
      OWNER_USER_ID: "${OWNER_USER_ID}"
      SIGNAL_API_URL: "http://signal-api:8080"
      SIGNAL_PHONE_NUMBER: "${SIGNAL_PHONE_NUMBER}"
      TIMEZONE: "${TIMEZONE:-Europe/Berlin}"
      LOG_LEVEL: "${LOG_LEVEL:-INFO}"
    volumes:
      - ./data:/data
```

### `.env.example`

```
TG_API_ID=
TG_API_HASH=
CONTROL_BOT_TOKEN=
OWNER_USER_ID=
SIGNAL_PHONE_NUMBER=+49...
TIMEZONE=Europe/Berlin
LOG_LEVEL=INFO
```

## Acceptance criteria

The implementation is complete when:

1. ✅ `docker compose up` brings up both containers and Python logs show "Userbot started", "Signal listener connected", "Control bot started".
2. ✅ Sending a DM to the owner's Telegram while autoresponder is ON triggers exactly one auto-reply.
3. ✅ Sending 5 DMs in a row triggers exactly one reply (cooldown works).
4. ✅ Sending a Signal DM produces the same behavior.
5. ✅ Group messages on either platform produce no reply.
6. ✅ Self-messages produce no reply.
7. ✅ `/off` from the control bot stops replies immediately.
8. ✅ Schedule mode correctly handles a window crossing midnight (18:00–08:00).
9. ✅ State survives container restart.
10. ✅ Killing & restarting `signal-api` causes the listener to reconnect within 30s.
11. ✅ Control bot ignores messages from non-owner Telegram users.
12. ✅ Inline-keyboard menu works end-to-end (tap → state changes → confirmation rendered).
13. ✅ Daily heartbeat DM arrives.

## Out of scope (do not implement)

- Web UI / dashboard
- Per-contact whitelists or custom replies (could be added later)
- Multi-tenant / multi-owner support
- Telegram bot username detection beyond `sender.bot`
- Vacation auto-reply with end date (could be added later)
- Importing message templates from a file
