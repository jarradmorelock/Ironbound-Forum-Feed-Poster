"""Durable editorial handoff for accepted Discord player-news stories."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .dedupe import canonicalize_url
from .models import NewsStory
from .presentation import StoryPresentation


LEDGER_SCHEMA_VERSION = 2


def _player_refs(event: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    refs: list[tuple[str, str, dict[str, Any]]] = []
    primary = event.get("player")
    if isinstance(primary, dict) and primary.get("nflverse_id"):
        refs.append((str(primary["nflverse_id"]), "primary", primary))
    for related in event.get("related_players") or []:
        if isinstance(related, dict) and related.get("nflverse_id"):
            refs.append((str(related["nflverse_id"]), "related", related))
    return refs


def build_player_index(events: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Build a compact lookup for every primary and related player in a batch."""
    players: dict[str, dict[str, Any]] = {}
    for event in events:
        event_id = str(event.get("event_id") or "")
        if not event_id:
            continue
        for player_id, role, player in _player_refs(event):
            row = players.setdefault(
                player_id,
                {
                    "nflverse_id": player_id,
                    "name": player.get("name"),
                    "nfl_team": player.get("nfl_team"),
                    "event_ids": [],
                    "primary_event_ids": [],
                    "related_event_ids": [],
                },
            )
            if event_id not in row["event_ids"]:
                row["event_ids"].append(event_id)
            target = "primary_event_ids" if role == "primary" else "related_event_ids"
            if event_id not in row[target]:
                row[target].append(event_id)
    for row in players.values():
        for key in ("event_ids", "primary_event_ids", "related_event_ids"):
            row[key] = sorted(row[key])
    return {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "players": {key: players[key] for key in sorted(players)},
    }


def _events_digest(events: Iterable[dict[str, Any]]) -> str:
    material = "".join(
        json.dumps(event, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        + "\n"
        for event in events
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def build_weekly_manifest(
    events: Iterable[dict[str, Any]],
    *,
    week_key: str,
    window_start: str,
    window_end: str,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    rows = list(events)
    return {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "ledger_type": "weekly_news_inbox",
        "week_key": str(week_key),
        "window_start": str(window_start),
        "window_end": str(window_end),
        "generated_at": (generated_at or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(),
        "event_count": len(rows),
        "player_count": len(build_player_index(rows).get("players") or {}),
        "events_sha256": _events_digest(rows),
    }


def receipt_matches(manifest: dict[str, Any], receipt: dict[str, Any]) -> bool:
    """Return true only for a receipt acknowledging this exact inbox revision."""
    manifest_count = manifest.get("event_count")
    receipt_count = receipt.get("event_count")
    return (
        str(receipt.get("week_key") or "") == str(manifest.get("week_key") or "")
        and str(receipt.get("events_sha256") or "") == str(manifest.get("events_sha256") or "")
        and receipt_count is not None
        and manifest_count is not None
        and int(receipt_count) == int(manifest_count)
    )


def build_news_event(
    story: NewsStory,
    presentation: StoryPresentation,
    tag_names: Iterable[str],
    *,
    action: str,
    thread_id: str | None,
    accepted_at: datetime | None = None,
) -> dict[str, Any]:
    """Create the compact fact packet consumed later by Editorial Desk.

    The event deliberately stores only feed-provided title/summary evidence and
    normalized metadata. It never archives the full source article.
    """
    accepted = (accepted_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    canonical_url = canonicalize_url(story.url)
    event_id = _event_id(story, canonical_url)

    player = presentation.player
    team = presentation.team
    return {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "event_id": event_id,
        "accepted_at": accepted.isoformat(),
        "published_at": story.published_at.astimezone(timezone.utc).isoformat(),
        "source": {
            "name": story.source,
            "url": story.url,
            "canonical_url": canonical_url,
            "categories": list(story.categories),
        },
        "evidence": {
            "original_title": story.title,
            "feed_summary": story.summary,
        },
        "editorial": {
            "headline": presentation.headline,
            "thread_title": presentation.thread_title,
            "tags": list(tag_names),
        },
        "player": (
            {
                "nflverse_id": player.key,
                "name": player.display_name,
                "nfl_team": player.team,
            }
            if player
            else None
        ),
        "related_players": [
            {
                "nflverse_id": related.key,
                "name": related.display_name,
                "nfl_team": related.team,
            }
            for related in presentation.related_players
        ],
        "nfl_team": (
            {
                "abbreviation": team.abbreviation,
                "name": team.name,
            }
            if team
            else None
        ),
        "discord": {
            "action": action,
            "thread_id": str(thread_id) if thread_id else None,
        },
    }


def write_news_batch(path: Path, events: Iterable[dict[str, Any]]) -> Path | None:
    rows = list(events)
    path = Path(path)
    if not rows:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return None

    path.parent.mkdir(parents=True, exist_ok=True)
    value = {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "events": rows,
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return path


def _event_id(story: NewsStory, canonical_url: str) -> str:
    material = "|".join(
        (
            story.source.strip().casefold(),
            canonical_url,
            story.published_at.astimezone(timezone.utc).isoformat(),
        )
    )
    return "news:" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]
