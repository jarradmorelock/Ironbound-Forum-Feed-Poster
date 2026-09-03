"""Fetch a league feed and publish a digest to a Discord Forum webhook."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping
from urllib.parse import quote

import requests

DISCORD_CONTENT_LIMIT = 2_000
DISCORD_THREAD_NAME_LIMIT = 100


@dataclass(frozen=True)
class Settings:
    league_id: str
    league_feed_url: str
    discord_webhook_url: str | None
    feed_api_token: str | None
    forum_post_title: str
    max_feed_items: int
    dry_run: bool

    @classmethod
    def from_environment(cls) -> "Settings":
        league_id = _required_environment_value("LEAGUE_ID")
        league_feed_url = _required_environment_value("LEAGUE_FEED_URL")
        dry_run = _as_bool(os.getenv("DRY_RUN", "false"))
        webhook_url = os.getenv("DISCORD_WEBHOOK_URL") or None

        if not dry_run and not webhook_url:
            raise ValueError("DISCORD_WEBHOOK_URL is required when DRY_RUN is false")

        raw_max_items = os.getenv("MAX_FEED_ITEMS") or "10"
        try:
            max_items = int(raw_max_items)
        except ValueError as exc:
            raise ValueError("MAX_FEED_ITEMS must be an integer") from exc
        if not 1 <= max_items <= 50:
            raise ValueError("MAX_FEED_ITEMS must be between 1 and 50")

        default_title = f"League Feed — {datetime.now(timezone.utc):%Y-%m-%d}"

        return cls(
            league_id=league_id,
            league_feed_url=league_feed_url,
            discord_webhook_url=webhook_url,
            feed_api_token=os.getenv("FEED_API_TOKEN") or None,
            forum_post_title=os.getenv("FORUM_POST_TITLE") or default_title,
            max_feed_items=max_items,
            dry_run=dry_run,
        )


def _required_environment_value(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _as_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def fetch_feed(settings: Settings) -> Any:
    """Fetch the configured JSON feed."""
    encoded_league_id = quote(settings.league_id, safe="")
    url = settings.league_feed_url.replace("{league_id}", encoded_league_id)
    headers = {"Accept": "application/json", "User-Agent": "ironbound-forum-feed-poster/0.1"}
    if settings.feed_api_token:
        headers["Authorization"] = f"Bearer {settings.feed_api_token}"

    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    return response.json()


def extract_items(feed_data: Any) -> list[Any]:
    """Return feed items from the supported top-level JSON shapes."""
    if isinstance(feed_data, list):
        return feed_data

    if isinstance(feed_data, Mapping):
        for key in ("items", "events", "feed"):
            items = feed_data.get(key)
            if isinstance(items, list):
                return items

    raise ValueError("Feed JSON must be a list or contain an items, events, or feed list")


def _first_text(item: Mapping[str, Any], keys: Iterable[str]) -> str:
    for key in keys:
        value = item.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def format_item(item: Any) -> str:
    """Format one provider-neutral feed item as Discord Markdown."""
    if not isinstance(item, Mapping):
        return f"- {str(item).strip()}"

    title = _first_text(item, ("title", "name", "type", "event"))
    summary = _first_text(item, ("summary", "description", "message", "details"))
    url = _first_text(item, ("url", "link"))
    timestamp = _first_text(item, ("timestamp", "created_at", "date"))

    primary = f"**{title}**" if title else summary or "Feed update"
    parts = [f"- {primary}"]
    if title and summary:
        parts.append(f" — {summary}")
    if url:
        parts.append(f" ([details]({url}))")
    if timestamp:
        parts.append(f"\n  -# {timestamp}")
    return "".join(parts)


def format_forum_post(
    league_id: str,
    title: str,
    items: list[Any],
    max_items: int,
) -> str:
    """Build content that fits Discord's webhook message limit."""
    updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"## {title}",
        f"League: `{league_id}` • Updated: {updated_at}",
        "",
        *(format_item(item) for item in items[:max_items]),
    ]
    content = "\n".join(lines)

    if len(content) <= DISCORD_CONTENT_LIMIT:
        return content

    suffix = "\n\n_Additional feed content was trimmed to fit Discord._"
    return content[: DISCORD_CONTENT_LIMIT - len(suffix)].rstrip() + suffix


def build_discord_payload(settings: Settings, content: str) -> dict[str, Any]:
    return {
        "thread_name": settings.forum_post_title[:DISCORD_THREAD_NAME_LIMIT],
        "content": content,
        "allowed_mentions": {"parse": []},
    }


def send_to_discord(webhook_url: str, payload: Mapping[str, Any]) -> None:
    """Create a Discord Forum thread through the existing webhook."""
    response = requests.post(webhook_url, params={"wait": "true"}, json=payload, timeout=30)
    response.raise_for_status()


def main() -> int:
    try:
        settings = Settings.from_environment()
        items = extract_items(fetch_feed(settings))
        if not items:
            print("The feed returned no items; no Forum post was created.")
            return 0

        content = format_forum_post(
            league_id=settings.league_id,
            title=settings.forum_post_title,
            items=items,
            max_items=settings.max_feed_items,
        )
        payload = build_discord_payload(settings, content)

        if settings.dry_run:
            print(json.dumps(payload, indent=2))
            return 0

        assert settings.discord_webhook_url is not None
        send_to_discord(settings.discord_webhook_url, payload)
        print("Discord Forum post created successfully.")
        return 0
    except (ValueError, requests.RequestException) as exc:
        print(f"Feed poster failed: {exc}")
        return 1
