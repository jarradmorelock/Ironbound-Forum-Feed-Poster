"""Print the configured Discord Forum's available tag IDs."""

from __future__ import annotations

import json
import os

import requests


def main() -> int:
    bot_token = os.getenv("DISCORD_BOT_TOKEN")
    channel_id = os.getenv("DISCORD_FORUM_CHANNEL_ID")
    if not bot_token or not channel_id:
        print("DISCORD_BOT_TOKEN and DISCORD_FORUM_CHANNEL_ID are required.")
        return 1

    try:
        response = requests.get(
            f"https://discord.com/api/v10/channels/{channel_id}",
            headers={"Authorization": f"Bot {bot_token}"},
            timeout=20,
        )
        response.raise_for_status()
        tags = response.json().get("available_tags", [])
        print(json.dumps({tag["name"]: tag["id"] for tag in tags}, indent=2))
        return 0
    except (KeyError, ValueError, requests.RequestException) as exc:
        print(f"Could not read Forum tags: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
