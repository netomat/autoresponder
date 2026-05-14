# Telegram + Signal Autoresponder

A self-hosted "I'm away" auto-replier for your **personal** Telegram and Signal accounts. It runs on a QNAP NAS (or any Linux box with Docker) and you control it from a small Telegram bot on your phone — turn it on, off, change the message, schedule it for evenings & weekends.

> **You are not a developer? That's fine.** This guide walks you through it step by step. You will need ~45 minutes the first time, and a friend with some technical skill if you get stuck. After that you only ever use a Telegram bot — no terminal, no SSH, nothing scary.

---

## What it does

- Someone messages you on Telegram or Signal → they get an automatic reply ("I'm away, will reply later").
- You don't get spammed: the same person only gets one reply every few hours.
- Group chats are ignored — only direct messages trigger a reply.
- You can turn it on and off from your phone via a control bot (it's like a remote control).

## What you need

1. **A QNAP NAS** with the **Container Station** app installed. (Free in the QNAP App Center.)
2. **A computer (laptop or desktop)** to do the one-time setup. Mac, Windows, or Linux all work.
3. **Your phone** with both Telegram and Signal installed and working.
4. **About 45 minutes** the first time.
5. **Optionally a friend who knows Linux** for the parts that touch the NAS terminal — but the steps below are copy-pasteable.

---

## Part 1 — Create your own Telegram control bot

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

That number goes into `TG_OWNER_USER_ID` in `.env`. It must be plain digits, e.g. `TG_OWNER_USER_ID=123456789` — not `"123456789"`, not `Id: 123456789`.

### Step 1.4 (optional): Note your Signal phone number

If you want auto-replies on Signal too, write down your Signal phone number in **international format** with the leading `+`, e.g. `+491701234567`. If you only want Telegram, you can skip Signal entirely.

---

## Part 2 — Install on your QNAP NAS

There are two phases:
- **Phase A** is done once on your own computer (your laptop or desktop) so we can log into Telegram and Signal interactively. The QNAP cannot do this part itself because it needs a typed-in code from your phone.
- **Phase B** copies everything over to the NAS where it runs forever.

> **You will need help from a tech-savvy friend for Phase A and for the very first time on the NAS.** After that you don't need them again unless something breaks.

### Phase A — One-time login on your computer

Your helper will:

1. Install **Docker Desktop** (Mac/Windows) or **Docker Engine** (Linux) on your computer. Free.
   - On Ubuntu: `sudo apt install docker.io docker-compose-plugin make` then `sudo usermod -aG docker $USER` and log out/in once.
2. Copy this whole project folder (the one containing this README) somewhere on your computer.
3. In a Terminal/PowerShell, navigate into the folder.
4. Copy `.env.example` to `.env` and fill in the values you collected in Part 1:

   ```
   TG_USER_BOT_API_ID=12345
   TG_USER_BOT_API_HASH=abc123def456...
   TG_CONTROL_BOT_TOKEN=8123456789:AAH...xyz
   TG_OWNER_USER_ID=123456789
   SIGNAL_PHONE_NUMBER=+491701234567
   TIMEZONE=Europe/Berlin
   ```

   Leave `SIGNAL_PHONE_NUMBER` blank if you only want Telegram.

5. Run the Telegram login (this writes a session file that the autoresponder will use to read your DMs):

   ```bash
   make tg-login
   ```

   It asks for your phone number — type it in international format (`+49...`). Telegram sends a login code *inside the Telegram app* (not as SMS) — read it and type it in. If you have 2FA enabled, type your 2FA password too. Done.

6. **(Signal only)** Link the Signal device:

   ```bash
   make signal-link
   make signal-qr
   ```

   `make signal-qr` prints a URL. Open it in your browser — a QR code appears. On your phone: open Signal → Settings → Linked Devices → tap the **+** → scan the QR code. The QNAP-side Signal becomes a "linked device" of your phone, so it sees the same messages.

7. Verify Signal worked:

   ```bash
   make signal-accounts
   ```

   You should see your phone number listed.

8. **Start everything and open your control bot.** This is the most important step — without it, the bot literally cannot message you (Telegram forbids bots from messaging users who never started a chat first).

   ```bash
   make up
   make logs
   ```

   Logs should show `userbot started as @you (id=…)`, `control bot started`, and (if Signal is on) `Signal listener connected`. Press `Ctrl+C` to stop tailing.

   Then on your phone:

   - In Telegram, tap the **search box** (top of the chat list).
   - Type the **@username** of the bot you created in Step 1.2 (e.g. `@my_autoresponder_bot`). **Do not search for `@BotFather` — that's the bot factory, not your bot.**
   - If you can't remember the username: open `@BotFather` → send `/mybots` → tap your bot → tap **Open Bot**.
   - In your bot's chat, tap the blue **START** button (or send `/start`).
   - You should see a welcome message with an inline keyboard (On / Off / Schedule / Status / Message / Platforms).

   If the welcome message doesn't appear, `TG_CONTROL_BOT_TOKEN` or `TG_OWNER_USER_ID` is wrong in `.env`. Stop here and double-check both. The owner ID must be plain digits (no quotes, no `Id:` prefix).

### Phase B — Move it to the NAS

Two folders now exist that contain login credentials for your accounts: `data/` (Telegram) and `signal-data/` (Signal). **Treat these like passwords.** Don't email them, don't post them anywhere.

1. **Copy the folder to the NAS.** Easiest is over the local network, e.g.:

   ```bash
   scp -r autoresponder/ admin@yournas.local:/share/Container/
   ```

   (Replace `admin` and `yournas.local` with your QNAP login and address.)

2. **SSH into the NAS** and lock down permissions on the credential folders:

   ```bash
   ssh admin@yournas.local
   cd /share/Container/autoresponder
   chmod 600 data/userbot.session
   chmod -R 700 data signal-data
   ```

3. **Start it via Container Station:**
   - Open the QNAP web UI → **Container Station**.
   - Click **Applications** → **Create**.
   - Choose **Create Application** and paste the contents of `docker-compose.yml`.
   - Container Station detects the `${VAR}` placeholders and asks you to fill them — paste the same values you put in `.env`.
   - Click **Deploy**.

   *Or, from the SSH terminal:*

   ```bash
   docker compose up -d
   ```

4. **Verify it's running.** In Container Station you should see two containers:
   - `autoresponder` — green/running
   - `signal-api` — green/running

   Click each to see the logs. You should see lines like:
   - `userbot started as @yourname (id=…)`
   - `Signal listener connected`
   - `control bot started`

5. **Set them to auto-restart** (Container Station → container → Edit → Restart policy → "unless-stopped"). This way they survive a NAS reboot.

6. **Optional but recommended:** remove the public port mapping from `signal-api` once the QR scan is done. In Container Station, edit the `signal-api` container and remove the `8080:8080` line. The autoresponder still talks to it over the internal Docker network.

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
| You stop seeing the daily "running" message | The autoresponder is probably down. Open Container Station → restart both containers. If that doesn't fix it, call your tech helper. |
| The bot replies to commands but doesn't auto-reply to DMs | Check `/status`. Probably it's set to OFF, or the schedule says "not active right now". |
| You see an `⚠️` error message from the bot | Note what it says and call your tech helper. Most often it's "Signal listener disconnected" — usually self-recovers. |
| You changed your phone number | Both Telegram and Signal need to be re-linked from scratch. Tech-helper job — schedule a session. |
| You got a new phone | Same — full re-link. |
| Signal stops auto-replying after a while | Signal sometimes drops linked devices for security reasons. Re-link via the QR-code procedure in Phase A step 6. |

### What you can't fix yourself

- The Telegram session getting invalidated (Telegram thinks the login is suspicious).
- Signal unlinking the QNAP-side device.
- The QNAP rebooting into a weird state.

For all of these: the fix is a 5–15 minute remote-support session with your tech helper. Plan for one of these once or twice a year.

---

## For developers / your tech helper

The end-user docs above cover the "happy path" install + daily use. The rest of this section is the maintainer's quick-start: getting it running on a Linux laptop, smoke-testing it, and iterating before the NAS deploy.

### Tech stack

Python 3.12 (asyncio, Telethon, python-telegram-bot v21, aiohttp), Docker + Compose, [`bbernhard/signal-cli-rest-api`](https://github.com/bbernhard/signal-cli-rest-api). Common dev tasks are in the `Makefile` (`make help`).

### Reference docs

- [`SPEC.md`](SPEC.md) — full architecture, component contracts, acceptance criteria.
- [`TESTING.md`](TESTING.md) — phased test plan (Telegram-only locally, then Signal, then soak, then NAS).
- [`DEPLOYMENT.md`](DEPLOYMENT.md) — detailed QNAP deployment + handoff checklist for the non-technical user.
- [`HOW_TO_USE_WITH_CLAUDE_CODE.md`](HOW_TO_USE_WITH_CLAUDE_CODE.md) — original prompt-driven build flow.

### Local quick-start (Ubuntu laptop, Telegram only)

This is the path that maps to **`TESTING.md` Phase 1** — get the stack running locally before adding Signal or moving to the NAS.

```bash
# 1. Prereqs (one-time)
sudo apt install docker.io docker-compose-plugin make
sudo usermod -aG docker $USER     # log out/in once after this

# 2. Configure
cp .env.example .env
$EDITOR .env       # paste TG_USER_BOT_API_ID/HASH, TG_CONTROL_BOT_TOKEN, TG_OWNER_USER_ID
                   # leave SIGNAL_PHONE_NUMBER blank for Phase 1

# 3. First-run Telegram login (writes data/userbot.session)
make tg-login
#   → enter phone in +49… form
#   → enter the login code that arrives inside the Telegram app
#   → 2FA password if you have one

# 4. Build & start
make build
make up
make logs        # follow both containers
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

If all five pass, walk through `TESTING.md` Phase 1 (T1–T14). For T3/T4 you'll want to lower `cooldown_hours` temporarily — easiest is to edit `data/state.json` directly while the container is stopped, or add a `/setcooldown` command (out of scope for v1).

### Add Signal (Phase 2)

```bash
$EDITOR .env             # set SIGNAL_PHONE_NUMBER=+49…
make signal-link         # brings up signal-api alone
make signal-qr           # prints the QR-link URL
                         # → open in browser, scan from Signal → Linked Devices → +
make signal-accounts     # should list your number
make restart             # bounce the autoresponder so it picks up the new env
make logs                # expect "Signal listener connected"
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
| `make signal-accounts` | Show linked Signal accounts |
| `make shell` | Open a shell in the autoresponder container |
| `make clean` | Remove the built image (does not touch `data/`) |

### Iteration loop

Code change in `app/` → `make build && make restart && make logs`. The mounted `data/` volume preserves session + `state.json` across rebuilds, so you don't have to re-login each time.

### Security notes

- `data/userbot.session` and everything in `signal-data/` are **credentials** — they grant full access to the linked accounts. Never commit them, never email them, restrict file permissions to the owner only.
- `.env` contains the bot token and API hash — also a credential. The included `.gitignore` keeps both out of git.
- Do not lower the cooldown below ~1 hour in production: Telegram's anti-spam systems can flag accounts that auto-reply rapidly to many people.
