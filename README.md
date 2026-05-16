# Telegram + Signal Autoresponder

A self-hosted "I'm away" auto-replier for your **personal** Telegram and Signal accounts. It runs on a QNAP NAS (or any Linux box with Docker) and you control it from a small Telegram bot on your phone — turn it on, off, change the message, schedule it for evenings & weekends.

> **You are not a developer? That's fine.** This guide walks you through it step by step. You will need ~45 minutes the first time, and a friend with some technical skill if you get stuck. After that you only ever use a Telegram bot — no terminal, no SSH, nothing scary.

> 🤖 **Built with [Claude](https://www.anthropic.com/claude)** (Anthropic's AI assistant) via [Claude Code](https://docs.claude.com/en/docs/claude-code), guided end-to-end by Marcel Reuter (review, testing, deployment, security decisions).

---

## What it does

- Someone messages you on Telegram or Signal → they get an automatic reply ("I'm away, will reply later").
- You don't get spammed: the same person only gets one reply every few hours.
- Group chats are ignored — only direct messages trigger a reply.
- You can turn it on and off from your phone via a control bot (it's like a remote control).

## What you need

1. **A QNAP NAS** with the **Container Station** app installed (free in the QNAP App Center) — *or* any Linux box with Docker.
2. **SSH access** to that machine, and `git` + `docker` + `docker compose` + `make` installed there.
3. **Your phone** with both Telegram and Signal installed and working.
4. **About 45 minutes** the first time.
5. **Optionally a friend who knows Linux** for the parts that touch the NAS terminal — but the steps below are copy-pasteable.

---

## Where credentials live

Everything that identifies you to Telegram and Signal lives in **one folder**, `environment/`:

```
environment/
├── .env                  ← TG API keys, bot token, your TG user id, Signal number  (you create this)
├── data/
│   ├── userbot.session   ← Telegram session (logged-in-as-you state)               (auto-created)
│   └── state.json        ← runtime settings (on/off, schedule, cooldown)           (auto-created)
└── signal-data/          ← Signal linked-device state (encrypted)                  (auto-created)
```

**What `./install.sh` and the containers create for you:**

- `environment/` (the folder itself) — created on first run of `./install.sh` if missing.
- `environment/.env` — copied from `.env.example` by `./install.sh` if missing. The installer then exits and tells you to edit it before re-running. **You fill in the values.**
- `environment/data/` and `environment/signal-data/` — created automatically when the containers first start. `userbot.session` is written by `make tg-login` (step 4 of the installer), `state.json` by the autoresponder on first start, `signal-data/*` by `signal-api` when you scan the QR code.

You don't need to `mkdir` anything by hand. The only file you have to create yourself is the *contents* of `environment/.env` — and the installer prompts for that too.

**What `.env.example` looks like** (it's checked into git as a template — all values blank):

```bash
# Telegram userbot — logs in as YOU (required)
# Get these from https://my.telegram.org → "API development tools"
TG_USER_BOT_API_ID=
TG_USER_BOT_API_HASH=

# Telegram control bot (required)
# Create the bot via @BotFather, then ask @userinfobot for TG_OWNER_USER_ID
TG_CONTROL_BOT_TOKEN=
TG_OWNER_USER_ID=
# Optional: the bot's @handle (without the @), for display in /start. Not required.
TG_CONTROL_BOT_NAME=

# Signal (optional — leave SIGNAL_PHONE_NUMBER blank to run Telegram-only)
SIGNAL_API_URL=http://signal-api:8080
SIGNAL_PHONE_NUMBER=

# General
TIMEZONE=Europe/Berlin
LOG_LEVEL=INFO
```

And what it looks like once filled in (your real `environment/.env`):

```bash
TG_USER_BOT_API_ID=12345                              # plain digits, from my.telegram.org
TG_USER_BOT_API_HASH=0123456789abcdef0123456789abcdef # 32-char hex, from my.telegram.org
TG_CONTROL_BOT_TOKEN=8123456789:AAHxYzExampleBotToken # from @BotFather, contains a colon
TG_OWNER_USER_ID=123456789                            # plain digits, from @userinfobot
TG_CONTROL_BOT_NAME=my_autoresponder_bot              # optional, no leading @
SIGNAL_API_URL=http://signal-api:8080                 # leave as-is; internal docker DNS
SIGNAL_PHONE_NUMBER=+491701234567                     # E.164 format with +, or blank
TIMEZONE=Europe/Berlin                                # any valid IANA zone
LOG_LEVEL=INFO                                        # DEBUG | INFO | WARNING | ERROR
```

> **Important formatting rules:**
> - **No quotes around any value.** `TG_OWNER_USER_ID="123"` will fail validation; `TG_OWNER_USER_ID=123` is correct.
> - `TG_USER_BOT_API_ID` and `TG_OWNER_USER_ID` must be **plain digits only** (no `Id:` prefix, no spaces).
> - `SIGNAL_PHONE_NUMBER` must start with `+` and contain only digits afterwards (E.164). Leave it entirely blank to skip Signal.

The whole `environment/` folder is gitignored, so:

- A fresh `git clone` starts empty — no credentials in the repo.
- Backing up the host means backing up `environment/`.
- Moving to a new host means copying `environment/` over (or redoing the QR scan + Telegram login on the new host).

---

## Part 1 — Collect your Telegram credentials

This bot is the remote control you'll use on your phone. It only listens to *you*.

### Step 1.1: Get your Telegram API credentials

These let the autoresponder read your incoming messages.

1. On a computer, open https://my.telegram.org in a browser.
2. Log in with your Telegram phone number. Telegram sends you a login code *inside Telegram itself* (not as a real SMS).
3. Click **API development tools**.
4. Fill in the form:
   - **App title**: `autoresponder` (anything works)
   - **Short name**: `autoresponder`
   - **Platform**: Desktop
5. Click **Create application**.
6. You will see two values: **`api_id`** (a number) and **`api_hash`** (a long letters-and-numbers string). **Write them down somewhere safe.** You'll need them later.

### Step 1.2: Create the control bot

1. Open Telegram on your phone.
2. Search for the user **`@BotFather`** (it has a verified blue checkmark) and start a chat.
3. Send the command `/newbot`.
4. BotFather asks for a name — type something like `My Autoresponder`.
5. BotFather asks for a username — type something ending in `bot`, e.g. `my_autoresponder_bot`. It must be unique on Telegram, so add numbers if it's taken (`my_autoresponder_bot_2937`).
6. BotFather replies with a **token** — a long string with a colon in the middle, like `8123456789:AAH...xyz`. **Copy it. This is your bot token.**
7. Save the **bot username** too — you'll search for this on your phone later to find your remote control.

### Step 1.3: Find your own Telegram user ID

The control bot needs to know that *you* are its owner, so it ignores messages from anyone else. Your Telegram user ID is a number (around 9–10 digits), distinct from your `@handle`.

1. In Telegram, search for **`@userinfobot`** and start a chat.
2. Tap **Start** (or send `/start`).
3. It replies with several lines — look for the line **`Id: 123456789`**. Copy *only* the number (no `Id:` prefix, no quotes).

That number goes into `TG_OWNER_USER_ID` in `environment/.env`. It must be plain digits, e.g. `TG_OWNER_USER_ID=123456789` — not `"123456789"`, not `Id: 123456789`.

### Step 1.4 (optional): Note your Signal phone number

If you want auto-replies on Signal too, write down your Signal phone number in **international format** with the leading `+`, e.g. `+491701234567`. If you only want Telegram, you can skip Signal entirely.

---

## Part 2 — Install (one shot via `./install.sh`)

You'll do this **directly on the machine that will run the autoresponder** — typically your QNAP NAS via SSH. The installer is interactive (it asks you to type your Telegram login code into the terminal, and to scan a QR code with your phone for Signal), so you need a live terminal session to that machine.

### Step 2.1: Clone the repository on the host

SSH into the host, then:

```bash
cd /share/Container        # on QNAP. On a regular Linux box, pick your own path.
git clone <repo-url> autoresponder
cd autoresponder
```

### Step 2.2: Fill in `environment/.env`

You have two equivalent ways to do this. **Either**:

**(a) Let the installer create the file for you** — easier the first time:

```bash
./install.sh           # exits with "Edit environment/.env, then re-run"
$EDITOR environment/.env
```

The installer notices `environment/.env` is missing, copies `.env.example` to `environment/.env`, `chmod 600`s it, prints "Edit environment/.env with your credentials, then re-run ./install.sh", and exits. Fill it in and run `./install.sh` again.

**(b) Or create it manually** before the first install run:

```bash
mkdir -p environment
cp .env.example environment/.env
chmod 600 environment/.env
$EDITOR environment/.env
```

Either way, paste the values you collected in Part 1. See the [annotated env example above](#where-credentials-live) for the full list of variables and the formatting rules.

### Step 2.3: Run the installer

```bash
./install.sh
```

This script is idempotent — you can re-run it if something goes wrong. It:

1. Checks Docker and Docker Compose are installed and reachable.
2. Validates `environment/.env` (required vars are set, numeric fields are digits, Signal number is E.164).
3. Builds the autoresponder image.
4. **Telegram login** — prompts for your phone number, then asks for the login code that arrives *inside the Telegram app*. (Skipped if `environment/data/userbot.session` already exists.)
5. **Signal link** (if `SIGNAL_PHONE_NUMBER` is set) — renders a QR code directly in your terminal. Scan it from your phone: **Signal → Settings → Linked Devices → +**. (Skipped if your number is already linked.)
6. Starts both containers.

### Step 2.4: Tap **START** in your control bot

This is the most important step — without it, **the bot literally cannot message you** (Telegram forbids bots from messaging users who never started a chat first).

On your phone:

- In Telegram, tap the **search box** (top of the chat list).
- Type the **@username** of the bot you created in Step 1.2 (e.g. `@my_autoresponder_bot`). **Do not search for `@BotFather` — that's the bot factory, not your bot.**
- If you forgot the username: open `@BotFather` → send `/mybots` → tap your bot → tap **Open Bot**.
- In your bot's chat, tap the blue **START** button (or send `/start`).
- You should see a welcome message with an inline keyboard (On / Off / Schedule / Status / Message / Platforms).

If the welcome message doesn't appear, `TG_CONTROL_BOT_TOKEN` or `TG_OWNER_USER_ID` is wrong in `environment/.env`. Stop here and double-check both. The owner ID must be plain digits (no quotes, no `Id:` prefix).

### Step 2.5 (optional): Tighten the firewall

The Signal QR-link step needs port 8080 exposed on the host. Once Signal is linked, you can stop publishing that port:

- Edit `docker-compose.yml`, comment out the `8080:8080` line under `signal-api`.
- `make restart`.

The autoresponder still talks to `signal-api` over the internal Docker network, so this only closes off external access.

---

## Part 3 — Daily use (this is the easy part)

On your phone, open Telegram and find the **bot username** you created in Step 1.2 (e.g. `@my_autoresponder_bot`):

- Tap the search box at the top of the chat list and type the @username.
- Or, if you forgot the username: open **@BotFather** → send `/mybots` → tap your bot → tap **Open Bot**.
- **Do not confuse this with `@BotFather`.** BotFather is the *factory* that created your bot. Your bot is a *different* chat.

In your bot's chat, tap the blue **START** button at the bottom (or send `/start`). This is a one-time handshake that Telegram requires before any bot can message you. After that the bot can DM you (daily heartbeat, error alerts, etc.).

You'll see a menu with buttons:

| Button | What it does |
|---|---|
| 🟢 **On** | Start replying to incoming DMs immediately |
| 🔴 **Off** | Stop replying |
| ⏰ **Schedule** | Use a time window (e.g. evenings + weekends) |
| 📊 **Status** | Show what's currently happening |
| ✏️ **Message** | Change the auto-reply text |
| ⚙️ **Platforms** | Turn Telegram or Signal on/off individually |

You can also type slash commands directly:

```
/menu       Show the buttons
/on         Turn it ON now
/off        Turn it OFF
/schedule   Use the schedule
/status     Show current state
/message Hi, I'm in a meeting until 4pm
/setschedule 18:00 08:00
/help       Show this help
```

**Pin the bot chat in Telegram** so you can find it instantly when you need it.

### The daily check-in message

Once a day at midnight, the bot DMs you a "✅ Autoresponder running" message with the current status. **If you stop seeing this for more than a day, something is wrong** — call your tech helper.

---

## Troubleshooting

| Symptom | What to do |
|---|---|
| You stop seeing the daily "running" message | The autoresponder is probably down. SSH in and run `make ps` / `make logs`. Try `make restart`. If that doesn't fix it, call your tech helper. |
| The bot replies to commands but doesn't auto-reply to DMs | Check `/status`. Probably it's set to OFF, or the schedule says "not active right now". |
| You see an `⚠️` error message from the bot | Note what it says and call your tech helper. Most often it's "Signal listener disconnected" — usually self-recovers. |
| You changed your phone number | Both Telegram and Signal need to be re-linked from scratch. Delete `environment/data/userbot.session` and `environment/signal-data/`, then re-run `./install.sh`. Tech-helper job. |
| Signal stops auto-replying after a while | Signal sometimes drops linked devices for security reasons. Re-link by deleting `environment/signal-data/` and re-running `./install.sh`. |

### What you can't fix yourself

- The Telegram session getting invalidated (Telegram thinks the login is suspicious).
- Signal unlinking the QNAP-side device.
- The QNAP rebooting into a weird state.

For all of these: the fix is a 5–15 minute remote-support session with your tech helper. Plan for one of these once or twice a year.

---

## For developers / your tech helper

The end-user docs above cover the "happy path". The rest of this section is the maintainer's quick-start.

### Tech stack

Python 3.12 (asyncio, Telethon, python-telegram-bot v21, aiohttp), Docker + Compose, [`bbernhard/signal-cli-rest-api`](https://github.com/bbernhard/signal-cli-rest-api). Common dev tasks are in the `Makefile` (`make help`).

### Reference docs

- [`SPEC.md`](SPEC.md) — full architecture, component contracts, acceptance criteria.
- [`TESTING.md`](TESTING.md) — phased test plan (Telegram-only locally, then Signal, then soak, then NAS).
- [`DEPLOYMENT.md`](DEPLOYMENT.md) — detailed QNAP deployment notes (older — `./install.sh` is now the recommended path).
- [`HOW_TO_USE_WITH_CLAUDE_CODE.md`](HOW_TO_USE_WITH_CLAUDE_CODE.md) — original prompt-driven build flow.

### Local quick-start (Ubuntu laptop, Telegram only)

```bash
# 1. Prereqs (one-time)
sudo apt install docker.io docker-compose-plugin make
sudo usermod -aG docker $USER     # log out/in once after this

# 2. Configure
mkdir -p environment
cp .env.example environment/.env
$EDITOR environment/.env   # paste TG_USER_BOT_API_ID/HASH, TG_CONTROL_BOT_TOKEN,
                           # TG_OWNER_USER_ID. Leave SIGNAL_PHONE_NUMBER blank
                           # for Phase 1.

# 3. One-shot install (does build + tg-login [+ signal-link] + up)
./install.sh
```

Or step-by-step for finer-grained iteration:

```bash
make build
make tg-login         # writes environment/data/userbot.session
make up
make logs             # follow both containers
```

Expected log lines:

```
userbot started as @yourname (id=…)
control bot started
Signal disabled (SIGNAL_PHONE_NUMBER unset)
```

### Smoke test

1. On your phone, open Telegram, search for the bot username you created with `@BotFather`, send `/start` → expect the inline keyboard.
2. Tap **🟢 On**.
3. From a second Telegram account, DM your personal account → expect exactly one auto-reply.
4. Send 4 more DMs in quick succession → expect zero further replies (cooldown).
5. Tap **📊 Status** in the control bot → confirm the displayed timezone, current local time, and "active right now" all match reality.

If all five pass, walk through `TESTING.md` Phase 1 (T1–T14). For T3/T4 you'll want to lower `cooldown_hours` temporarily — easiest is to edit `environment/data/state.json` directly while the container is stopped.

### Add Signal (Phase 2)

```bash
$EDITOR environment/.env     # set SIGNAL_PHONE_NUMBER=+49…
make signal-link             # brings up signal-api alone
make signal-qr-tty           # renders the QR directly in your terminal
                             # → scan from Signal → Linked Devices → +
make signal-accounts         # should list your number
make restart                 # bounce the autoresponder so it picks up SIGNAL_PHONE_NUMBER
make logs                    # expect "Signal listener connected"
```

Then repeat the smoke test using a Signal DM instead of a Telegram one, and run TESTING.md Phase 2 (S1–S4).

### Useful make targets

| Command | What it does |
|---|---|
| `make help` | List all targets |
| `make build` | Build the autoresponder image |
| `make up` | Start both containers detached |
| `make down` | Stop and remove containers (volumes preserved) |
| `make restart` | Bounce both containers (after `.env` or code changes) |
| `make logs` | Follow logs from both containers |
| `make ps` | Container status |
| `make tg-login` | First-run interactive Telegram login |
| `make signal-link` | Bring up `signal-api` alone for QR linking |
| `make signal-qr` | Print the QR-link URL |
| `make signal-qr-tty` | Render the Signal QR code in the terminal |
| `make signal-accounts` | Show linked Signal accounts |
| `make shell` | Open a shell in the autoresponder container |
| `make clean` | Remove the built image (does not touch `environment/`) |

> All `make` targets and `./install.sh` pass `--env-file environment/.env` to `docker compose` automatically. If you invoke `docker compose` by hand, remember to include that flag — otherwise compose won't find your variables.

### Iteration loop

Code change in `app/` → `make build && make restart && make logs`. The mounted `environment/data/` volume preserves the session + `state.json` across rebuilds, so you don't have to re-login each time.

### Security notes

- `environment/data/userbot.session` and everything in `environment/signal-data/` are **credentials** — they grant full access to the linked accounts. The included `.gitignore` keeps `environment/` out of git entirely.
- `environment/.env` contains the bot token, the Telegram API hash, and your Signal phone number. The installer `chmod 600`'s it.
- Do not lower the cooldown below ~1 hour in production: Telegram's anti-spam systems can flag accounts that auto-reply rapidly to many people.
- Port 8080 is only published while you're linking Signal. Comment it out in `docker-compose.yml` (and `make restart`) afterwards.

---

## Acknowledgments

The implementation, install scripts, and documentation in this repository were generated by **Claude** (Anthropic) in an interactive session via [Claude Code](https://docs.claude.com/en/docs/claude-code), with all design decisions, testing, debugging, and final review done by [Marcel Reuter](mailto:mr@skynw.com). The intent is to keep this attribution visible so anyone reading or contributing knows the provenance of the code.
