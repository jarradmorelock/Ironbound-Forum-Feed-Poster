"""Fetch and normalize public RSS/Atom player-news feeds."""

from __future__ import annotations

import calendar
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import urljoin

import feedparser
import requests
from bs4 import BeautifulSoup

from .models import NewsSource, NewsStory

USER_AGENT = "Ironbound-Forum-Feed-Poster/0.2 (+private Discord news feed)"


def fetch_source(
    source: NewsSource,
    session: requests.Session,
    timeout: int,
) -> list[NewsStory]:
    response = session.get(
        source.url,
        headers={
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml",
            "User-Agent": USER_AGENT,
        },
        timeout=timeout,
    )
    response.raise_for_status()
    return parse_feed(source, response.content)


def parse_feed(source: NewsSource, content: bytes | str) -> list[NewsStory]:
    parsed = feedparser.parse(content)
    if getattr(parsed, "bozo", False) and not parsed.entries:
        raise ValueError(f"{source.name} returned invalid RSS/Atom data")

    stories: list[NewsStory] = []
    for entry in parsed.entries:
        title = _html_text(entry.get("title", ""))
        url = str(entry.get("link") or entry.get("id") or "").strip()
        if not title or not url:
            continue

        raw_summary = entry.get("summary") or entry.get("description") or ""
        categories = tuple(
            str(tag.get("term") or "").strip()
            for tag in entry.get("tags", [])
            if str(tag.get("term") or "").strip()
        )
        stories.append(
            NewsStory(
                source=source.name,
                title=title,
                summary=_html_text(raw_summary),
                url=url,
                published_at=_published_at(entry),
                image_url=_entry_image_url(entry, url),
                categories=categories,
            )
        )
    return stories


def find_article_image(
    story: NewsStory,
    session: requests.Session,
    timeout: int,
) -> str | None:
    """Use Open Graph/Twitter metadata when the feed omits an image."""
    response = session.get(
        story.url,
        headers={"Accept": "text/html", "User-Agent": USER_AGENT},
        timeout=timeout,
    )
    response.raise_for_status()
    if "html" not in response.headers.get("Content-Type", "").lower():
        return None

    soup = BeautifulSoup(response.text, "html.parser")
    selectors = (
        ('meta[property="og:image:secure_url"]', "content"),
        ('meta[property="og:image"]', "content"),
        ('meta[name="twitter:image"]', "content"),
        ('meta[name="twitter:image:src"]', "content"),
    )
    for selector, attribute in selectors:
        node = soup.select_one(selector)
        value = node.get(attribute) if node else None
        if value:
            return urljoin(story.url, str(value).strip())
    return None


def _html_text(value: Any) -> str:
    text = BeautifulSoup(str(value or ""), "html.parser").get_text(" ", strip=True)
    return " ".join(text.split())


def _published_at(entry: Any) -> datetime:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        parsed_time = entry.get(key)
        if parsed_time:
            return datetime.fromtimestamp(calendar.timegm(parsed_time), tz=timezone.utc)
    return datetime.now(timezone.utc)


def _entry_image_url(entry: Any, story_url: str) -> str | None:
    for key in ("media_content", "media_thumbnail"):
        for media in entry.get(key, []) or []:
            url = media.get("url") if isinstance(media, dict) else None
            if url:
                return urljoin(story_url, str(url).strip())

    for enclosure in entry.get("enclosures", []) or []:
        if not isinstance(enclosure, dict):
            continue
        media_type = str(enclosure.get("type") or "").lower()
        url = enclosure.get("href") or enclosure.get("url")
        if url and (media_type.startswith("image/") or _looks_like_image(str(url))):
            return urljoin(story_url, str(url).strip())

    html_fragments: Iterable[str] = (
        str(item.get("value") or "")
        for item in entry.get("content", []) or []
        if isinstance(item, dict)
    )
    for html in (*html_fragments, str(entry.get("summary") or "")):
        image = BeautifulSoup(html, "html.parser").find("img")
        src = image.get("src") if image else None
        if src:
            return urljoin(story_url, str(src).strip())
    return None


def _looks_like_image(url: str) -> bool:
    path = url.lower().split("?", 1)[0]
    return path.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"))
