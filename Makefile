.PHONY: help build up down restart logs ps tg-login signal-link signal-qr signal-qr-tty signal-accounts shell clean

# All credentials live under environment/. docker compose needs --env-file
# pointed there so ${VAR} substitutions in docker-compose.yml resolve.
COMPOSE := docker compose --env-file environment/.env

help:
	@echo "Targets:"
	@echo "  build           Build the autoresponder image"
	@echo "  up              Start both containers in the background"
	@echo "  down            Stop and remove containers (volumes preserved)"
	@echo "  restart         Restart both containers"
	@echo "  logs            Tail logs from both containers"
	@echo "  ps              Show container status"
	@echo "  tg-login        First-run interactive Telegram login (writes environment/data/userbot.session)"
	@echo "  signal-link     Bring up signal-api alone for QR linking"
	@echo "  signal-qr       Print the QR-link URL once signal-api is running"
	@echo "  signal-qr-tty   Render the Signal QR code as ASCII directly in the terminal"
	@echo "  signal-accounts Show linked Signal accounts (verify after QR scan)"
	@echo "  shell           Open a shell in the autoresponder container"
	@echo "  clean           Remove the built image (does NOT touch environment/)"

build:
	$(COMPOSE) build

up:
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

restart:
	$(COMPOSE) restart

logs:
	$(COMPOSE) logs -f --tail=200

ps:
	$(COMPOSE) ps

# First-run Telegram login. Reads TG_USER_BOT_API_ID / TG_USER_BOT_API_HASH from environment/.env.
# Prompts interactively for phone + login code. Writes /data/userbot.session
# (which is environment/data/userbot.session on the host).
tg-login:
	$(COMPOSE) run --rm autoresponder python -m app.tg_login

signal-link:
	$(COMPOSE) up -d signal-api

signal-qr:
	@echo "Open this URL in your browser to get a QR code, then scan with Signal → Settings → Linked Devices:"
	@echo "  http://localhost:8080/v1/qrcodelink?device_name=autoresponder"

# Renders the Signal-link QR directly in the terminal — no host tools required.
# Uses a throwaway Alpine container that shares signal-api's network namespace,
# so curl can reach the API at localhost:8080 regardless of compose network naming.
# Pipeline: fetch PNG → decode with zbarimg (needs imagemagick + png delegate) →
# re-encode as block-character QR with qrencode (cleaner than rendering the PNG).
# Scan with Signal app → Settings → Linked Devices → +
signal-qr-tty:
	@docker run --rm --network=container:signal-api alpine:latest sh -c '\
	  apk add --no-cache --quiet curl libqrencode-tools zbar imagemagick imagemagick-libpng >/dev/null && \
	  curl -sf "http://localhost:8080/v1/qrcodelink?device_name=autoresponder" -o /tmp/q.png && \
	  zbarimg --raw -q /tmp/q.png | tr -d "\n" | qrencode -t UTF8' \
	  || echo "Failed. Is signal-api running? Try: make up"

signal-accounts:
	@curl -s http://localhost:8080/v1/accounts || echo "signal-api not reachable on :8080"

shell:
	$(COMPOSE) run --rm autoresponder /bin/bash

clean:
	$(COMPOSE) down --rmi local
