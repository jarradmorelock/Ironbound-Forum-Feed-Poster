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


LEDGER_SCHEMA_VERSION = 1


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
