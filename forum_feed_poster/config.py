"""Environment-driven configuration."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import NewsSource

DEFAULT_NEWS_SOURCES = (
    NewsSource(
        name="Draft Sharks",
        url="https://www.draftsharks.com/rss/shark-bites",
    ),
    NewsSource(
        name="RotoWire",
        url="https://www.rotowire.com/rss/news.php?sport=NFL",
    ),
)


@dataclass(frozen=True)
class Settings:
    discord_webhook_url: str | None
    discord_bot_token: str | None
    news_sources: tuple[NewsSource, ...]
    discord_tag_ids: dict[str, str]
    discord_team_emoji_ids: dict[str, str]
    max_posts_per_run: int
    max_story_age_hours: int
    dedupe_window_hours: int
    dedupe_similarity: float
    dedupe_state_path: Path
    thread_merge_window_minutes: int
    player_data_path: Path
    player_data_max_age_hours: int
    request_timeout_seconds: int
    dry_run: bool
    force_repost: bool

    @classmethod
    def from_environment(cls) -> "Settings":
        dry_run = _as_bool(os.getenv("DRY_RUN", "true"))
        webhook_url = (os.getenv("DISCORD_WEBHOOK_URL") or "").strip() or None
        bot_token = (os.getenv("DISCORD_BOT_TOKEN") or "").strip() or None
        if not dry_run and not webhook_url:
            raise ValueError("DISCORD_WEBHOOK_URL is required when DRY_RUN is false")
        tag_ids = _parse_string_map(
            os.getenv("DISCORD_TAG_IDS_JSON"), "DISCORD_TAG_IDS_JSON"
        )
        if not dry_run and not tag_ids:
            raise ValueError("DISCORD_TAG_IDS_JSON is required when DRY_RUN is false")

        return cls(
            discord_webhook_url=webhook_url,
            discord_bot_token=bot_token,
            news_sources=_parse_sources(os.getenv("NEWS_FEEDS_JSON")),
            discord_tag_ids=tag_ids,
            discord_team_emoji_ids=_parse_string_map(
                os.getenv("DISCORD_TEAM_EMOJI_IDS_JSON"),
                "DISCORD_TEAM_EMOJI_IDS_JSON",
            ),
            max_posts_per_run=_bounded_int("MAX_POSTS_PER_RUN", 3, 1, 10),
            max_story_age_hours=_bounded_int("MAX_STORY_AGE_HOURS", 24, 1, 168),
            dedupe_window_hours=_bounded_int("DEDUPE_WINDOW_HOURS", 168, 1, 720),
            dedupe_similarity=_bounded_float("DEDUPE_SIMILARITY", 0.62, 0.4, 1.0),
            dedupe_state_path=Path(os.getenv("DEDUPE_STATE_PATH") or ".state/seen.json"),
            thread_merge_window_minutes=_bounded_int(
                "THREAD_MERGE_WINDOW_MINUTES", 60, 5, 360
            ),
            player_data_path=Path(
                os.getenv("PLAYER_DATA_PATH") or ".state/nfl_players.csv"
            ),
            player_data_max_age_hours=_bounded_int(
                "PLAYER_DATA_MAX_AGE_HOURS", 24, 1, 168
            ),
            request_timeout_seconds=_bounded_int(
                "REQUEST_TIMEOUT_SECONDS", 20, 5, 60
            ),
            dry_run=dry_run,
            force_repost=_as_bool(os.getenv("FORCE_REPOST", "false")),
        )


def _as_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw_value = os.getenv(name) or str(default)
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _bounded_float(name: str, default: float, minimum: float, maximum: float) -> float:
    raw_value = os.getenv(name) or str(default)
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _load_json(raw_value: str | None, name: str, default: Any) -> Any:
    if not raw_value:
        return default
    try:
        return json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{name} must contain valid JSON") from exc


def _parse_sources(raw_value: str | None) -> tuple[NewsSource, ...]:
    data = _load_json(raw_value, "NEWS_FEEDS_JSON", None)
    if data is None:
        return DEFAULT_NEWS_SOURCES
    if not isinstance(data, list) or not data:
        raise ValueError("NEWS_FEEDS_JSON must be a non-empty JSON list")

    sources: list[NewsSource] = []
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("Every NEWS_FEEDS_JSON entry must be an object")
        name = str(item.get("name") or "").strip()
        url = str(item.get("url") or "").strip()
        if not name or not url.startswith(("https://", "http://")):
            raise ValueError("Every news feed needs a name and an HTTP(S) URL")
        sources.append(NewsSource(name=name, url=url))
    return tuple(sources)


def _parse_string_map(raw_value: str | None, name: str) -> dict[str, str]:
    data = _load_json(raw_value, name, {})
    if not isinstance(data, dict):
        raise ValueError(f"{name} must be a JSON object")
    return {
        str(key).strip(): str(value).strip()
        for key, value in data.items()
        if str(key).strip() and str(value).strip()
    }
