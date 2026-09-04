"""Print the configured Discord Forum's tag IDs and NFL team emoji IDs."""

from __future__ import annotations

import json
import os

import requests


TEAM_EMOJI_NAMES = {
    "ARI": "cardinals",
    "ATL": "falcons",
    "BAL": "ravens",
    "BUF": "bills",
    "CAR": "panthers",
    "CHI": "bears",
    "CIN": "bengals",
    "CLE": "browns",
    "DAL": "cowboys",
    "DEN": "broncos",
    "DET": "lions",
    "GB": "packers",
    "HOU": "texans",
    "IND": "colts",
    "JAX": "jaguars",
    "KC": "chiefs",
    "LV": "raiders",
    "LAC": "chargers",
    "LAR": "rams",
    "MIA": "dolphins",
    "MIN": "vikings",
    "NE": "patriots",
    "NO": "saints",
    "NYG": "giants",
    "NYJ": "jets",
    "PHI": "eagles",
    "PIT": "steelers",
    "SEA": "seahawks",
    "SF": "49rs",
    "TB": "buccaneers",
    "TEN": "titans",
    "WAS": "commanders",
}


def main() -> int:
    bot_token = os.getenv("DISCORD_BOT_TOKEN")
    channel_id = os.getenv("DISCORD_FORUM_CHANNEL_ID")
    if not bot_token or not channel_id:
        print("DISCORD_BOT_TOKEN and DISCORD_FORUM_CHANNEL_ID are required.")
        return 1

    try:
        headers = {"Authorization": f"Bot {bot_token.strip()}"}
        response = requests.get(
            f"https://discord.com/api/v10/channels/{channel_id.strip()}",
            headers=headers,
            timeout=20,
        )
        response.raise_for_status()
        channel = response.json()
        tags = channel.get("available_tags", [])
        guild_id = channel.get("guild_id")
        if not guild_id:
            raise ValueError("The configured channel is not a server Forum channel")

        emoji_response = requests.get(
            f"https://discord.com/api/v10/guilds/{guild_id}/emojis",
            headers=headers,
            timeout=20,
        )
        emoji_response.raise_for_status()

        tag_ids = {tag["name"]: tag["id"] for tag in tags}
        team_emoji_ids = _team_emoji_ids(emoji_response.json())

        print("DISCORD_TAG_IDS_JSON")
        print(json.dumps(tag_ids, indent=2))
        print("\nDISCORD_TEAM_EMOJI_IDS_JSON")
        print(json.dumps(team_emoji_ids, indent=2))

        missing = sorted(set(TEAM_EMOJI_NAMES) - set(team_emoji_ids))
        if missing:
            print(f"\nWarning: no server emoji was found for: {', '.join(missing)}")
        return 0
    except (KeyError, ValueError, requests.RequestException) as exc:
        print(f"Could not read Forum tags: {exc}")
        return 1


def _team_emoji_ids(emojis: list[dict[str, object]]) -> dict[str, str]:
    ids_by_name = {
        str(emoji.get("name", "")).lower(): str(emoji["id"])
        for emoji in emojis
        if emoji.get("name") and emoji.get("id") and emoji.get("available", True)
    }
    return {
        abbreviation: ids_by_name[emoji_name]
        for abbreviation, emoji_name in TEAM_EMOJI_NAMES.items()
        if emoji_name in ids_by_name
    }


if __name__ == "__main__":
    raise SystemExit(main())
