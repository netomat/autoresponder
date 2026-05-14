#!/usr/bin/env bash
# install.sh — one-shot installer for the Telegram + Signal autoresponder.
#
# Run this on the Docker host (typically your QNAP, via SSH) after editing .env.
# Idempotent: re-running it skips steps that are already done.
#
# Usage: ./install.sh

set -euo pipefail

# ── output helpers ───────────────────────────────────────────────────────────
if [[ -t 1 ]]; then
  RED=$'\033[0;31m'; GRN=$'\033[0;32m'; YEL=$'\033[0;33m'
  BLU=$'\033[0;34m'; BOLD=$'\033[1m'; NC=$'\033[0m'
else
  RED=''; GRN=''; YEL=''; BLU=''; BOLD=''; NC=''
fi
info()  { printf "%s→%s %s\n" "$BLU" "$NC" "$*"; }
ok()    { printf "%s✓%s %s\n" "$GRN" "$NC" "$*"; }
warn()  { printf "%s!%s %s\n" "$YEL" "$NC" "$*"; }
fail()  { printf "%s✗%s %s\n" "$RED" "$NC" "$*" >&2; exit 1; }
step()  { printf "\n%s%s── %s ──%s\n" "$BOLD" "$BLU" "$*" "$NC"; }

# ── 1. Prereqs ──────────────────────────────────────────────────────────────
step "Checking prerequisites"
command -v docker >/dev/null 2>&1 || fail "docker not installed (install Container Station on QNAP, or docker.io on Linux)"
docker compose version >/dev/null 2>&1 || fail "docker compose plugin missing — install docker-compose-plugin or upgrade Docker"
docker info >/dev/null 2>&1 || fail "docker daemon not reachable (is the service running, and are you in the docker group?)"
ok "docker $(docker --version | awk '{print $3}' | tr -d ,)"
ok "compose $(docker compose version --short)"

# ── 2. .env ─────────────────────────────────────────────────────────────────
step "Checking .env"
if [[ ! -f .env ]]; then
  if [[ -f .env.example ]]; then
    cp .env.example .env
    warn ".env created from .env.example"
    fail "Edit .env with your credentials (see README Part 1), then re-run ./install.sh"
  else
    fail ".env not found and no .env.example to start from — are you in the project root?"
  fi
fi

# Validate required vars without printing values
required=(TG_USER_BOT_API_ID TG_USER_BOT_API_HASH TG_CONTROL_BOT_TOKEN TG_OWNER_USER_ID)
missing=()
# shellcheck disable=SC1091
set -a; . ./.env; set +a
for v in "${required[@]}"; do
  if [[ -z "${!v:-}" ]]; then missing+=("$v"); fi
done
if [[ ${#missing[@]} -gt 0 ]]; then
  fail "Missing required vars in .env: ${missing[*]}"
fi

# Sanity-check numeric fields
[[ "${TG_USER_BOT_API_ID}" =~ ^[0-9]+$ ]] || fail "TG_USER_BOT_API_ID must be plain digits (no quotes, no spaces)"
[[ "${TG_OWNER_USER_ID}" =~ ^[0-9]+$ ]] || fail "TG_OWNER_USER_ID must be plain digits (no quotes, no 'Id:' prefix)"
ok ".env looks complete"

SIGNAL_ENABLED=0
if [[ -n "${SIGNAL_PHONE_NUMBER:-}" ]]; then
  [[ "${SIGNAL_PHONE_NUMBER}" =~ ^\+[0-9]+$ ]] || fail "SIGNAL_PHONE_NUMBER must be in E.164 format (e.g. +491701234567)"
  SIGNAL_ENABLED=1
  info "Signal: enabled"
else
  info "Signal: disabled (SIGNAL_PHONE_NUMBER blank — Telegram-only install)"
fi

# ── 3. Build ────────────────────────────────────────────────────────────────
step "Building autoresponder image"
docker compose build
ok "image built"

# ── 4. Telegram login (interactive) ─────────────────────────────────────────
step "Telegram userbot login"
if [[ -f data/userbot.session ]]; then
  warn "data/userbot.session already exists — skipping login"
  warn "  (delete it and re-run if you want to log in as a different account)"
else
  info "You'll be prompted for your phone (in +49... format) then a login code"
  info "Telegram will send the code as a message inside your Telegram app (chat: \"Telegram\")"
  echo
  docker compose run --rm autoresponder python -m app.tg_login
  [[ -f data/userbot.session ]] || fail "Telegram login did not produce data/userbot.session"
  ok "Telegram userbot logged in"
fi

# ── 5. Signal link (interactive QR) ─────────────────────────────────────────
if [[ $SIGNAL_ENABLED -eq 1 ]]; then
  step "Signal link"
  info "Starting signal-api container..."
  docker compose up -d signal-api

  info "Waiting for signal-api to be ready..."
  for _ in $(seq 1 30); do
    if docker compose exec -T signal-api wget -q -O- http://localhost:8080/v1/about >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done

  # Check whether already linked
  accounts="$(docker compose exec -T signal-api wget -q -O- http://localhost:8080/v1/accounts 2>/dev/null || echo '[]')"
  if echo "$accounts" | grep -q "\"${SIGNAL_PHONE_NUMBER}\""; then
    ok "Signal already linked for ${SIGNAL_PHONE_NUMBER}"
  else
    echo
    info "Scan this QR with the Signal app:"
    info "  Phone → Signal → Settings → Linked Devices → + → scan"
    echo
    docker run --rm --network=container:signal-api alpine:latest sh -c '
      apk add --no-cache --quiet curl libqrencode-tools zbar imagemagick imagemagick-libpng >/dev/null
      curl -sf "http://localhost:8080/v1/qrcodelink?device_name=autoresponder" -o /tmp/q.png
      zbarimg --raw -q /tmp/q.png | tr -d "\n" | qrencode -t UTF8
    '
    echo
    read -r -p "Press Enter after you have scanned the QR and Signal shows the linked device... " _
    sleep 2

    accounts="$(docker compose exec -T signal-api wget -q -O- http://localhost:8080/v1/accounts 2>/dev/null || echo '[]')"
    if echo "$accounts" | grep -q "\"${SIGNAL_PHONE_NUMBER}\""; then
      ok "Signal linked for ${SIGNAL_PHONE_NUMBER}"
    else
      warn "Could not confirm Signal link. Continuing anyway — verify later with:"
      warn "  docker compose exec signal-api wget -q -O- http://localhost:8080/v1/accounts"
    fi
  fi
fi

# ── 6. Start everything ─────────────────────────────────────────────────────
step "Starting all containers"
docker compose up -d
sleep 2
docker compose ps

# ── 7. Done ─────────────────────────────────────────────────────────────────
echo
ok "Installation complete."
cat <<EOF

${BOLD}Next steps:${NC}
  1. In Telegram, find your control bot${TG_CONTROL_BOT_NAME:+ (@${TG_CONTROL_BOT_NAME})} and send /start
     - If you forgot the username: open @BotFather, send /mybots, tap your bot, tap "Open Bot"
  2. Set your auto-reply text via the ✏️ Message button (or /message <text>)
  3. Set the schedule via the ⏰ Schedule button (or /setschedule HH:MM HH:MM)
  4. Toggle on via the 🟢 On button (or /on)

${BOLD}Useful commands:${NC}
  Watch logs:           docker compose logs -f
  Stop:                 docker compose down
  Restart:              docker compose restart
  Status:               docker compose ps
  Recreate after .env:  docker compose up -d --force-recreate

EOF
