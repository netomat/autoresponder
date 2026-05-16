#!/usr/bin/env bash
# install.sh — one-shot installer for the Telegram + Signal autoresponder.
#
# Run this on the Docker host (typically your QNAP, via SSH) after editing
# environment/.env. Idempotent: re-running it skips steps that are already done.
#
# All credentials and persistent state live under ./environment/ — that
# directory is gitignored, so a fresh `git clone` starts empty and this
# installer walks the user through populating it.
#
# Usage:
#   ./install.sh            # skip build if the image is already present
#   ./install.sh --rebuild  # force a rebuild (use after pulling code changes)

set -euo pipefail

FORCE_REBUILD=0
case "${1:-}" in
  --rebuild|-r) FORCE_REBUILD=1 ;;
  "") ;;
  *) echo "Usage: $0 [--rebuild]" >&2; exit 2 ;;
esac

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

# All credentials live under environment/. docker compose needs --env-file
# pointed there so ${VAR} substitutions in docker-compose.yml resolve.
COMPOSE=(docker compose --env-file environment/.env)

# ── 1. Prereqs ──────────────────────────────────────────────────────────────
step "Checking prerequisites"
command -v docker >/dev/null 2>&1 || fail "docker not installed (install Container Station on QNAP, or docker.io on Linux)"
docker compose version >/dev/null 2>&1 || fail "docker compose plugin missing — install docker-compose-plugin or upgrade Docker"
docker info >/dev/null 2>&1 || fail "docker daemon not reachable (is the service running, and are you in the docker group?)"
ok "docker $(docker --version | awk '{print $3}' | tr -d ,)"
ok "compose $(docker compose version --short)"

# ── 2. environment/.env ─────────────────────────────────────────────────────
step "Checking environment/.env"
mkdir -p environment environment/data environment/signal-data
if [[ ! -f environment/.env ]]; then
  if [[ -f .env.example ]]; then
    cp .env.example environment/.env
    chmod 600 environment/.env
    warn "environment/.env created from .env.example"
    fail "Edit environment/.env with your credentials (see README Part 1), then re-run ./install.sh"
  else
    fail ".env.example not found at project root — are you in the project root?"
  fi
fi

# Load .env into shell scope so we can validate per the userbot flag
# shellcheck disable=SC1091
set -a; . ./environment/.env; set +a

# Userbot toggle: defaults to enabled for backward compat. Set
# TG_USERBOT_ENABLED=false in .env to run Telegram replies via Chat
# Automation only (no Telethon login, no API_ID/HASH needed).
USERBOT_ENABLED=1
case "${TG_USERBOT_ENABLED:-true}" in
  0|false|False|FALSE|no|No|NO|off|Off|OFF) USERBOT_ENABLED=0 ;;
esac

# Validate required vars without printing values
required=(TG_CONTROL_BOT_TOKEN TG_OWNER_USER_ID)
if [[ $USERBOT_ENABLED -eq 1 ]]; then
  required+=(TG_USER_BOT_API_ID TG_USER_BOT_API_HASH)
fi
missing=()
for v in "${required[@]}"; do
  if [[ -z "${!v:-}" ]]; then missing+=("$v"); fi
