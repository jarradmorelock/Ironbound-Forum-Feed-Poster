"""Collect player news and create image-backed Discord Forum posts."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import requests

from .classify import classify_story, tag_ids_for_names
from .config import Settings
from .dedupe import DedupeStore
from .discord import build_payload, download_image, generate_story_card, send_forum_post
from .models import NewsStory
from .sources import fetch_source, find_article_image


def collect_stories(settings: Settings, session: requests.Session) -> list[NewsStory]:
    stories: list[NewsStory] = []
    successful_sources = 0
    for source in settings.news_sources:
        try:
            source_stories = fetch_source(source, session, settings.request_timeout_seconds)
            stories.extend(source_stories)
            successful_sources += 1
            print(f"Fetched {len(source_stories)} stories from {source.name}.")
        except (ValueError, requests.RequestException) as exc:
            print(f"Warning: {source.name} could not be fetched: {exc}")

    if not successful_sources:
        raise ValueError("Every configured news source failed")
    return sorted(stories, key=lambda story: story.published_at, reverse=True)


def main() -> int:
    try:
        settings = Settings.from_environment()
        session = requests.Session()
        store = DedupeStore(
            path=settings.dedupe_state_path,
            window_hours=settings.dedupe_window_hours,
            similarity=settings.dedupe_similarity,
        )
        cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.max_story_age_hours)
        posted = 0

        for story in collect_stories(settings, session):
            if posted >= settings.max_posts_per_run:
                break
            if story.published_at < cutoff:
                continue
            if store.is_duplicate(story):
                print(f"Skipped duplicate: {story.title}")
                continue

            image_url = story.image_url
            if not image_url:
                try:
                    image_url = find_article_image(
                        story, session, settings.request_timeout_seconds
                    )
                except requests.RequestException as exc:
                    print(f"Warning: article image lookup failed for {story.title}: {exc}")

            if not image_url:
                attachment = generate_story_card(story)
                image_kind = "generated headline card"
            else:
                try:
                    attachment = download_image(
                        image_url,
                        story.title,
                        session,
                        settings.request_timeout_seconds,
                    )
                    image_kind = "source image"
                except (ValueError, requests.RequestException) as exc:
                    print(f"Using headline card because the source image failed: {exc}")
                    attachment = generate_story_card(story)
                    image_kind = "generated headline card"

            story = replace(story, image_url=image_url)
            tag_names = classify_story(story)
            tag_ids = tag_ids_for_names(tag_names, settings.discord_tag_ids)
            payload = build_payload(story, tag_ids, attachment)

            if settings.dry_run:
                print(
                    json.dumps(
                        {
                            "dry_run": True,
                            "source": story.source,
                            "suggested_tags": tag_names,
                            "image_url": image_url,
                            "image_kind": image_kind,
                            "image_bytes": len(attachment.data),
                            "discord_payload": payload,
                        },
                        indent=2,
                    )
                )
            else:
                assert settings.discord_webhook_url is not None
                send_forum_post(
                    settings.discord_webhook_url,
                    payload,
                    attachment,
                    session,
                    settings.request_timeout_seconds,
                )
                print(f"Posted: {story.title} [{', '.join(tag_names)}]")

            store.remember(story)
            if not settings.dry_run:
                store.save()
            posted += 1

        if posted == 0:
            print("No new stories were eligible for posting.")
        elif settings.dry_run:
            print(f"Dry run completed with {posted} candidate post(s); state was not saved.")
        return 0
    except (ValueError, OSError, requests.RequestException) as exc:
        print(f"News poster failed: {exc}")
        return 1
