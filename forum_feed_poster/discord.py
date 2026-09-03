"""Build and send gallery-ready Discord Forum webhook posts."""

from __future__ import annotations

import json
import mimetypes
import re
import textwrap
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit

import requests
from PIL import Image, ImageDraw, ImageFont

from .models import NewsStory
from .sources import USER_AGENT

DISCORD_CONTENT_LIMIT = 2_000
DISCORD_THREAD_NAME_LIMIT = 100
MAX_IMAGE_BYTES = 8 * 1024 * 1024
IMAGE_CONTENT_TYPES = {
    "image/avif": ".avif",
    "image/gif": ".gif",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


@dataclass(frozen=True)
class ImageAttachment:
    filename: str
    content_type: str
    data: bytes


def generate_story_card(story: NewsStory) -> ImageAttachment:
    """Create a clean Gallery thumbnail when a source does not supply an image."""
    canvas = Image.new("RGB", (1200, 675), "#0b1220")
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, 1200, 18), fill="#d43c32")
    draw.rounded_rectangle((70, 72, 1130, 603), radius=28, fill="#131f33")

    eyebrow_font = _load_font(30, bold=True)
    title_font = _load_font(58, bold=True)
    source_font = _load_font(28, bold=False)
    draw.text((115, 120), "IRONBOUND  •  PLAYER NEWS", font=eyebrow_font, fill="#ef5a50")

    title_lines = _wrap_title(draw, story.title, title_font, max_width=970, max_lines=5)
    y = 195
    for line in title_lines:
        draw.text((115, y), line, font=title_font, fill="#f8fafc")
        y += 72
    draw.text((115, 540), story.source.upper(), font=source_font, fill="#a9b7cc")

    output = BytesIO()
    canvas.save(output, format="PNG", optimize=True)
    return ImageAttachment(
        filename=_image_filename(story.title, "story.png", ".png"),
        content_type="image/png",
        data=output.getvalue(),
    )


def download_image(
    image_url: str,
    title: str,
    session: requests.Session,
    timeout: int,
) -> ImageAttachment:
    response = session.get(
        image_url,
        headers={"Accept": "image/*", "User-Agent": USER_AGENT},
        timeout=timeout,
        stream=True,
    )
    response.raise_for_status()

    content_type = response.headers.get("Content-Type", "").split(";", 1)[0].lower()
    if content_type not in IMAGE_CONTENT_TYPES:
        guessed_type, _ = mimetypes.guess_type(urlsplit(image_url).path)
        content_type = guessed_type or content_type
    if content_type not in IMAGE_CONTENT_TYPES:
        raise ValueError(f"Unsupported story image type: {content_type or 'unknown'}")

    chunks: list[bytes] = []
    total_bytes = 0
    for chunk in response.iter_content(chunk_size=64 * 1024):
        if not chunk:
            continue
        total_bytes += len(chunk)
        if total_bytes > MAX_IMAGE_BYTES:
            raise ValueError("Story image is larger than the 8 MB safety limit")
        chunks.append(chunk)

    if total_bytes == 0:
        raise ValueError("Story image was empty")
    filename = _image_filename(title, image_url, IMAGE_CONTENT_TYPES[content_type])
    return ImageAttachment(filename=filename, content_type=content_type, data=b"".join(chunks))


def build_payload(
    story: NewsStory,
    tag_ids: Sequence[str],
    attachment: ImageAttachment,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "thread_name": story.title[:DISCORD_THREAD_NAME_LIMIT],
        "content": format_story(story),
        "allowed_mentions": {"parse": []},
        "attachments": [
            {
                "id": 0,
                "filename": attachment.filename,
                "description": story.title[:1_024],
            }
        ],
    }
    if tag_ids:
        payload["applied_tags"] = list(tag_ids[:5])
    return payload


def format_story(story: NewsStory) -> str:
    timestamp = int(story.published_at.timestamp())
    headline = story.title[:300]
    summary = story.summary.strip()
    if len(summary) > 650:
        summary = summary[:647].rstrip() + "..."
    content = (
        f"## {headline}\n\n"
        f"{summary}\n\n"
        f"[Read the full story]({story.url})\n"
        f"-# {story.source} • <t:{timestamp}:R>"
    )
    if len(content) <= DISCORD_CONTENT_LIMIT:
        return content
    overflow = len(content) - DISCORD_CONTENT_LIMIT
    shorter_summary = summary[: max(0, len(summary) - overflow - 3)].rstrip() + "..."
    return content.replace(summary, shorter_summary, 1)


def send_forum_post(
    webhook_url: str,
    payload: Mapping[str, Any],
    attachment: ImageAttachment,
    session: requests.Session,
    timeout: int,
) -> None:
    response = session.post(
        webhook_url,
        params={"wait": "true"},
        data={"payload_json": json.dumps(payload)},
        files={
            "files[0]": (
                attachment.filename,
                attachment.data,
                attachment.content_type,
            )
        },
        timeout=timeout,
    )
    response.raise_for_status()


def _image_filename(title: str, image_url: str, extension: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60] or "story"
    url_extension = PurePosixPath(urlsplit(image_url).path).suffix.lower()
    if url_extension in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"}:
        extension = ".jpg" if url_extension == ".jpeg" else url_extension
    return f"{slug}{extension}"


def _load_font(size: int, bold: bool) -> ImageFont.ImageFont:
    names = (
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
        "Arial Bold.ttf" if bold else "Arial.ttf",
    )
    directories = (
        Path("/usr/share/fonts/truetype/dejavu"),
        Path("/System/Library/Fonts/Supplemental"),
        Path("/Library/Fonts"),
    )
    for directory in directories:
        for name in names:
            font_path = directory / name
            if font_path.exists():
                return ImageFont.truetype(str(font_path), size=size)
    return ImageFont.load_default()


def _wrap_title(
    draw: ImageDraw.ImageDraw,
    title: str,
    font: ImageFont.ImageFont,
    max_width: int,
    max_lines: int,
) -> list[str]:
    words = title.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        width = draw.textbbox((0, 0), candidate, font=font)[2]
        if current and width > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)

    if len(lines) <= max_lines:
        return lines
    visible = lines[:max_lines]
    visible[-1] = textwrap.shorten(visible[-1] + " " + " ".join(lines[max_lines:]), width=34)
    return visible
