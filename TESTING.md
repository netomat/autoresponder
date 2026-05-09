# Testing Plan

Test on **your own** Telegram and Signal accounts before deploying to your friend. You'll need a second device or a second account to send test messages.

## Phase 1: Telegram only, on your Ubuntu laptop

Goal: validate the Telegram userbot + control bot end-to-end without Signal in the mix.

### Setup

1. Get your `api_id`/`api_hash` from https://my.telegram.org → "API development tools".
2. Create a control bot via `@BotFather` on Telegram → `/newbot`. Save the token.
3. Get your own user ID from `@userinfobot`.
4. Create `.env` from `.env.example` with the four Telegram values. Leave Signal vars blank for now.
5. Comment out the `signal-api` service and the Signal-related env vars in `docker-compose.yml` temporarily, OR add a feature flag to skip Signal startup if `SIGNAL_PHONE_NUMBER` is unset.

### First-run login (interactive)

Telethon needs your phone number + SMS code on first run. Easiest way:

```bash
docker compose run --rm autoresponder python -c "
from telethon import TelegramClient
import os
c = TelegramClient('/data/userbot', int(os.environ['TG_API_ID']), os.environ['TG_API_HASH'])
c.start()
print('Session created')
"
```

Type your phone number in E.164 format (`+49...`). Receive the SMS code in Telegram itself (not as a real SMS — Telegram sends it as a message). Type the code. Done. `data/userbot.session` now exists.

### Tests

Run with `docker compose up` and watch logs.

| # | Test | Expected |
|---|---|---|
| T1 | DM yourself from a second account while `enabled: false` | No reply |
| T2 | `/on` in control bot, then DM | One reply |
| T3 | Send 5 DMs in 30 seconds | Exactly one reply (cooldown) |
| T4 | Wait > cooldown_hours (lower it to 0.01 for testing!), send another DM | New reply |
| T5 | DM in a group containing your account | No reply |
| T6 | DM yourself from another bot | No reply |
| T7 | `/off`, then DM | No reply |
| T8 | `/setschedule` for the next 2 minutes, `/schedule` to enable, DM inside window | Reply |
| T9 | Same, DM outside window | No reply |
| T10 | Schedule 23:00–02:00 (midnight crossing), test inside (e.g. 23:30 or 01:30) and outside | Inside replies, outside doesn't |
| T11 | Restart container (`docker compose restart`) | Last state preserved, listener reconnects |
| T12 | Have a non-owner DM the control bot | Bot ignores entirely |
| T13 | Tap each inline-keyboard button | Each works as documented |
| T14 | `/message Hi I'm in a meeting` then trigger reply | Reply uses new text |

## Phase 2: Add Signal locally

### Setup

1. Uncomment `signal-api` in compose.
2. Fill in `SIGNAL_PHONE_NUMBER` in `.env`.
3. `docker compose up signal-api -d` (just the Signal container for now).
4. Visit `http://localhost:8080/v1/qrcodelink?device_name=autoresponder-test` in your browser. A QR code appears.
5. On your phone: Signal → Settings → Linked Devices → "+" → scan the QR.
6. Verify: `curl http://localhost:8080/v1/accounts` should list your phone number.
7. Manual send test:
   ```bash
   curl -X POST http://localhost:8080/v2/send \
     -H "Content-Type: application/json" \
     -d '{"message":"manual test","number":"+49YOURNUMBER","recipients":["+49TARGETNUMBER"]}'
   ```
   Confirm the message arrives.

### Tests

Now `docker compose up` the full stack. Repeat the relevant Telegram tests (T1, T2, T3, T5, T7, T8) with **Signal DMs** instead. Plus:

| # | Test | Expected |
|---|---|---|
| S1 | `docker compose restart signal-api` while listener is running | Listener reconnects within 30s, log shows "Signal listener connected" again |
| S2 | `/platforms signal off`, send Signal DM | No reply, but Telegram still works |
| S3 | Send Signal message that's a typing indicator (just open chat without typing) | No reply, no error in logs |
| S4 | Receive Signal in a group | No reply |

## Phase 3: Soak test

Run on your own machine for a full week. At minimum:

- Leave it running for 7 days continuously.
- Trigger the schedule transition every day (it should activate/deactivate at the right times).
- Verify the daily heartbeat DM arrives 7 times.
- Check `state.json` doesn't grow unboundedly (the cooldown prune should keep `recently_replied` bounded).
- Force a network blip on the host and confirm both Telegram and Signal reconnect.
- Check logs for any unexpected errors.

## Phase 4: Move to your QNAP

Same project, deployed via Container Station. See `DEPLOYMENT.md`.

Run on your *own* QNAP for another week before involving your friend. NAS environments behave differently from a laptop — different filesystem, different networking, different reboot behavior.

## Edge cases worth testing explicitly

- **Telegram session invalidated** (Telegram thinks you're spamming): Userbot will fail to start. Confirm error notification reaches you via control bot.
- **Bad SIGNAL_PHONE_NUMBER**: Signal listener should fail clearly at startup, not loop silently.
- **Corrupt `state.json`**: Delete a `}` and restart. Should fail clearly, not crash without explanation.
- **Clock skew on QNAP**: Schedule logic depends on system time. If the NAS clock is wrong, schedules trigger at the wrong time. Maybe add a startup log line showing "Current time in TIMEZONE: …" so it's obvious.
