"""First-run helper that creates /data/userbot.session interactively.

Run via `make tg-login`. It reads TG_USER_BOT_API_ID / TG_USER_BOT_API_HASH
from the env, prompts for the owner's phone number and the Telegram login
code, and writes the session file the userbot uses at runtime."""

from __future__ import annotations

import os
import sys

from telethon import TelegramClient

from .userbot import SESSION_PATH


def main() -> None:
    api_id = os.environ.get("TG_USER_BOT_API_ID")
    api_hash = os.environ.get("TG_USER_BOT_API_HASH")
    if not api_id or not api_hash:
        print(
            "FATAL: TG_USER_BOT_API_ID and TG_USER_BOT_API_HASH must be set in .env",
            file=sys.stderr,
        )
        sys.exit(1)

    client = TelegramClient(SESSION_PATH, int(api_id), api_hash)
    client.start()
    me = client.loop.run_until_complete(client.get_me())
    print(f"Session created for @{me.username} (id={me.id}) at {SESSION_PATH}.session")
    client.disconnect()


if __name__ == "__main__":
    main()
