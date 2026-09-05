"""Collect player news and create image-backed Discord Forum posts."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Sequence

import requests

from .classify import TAG_CLASSIFIER_VERSION, classify_story, tag_ids_for_names
from .config import Settings
from .dedupe import ActiveThread, DedupeStore, canonicalize_url
from .discord import (
    DiscordRequestError,
    ImageAttachment,
    build_payload,
    build_update_payload,
    download_image,
    generate_story_card,
    rename_forum_thread,
    send_forum_post,
    send_thread_update,
    team_emoji_cdn_url,
    team_emoji_markup,
)
from .models import NewsStory
from .presentation import (
    PlayerDirectory,
    StoryPresentation,
    load_player_directory,
    present_story,
)
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
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=settings.max_story_age_hours)
        try:
            players = load_player_directory(
                session,
                settings.player_data_path,
                settings.request_timeout_seconds,
                settings.player_data_max_age_hours,
                now,
            )
            print(f"Loaded {len(players.profiles)} current NFL player profiles.")
        except (OSError, ValueError, requests.RequestException) as exc:
            print(f"Warning: player directory unavailable; using article metadata: {exc}")
            players = PlayerDirectory.empty()
        posted = 0

        for story in collect_stories(settings, session):
            if posted >= settings.max_posts_per_run:
                break
            if story.published_at < cutoff:
                continue
            presentation = present_story(story, players)
            active_thread = (
                store.find_active_thread(
                    presentation.player_key,
                    settings.thread_merge_window_minutes,
                    now,
                )
                if presentation.player_key
                else None
            )
            if not settings.force_repost and store.is_exact_duplicate(story):
                print(f"Skipped duplicate: {story.title}")
                continue
            if (
                not settings.force_repost
                and active_thread is not None
                and store.is_duplicate_follow_up(story, active_thread)
            ):
                print(f"Skipped likely duplicate follow-up: {story.title}")
                continue
            if not settings.force_repost and active_thread is None and store.is_duplicate(story):
                print(f"Skipped likely duplicate: {story.title}")
                continue

            attachment, image_url, image_kind = _story_attachment(
                story, presentation, settings, session
            )

            story = replace(story, image_url=image_url)
            current_tags = classify_story(story)
            previous_tags = active_thread.tag_names if active_thread else ()
            if (
                active_thread
                and active_thread.classifier_version < TAG_CLASSIFIER_VERSION
            ):
                previous_tags = [
                    tag for tag in previous_tags if tag != "Fantasy Analysis"
                ]
            tag_names = _merge_tags(
                current_tags,
                previous_tags,
            )
            tag_ids = tag_ids_for_names(tag_names, settings.discord_tag_ids)
            emoji = team_emoji_markup(
                presentation.team, settings.discord_team_emoji_ids
            )
            action = "update" if active_thread else "create"
            payload = (
                build_update_payload(story, attachment, presentation, emoji)
                if active_thread
                else build_payload(story, tag_ids, attachment, presentation, emoji)
            )

            if settings.dry_run:
                print(
                    json.dumps(
                        {
                            "dry_run": True,
                            "action": action,
                            "player": (
                                presentation.player.display_name
                                if presentation.player
                                else None
                            ),
                            "team": (
                                presentation.team.abbreviation
                                if presentation.team
                                else None
                            ),
                            "thread_id": active_thread.thread_id if active_thread else None,
                            "editorial_headline": presentation.thread_title,
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
                if active_thread:
                    try:
                        send_thread_update(
                            settings.discord_webhook_url,
                            active_thread.thread_id,
                            payload,
                            attachment,
                            session,
                            settings.request_timeout_seconds,
                        )
                    except DiscordRequestError as exc:
                        if exc.status_code != 404:
                            raise
                        print(
                            "The saved Forum thread no longer exists; "
                            "creating a replacement post."
                        )
                        store.remove_thread(active_thread.thread_id)
                        active_thread = None
                        action = "create"
                        payload = build_payload(
                            story, tag_ids, attachment, presentation, emoji
                        )

                if active_thread is None:
                    message = send_forum_post(
                        settings.discord_webhook_url,
                        payload,
                        attachment,
                        session,
                        settings.request_timeout_seconds,
                    )
                    if presentation.player_key and presentation.player:
                        active_thread = ActiveThread(
                            player_key=presentation.player_key,
                            player_name=presentation.player.display_name,
                            thread_id=message.channel_id,
                            headline=presentation.thread_title,
                            opened_at=now.isoformat(),
                            updated_at=now.isoformat(),
                            tag_names=tag_names,
                            source_urls=[canonicalize_url(story.url)],
                            classifier_version=TAG_CLASSIFIER_VERSION,
                        )
                        store.remember_thread(active_thread)
                    print(
                        f"Created Forum post: {presentation.thread_title} "
                        f"[{', '.join(tag_names)}]"
                    )
                else:
                    active_thread.headline = presentation.thread_title
                    active_thread.updated_at = now.isoformat()
                    active_thread.tag_names = tag_names
                    active_thread.source_urls.append(canonicalize_url(story.url))
                    active_thread.classifier_version = TAG_CLASSIFIER_VERSION
                    store.remember_thread(active_thread)
                    print(
                        f"Added follow-up to {active_thread.player_name}: "
                        f"{presentation.headline}"
                    )
                    if settings.discord_bot_token:
                        try:
                            rename_forum_thread(
                                settings.discord_bot_token,
                                active_thread.thread_id,
                                presentation.thread_title,
                                tag_ids,
                                session,
                                settings.request_timeout_seconds,
                            )
                            print("Updated the Forum headline and tags.")
                        except (ValueError, requests.RequestException) as exc:
                            print(
                                "Warning: follow-up was posted, but the Forum headline "
                                f"could not be updated: {exc}"
                            )
                    else:
                        print(
                            "Note: DISCORD_BOT_TOKEN is not configured, so the follow-up "
                            "was added without renaming the Forum headline."
                        )

            if settings.dry_run and active_thread is None and presentation.player:
                store.remember_thread(
                    ActiveThread(
                        player_key=presentation.player.key,
                        player_name=presentation.player.display_name,
                        thread_id=f"dry-run-{presentation.player.key}",
                        headline=presentation.thread_title,
                        opened_at=now.isoformat(),
                        updated_at=now.isoformat(),
                        tag_names=tag_names,
                        source_urls=[canonicalize_url(story.url)],
                        classifier_version=TAG_CLASSIFIER_VERSION,
                    )
                )

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


def _story_attachment(
    story: NewsStory,
    presentation: StoryPresentation,
    settings: Settings,
    session: requests.Session,
) -> tuple[ImageAttachment, str | None, str]:
    player_image: ImageAttachment | None = None
    if presentation.player and presentation.player.headshot_url:
        try:
            player_image = download_image(
                presentation.player.headshot_url,
                presentation.player.display_name,
                session,
                settings.request_timeout_seconds,
            )
        except (ValueError, requests.RequestException) as exc:
            print(f"Warning: player headshot unavailable: {exc}")

    team_logo: ImageAttachment | None = None
    logo_url = team_emoji_cdn_url(
        presentation.team, settings.discord_team_emoji_ids
    )
    if logo_url:
        try:
            team_logo = download_image(
                logo_url,
                presentation.team.name if presentation.team else "NFL team",
                session,
                settings.request_timeout_seconds,
            )
        except (ValueError, requests.RequestException) as exc:
            print(f"Warning: team logo unavailable for image card: {exc}")

    if player_image:
        return (
            generate_story_card(
                story,
                presentation.headline,
                player_image=player_image,
                team_logo=team_logo,
            ),
            presentation.player.headshot_url if presentation.player else None,
            "player headshot card",
        )

    image_url = story.image_url
    if not image_url:
        try:
            image_url = find_article_image(
                story, session, settings.request_timeout_seconds
            )
        except requests.RequestException as exc:
            print(f"Warning: article image lookup failed for {story.title}: {exc}")

    if image_url and not _looks_generic_image(image_url):
        try:
            return (
                download_image(
                    image_url,
                    presentation.headline,
                    session,
                    settings.request_timeout_seconds,
                ),
                image_url,
                "source image",
            )
        except (ValueError, requests.RequestException) as exc:
            print(f"Using headline card because the source image failed: {exc}")

    return (
        generate_story_card(
            story,
            presentation.headline,
            team_logo=team_logo,
        ),
        image_url,
        "generated headline card",
    )


def _looks_generic_image(image_url: str) -> bool:
    lowered = image_url.lower()
    return any(
        term in lowered
        for term in (
            "banner",
            "placeholder",
            "default-image",
            "site-logo",
            "yourunfairadvantage",
        )
    )


def _merge_tags(primary: Sequence[str], previous: Sequence[str]) -> list[str]:
    merged: list[str] = []
    for tag in (*primary, *previous):
        if tag not in merged:
            merged.append(tag)
    if len(merged) > 1 and "General News" in merged:
        merged.remove("General News")
    return merged[:5]