done
if [[ ${#missing[@]} -gt 0 ]]; then
  fail "Missing required vars in environment/.env: ${missing[*]}"
fi

# Sanity-check numeric fields
if [[ $USERBOT_ENABLED -eq 1 ]]; then
  [[ "${TG_USER_BOT_API_ID}" =~ ^[0-9]+$ ]] || fail "TG_USER_BOT_API_ID must be plain digits (no quotes, no spaces)"
fi
[[ "${TG_OWNER_USER_ID}" =~ ^[0-9]+$ ]] || fail "TG_OWNER_USER_ID must be plain digits (no quotes, no 'Id:' prefix)"
ok "environment/.env looks complete"
if [[ $USERBOT_ENABLED -eq 0 ]]; then
  info "Telegram userbot: disabled (Chat Automation only)"
else
  info "Telegram userbot: enabled"
fi

# Protect the file from accidental world-readability
chmod 600 environment/.env 2>/dev/null || true

# ── 2b. Host UID/GID for signal-cli-rest-api ────────────────────────────────
# signal-cli-rest-api inside the container drops privileges to SIGNAL_CLI_UID
# and writes to /home/.local/share/signal-cli, which is bind-mounted from
# environment/signal-data. On native Linux Docker where your user is UID 1000
# the default works. On Synology/QNAP NAS your user is typically UID 1026+,
# so the in-container UID must match or signal-api can't write its config and
# fails its healthcheck.
#
# Fill blanks in .env from `id -u` / `id -g` so the in-container user matches
# the host. Pre-existing non-empty values are left alone (user override).
host_uid="$(id -u)"
host_gid="$(id -g)"
for kv in "SIGNAL_CLI_UID=${host_uid}" "SIGNAL_CLI_GID=${host_gid}"; do
  key="${kv%%=*}"
  if grep -qE "^${key}=.+$" environment/.env; then
    :  # already set to non-empty value — respect user override
  elif grep -q "^${key}=" environment/.env; then
    sed -i.bak "s|^${key}=.*|${kv}|" environment/.env
  else
    echo "${kv}" >> environment/.env
  fi
done
rm -f environment/.env.bak
# Re-source so the rest of this script sees the updated values
set -a; . ./environment/.env; set +a
ok "signal-cli will run as UID:GID ${SIGNAL_CLI_UID}:${SIGNAL_CLI_GID}"

# Make sure the bind-mount dirs are owned by that UID/GID. If a previous
# (broken) run let the container chown them to 1000, fix that here — or
# print a sudo command if we can't.
fix_owner() {
  local dir="$1"
  [[ -d "$dir" ]] || return 0
  local cur_uid
  cur_uid="$(stat -c %u "$dir")"
  if [[ "$cur_uid" != "${SIGNAL_CLI_UID}" ]]; then
    if chown -R "${SIGNAL_CLI_UID}:${SIGNAL_CLI_GID}" "$dir" 2>/dev/null; then
      ok "fixed ownership of $dir (was UID $cur_uid)"
    else
      warn "$dir is owned by UID $cur_uid, expected ${SIGNAL_CLI_UID}."
      warn "Run this once, then re-run ./install.sh:"
      warn "  sudo chown -R ${SIGNAL_CLI_UID}:${SIGNAL_CLI_GID} $dir"
      exit 1
    fi
  fi
}
fix_owner environment/data
fix_owner environment/signal-data

SIGNAL_ENABLED=0
if [[ -n "${SIGNAL_PHONE_NUMBER:-}" ]]; then
  [[ "${SIGNAL_PHONE_NUMBER}" =~ ^\+[0-9]+$ ]] || fail "SIGNAL_PHONE_NUMBER must be in E.164 format (e.g. +491701234567)"
  SIGNAL_ENABLED=1
  info "Signal: enabled"
else
  info "Signal: disabled (SIGNAL_PHONE_NUMBER blank — Telegram-only install)"
fi

# ── 3. Build ────────────────────────────────────────────────────────────────
# Compose builds are incremental but the context-transfer step is slow on
# NAS Docker. Skip the build if the image already exists; pass --rebuild
# after pulling code changes (Dockerfile, requirements.txt, app/...).
step "Building autoresponder image"
auto_img="$("${COMPOSE[@]}" config --images 2>/dev/null | grep -E 'autoresponder' | head -1 || true)"
if [[ $FORCE_REBUILD -eq 1 ]]; then
  info "rebuilding (--rebuild)"
  "${COMPOSE[@]}" build
  ok "image rebuilt"
elif [[ -n "$auto_img" ]] && docker image inspect "$auto_img" >/dev/null 2>&1; then
  ok "$auto_img already built — skipping (use ./install.sh --rebuild to force)"
else
  info "image missing — building"
  "${COMPOSE[@]}" build
  ok "image built"
fi

# ── 4. Telegram login (interactive) ─────────────────────────────────────────
step "Telegram userbot login"
if [[ $USERBOT_ENABLED -eq 0 ]]; then
  info "TG_USERBOT_ENABLED=false — skipping userbot login (Chat Automation only)"
elif [[ -f environment/data/userbot.session ]]; then
  warn "environment/data/userbot.session already exists — skipping login"
  warn "  (delete it and re-run if you want to log in as a different account)"
else
  info "You'll be prompted for your phone (in +49... format) then a login code"
  info "Telegram will send the code as a message inside your Telegram app (chat: \"Telegram\")"
  echo
  "${COMPOSE[@]}" run --rm autoresponder python -m app.tg_login
  [[ -f environment/data/userbot.session ]] || fail "Telegram login did not produce environment/data/userbot.session"
  ok "Telegram userbot logged in"
fi

# ── 5. Signal link (interactive QR) ─────────────────────────────────────────
if [[ $SIGNAL_ENABLED -eq 1 ]]; then
  step "Signal link"
  info "Starting signal-api container..."
  "${COMPOSE[@]}" up -d signal-api

  info "Waiting for signal-api to be ready..."
  for _ in $(seq 1 30); do
    if "${COMPOSE[@]}" exec -T signal-api wget -q -O- http://localhost:8080/v1/about >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done

  # Check whether already linked
  accounts="$("${COMPOSE[@]}" exec -T signal-api wget -q -O- http://localhost:8080/v1/accounts 2>/dev/null || echo '[]')"
  if echo "$accounts" | grep -q "\"${SIGNAL_PHONE_NUMBER}\""; then
    ok "Signal already linked for ${SIGNAL_PHONE_NUMBER}"
  else
    echo
    info "Scan this QR with the Signal app:"
    info "  Phone → Signal → Settings → Linked Devices → + → scan"
    echo
    docker run --rm --network=container:signal-api alpine:latest sh -c '
      set -e
      apk add --no-cache --quiet curl libqrencode-tools zbar >/dev/null
      curl -sf "http://localhost:8080/v1/qrcodelink?device_name=autoresponder" -o /tmp/q.png
      zbarimg --raw -q /tmp/q.png | tr -d "\n" | qrencode -t UTF8
    '
    echo
    read -r -p "Press Enter after you have scanned the QR and Signal shows the linked device... " _
    sleep 2

    accounts="$("${COMPOSE[@]}" exec -T signal-api wget -q -O- http://localhost:8080/v1/accounts 2>/dev/null || echo '[]')"
    if echo "$accounts" | grep -q "\"${SIGNAL_PHONE_NUMBER}\""; then
      ok "Signal linked for ${SIGNAL_PHONE_NUMBER}"
    else
      warn "Could not confirm Signal link. Continuing anyway — verify later with:"
      warn "  ${COMPOSE[*]} exec signal-api wget -q -O- http://localhost:8080/v1/accounts"
    fi
  fi
fi

# ── 6. Start everything ─────────────────────────────────────────────────────
step "Starting all containers"
"${COMPOSE[@]}" up -d
sleep 2
"${COMPOSE[@]}" ps

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
  Watch logs:           make logs
  Stop:                 make down
  Restart:              make restart
  Status:               make ps
  Recreate after edit:  ${COMPOSE[*]} up -d --force-recreate

EOF
