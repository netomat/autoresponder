.PHONY: help build up down restart logs ps tg-login signal-link signal-qr signal-accounts shell clean

help:
	@echo "Targets:"
	@echo "  build           Build the autoresponder image"
	@echo "  up              Start both containers in the background"
	@echo "  down            Stop and remove containers (volumes preserved)"
	@echo "  restart         Restart both containers"
	@echo "  logs            Tail logs from both containers"
	@echo "  ps              Show container status"
	@echo "  tg-login        First-run interactive Telegram login (writes data/userbot.session)"
	@echo "  signal-link     Bring up signal-api alone for QR linking"
	@echo "  signal-qr       Print the QR-link URL once signal-api is running"
	@echo "  signal-accounts Show linked Signal accounts (verify after QR scan)"
	@echo "  shell           Open a shell in the autoresponder container"
	@echo "  clean           Remove the built image (does NOT touch data/ or signal-data/)"

build:
	docker compose build

up:
	docker compose up -d

down:
	docker compose down

restart:
	docker compose restart

logs:
	docker compose logs -f --tail=200

ps:
	docker compose ps

# First-run Telegram login. Reads TG_API_ID / TG_API_HASH from .env.
# Prompts interactively for phone + login code. Writes /data/userbot.session.
tg-login:
	docker compose run --rm autoresponder python -m app.tg_login

signal-link:
	docker compose up -d signal-api

signal-qr:
	@echo "Open this URL in your browser to get a QR code, then scan with Signal → Settings → Linked Devices:"
	@echo "  http://localhost:8080/v1/qrcodelink?device_name=autoresponder"

signal-accounts:
	@curl -s http://localhost:8080/v1/accounts || echo "signal-api not reachable on :8080"

shell:
	docker compose run --rm autoresponder /bin/bash

clean:
	docker compose down --rmi local
