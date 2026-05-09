# Deployment to QNAP & Handoff to Non-Technical User

## On your friend's QNAP

### Prerequisites

- QNAP with **Container Station** installed (free from App Center).
- SSH access enabled on the QNAP (Control Panel → Network & File Services → Telnet/SSH).
- A folder on the NAS for the project, e.g. `/share/Container/autoresponder/`.

### Step 1: Friend creates his own credentials

He must do this himself — these are tied to his accounts, not yours.

1. **Telegram API credentials**: He visits https://my.telegram.org from his phone or computer, logs in with his Telegram phone number, goes to "API development tools", creates an application. He gives you the `api_id` and `api_hash`.
2. **Control bot**: Walk him through creating one with `@BotFather` on Telegram. Save the token.
3. **His Telegram user ID**: He messages `@userinfobot` and tells you the number.
4. **His Signal phone number** in E.164 format.

### Step 2: First-run logins (do this on YOUR laptop, with him present)

You need his phone for the SMS code (Telegram) and the QR scan (Signal). Easiest is a screen-share or in-person session.

**Telegram session:**

```bash
# In the project folder on your laptop
docker compose run --rm autoresponder python -c "
from telethon import TelegramClient
import os
c = TelegramClient('/data/userbot', int(os.environ['TG_API_ID']), os.environ['TG_API_HASH'])
c.start()
"
```

He types his phone number, receives the Telegram login code (in his Telegram app, not via SMS), reads it to you. Done.

**Signal linking:**

```bash
docker compose up signal-api -d
# Open http://localhost:8080/v1/qrcodelink?device_name=autoresponder
```

He scans with his phone via Signal → Settings → Linked Devices → "+". Confirm with `curl http://localhost:8080/v1/accounts`.

Now you have working `data/userbot.session` and `signal-data/` with linked Signal device.

### Step 3: Copy to QNAP

SCP the entire project folder (including `data/` and `signal-data/`) to the QNAP:

```bash
scp -r autoresponder/ admin@qnap.local:/share/Container/
```

Lock down permissions on the NAS:

```bash
ssh admin@qnap.local
cd /share/Container/autoresponder
chmod 600 data/userbot.session
chmod -R 700 data signal-data
```

The session and signal data files are equivalent to having his accounts. Treat them like passwords.

### Step 4: Deploy via Container Station

Container Station (recent versions) supports docker-compose directly:

1. Open Container Station → Applications → Create.
2. Choose "Create Application" → paste the contents of `docker-compose.yml`.
3. Set environment variables in Container Station's UI (it'll detect the `${VAR}` substitutions).
4. Deploy.

Alternative: SSH in and run `docker compose up -d` directly from the project folder.

### Step 5: Verify

- Check Container Station → Containers → both `autoresponder` and `signal-api` should be running.
- Check logs in Container Station UI. Look for: "Userbot started", "Signal listener connected", "Control bot started".
- DM the control bot from his Telegram → it should respond. Try `/status`.
- DM his personal Telegram from your account → he should get an auto-reply (after you tell him to `/on`).

### Step 6: Lock down

- In Container Station, set the `autoresponder` container to "Auto-restart" — confirms it survives QNAP reboots.
- Remove the `8080:8080` port mapping from `signal-api` in compose (linking is done; the API is reachable from the autoresponder container via the internal Docker network and doesn't need to be on the host network anymore). Restart.
- Optionally, set up QNAP notifications for container failures.

## Handoff to your friend

A non-technical user needs these things from you:

### 1. A short cheat-sheet (paper or note app)

```
TO USE THE AUTORESPONDER, OPEN @YourControlBotName ON TELEGRAM:

  /menu       Show all options as buttons
  /on         Turn it ON now
  /off        Turn it OFF
  /schedule   Use the schedule (evenings + weekends)
  /status     What's happening right now?
  /message    Change the auto-reply text

WHAT TO DO IF...

  ...you stop getting the daily "running" message → call <your name>
  ...you get an "error" message from the bot → call <your name>
  ...you switched phones → call <your name>, both accounts need re-linking
  ...you want to delete the auto-reply temporarily → just send /off
```

### 2. A pinned chat

Tell him to **pin** the control bot chat in his Telegram so he can find it instantly. Tell him: *"This bot will message you once a day to confirm it's working. If a day passes without a message, tell me."*

### 3. Realistic expectations

Tell him plainly:

- Auto-replies aren't invisible. People will see "Read" status when his linked devices process messages. There's no way around that.
- Signal occasionally drops linked devices for security reasons. If that happens, you'll need to re-link via QR — that means a 5-minute remote support session, not something he can do alone.
- If he gets a new phone, both Telegram and Signal need re-linking. Plan for that.
- Telegram has anti-spam systems. If he sets the cooldown very low and starts mass-replying, his account could be flagged. The defaults in this project are conservative; don't lower them.

### 4. Recovery contacts

Make sure he knows:
- The Telegram username of the control bot (so he can find it again if he loses the chat).
- Your contact info as the maintainer.
- That the QNAP folder is `/share/Container/autoresponder/` if he ever needs to point another helper at it.

## Updating later

When you push improvements:

```bash
ssh admin@qnap.local
cd /share/Container/autoresponder
git pull   # or scp updated files
docker compose build
docker compose up -d
```

State, sessions, and Signal links survive container rebuilds because they're in mounted volumes. Don't `docker compose down -v` — the `-v` would wipe the volumes.

## What you can't easily fix remotely

Be honest about these:

- **Signal device unlinked** — needs a new QR scan from his phone. Either screen-share him through opening port 8080 temporarily, or he reads you a QR code.
- **Telegram session invalidated** — needs his phone for the SMS code again. Same screen-share situation.
- **He changes his Signal or Telegram phone number** — full re-link of both, treat as fresh deployment.
- **QNAP reboot puts containers in a weird state** — usually a `docker compose down && docker compose up -d` fixes it; he'll need to use Container Station UI to do this himself, or call you.

For these, having a "remote support afternoon" booked once or twice a year is realistic.
