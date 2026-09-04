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
from PIL import Image, ImageDraw, ImageFont, ImageOps

from .models import NewsStory
from .presentation import StoryPresentation
from .sources import USER_AGENT
from .teams import NflTeam

DISCORD_CONTENT_LIMIT = 2_000
DISCORD_THREAD_NAME_LIMIT = 100
MAX_IMAGE_BYTES = 8 * 1024 * 1024
SUPPRESS_EMBEDS = 1 << 2
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


@dataclass(frozen=True)
class WebhookMessage:
    id: str
    channel_id: str


class DiscordRequestError(ValueError):
    def __init__(self, action: str, status_code: int, detail: str) -> None:
        suffix = f": {detail}" if detail else ""
        super().__init__(f"Discord could not {action} (HTTP {status_code}){suffix}")
        self.status_code = status_code


def generate_story_card(
    story: NewsStory,
    headline: str | None = None,
    player_image: ImageAttachment | None = None,
    team_logo: ImageAttachment | None = None,
) -> ImageAttachment:
    """Create a clean Gallery thumbnail when a source does not supply an image."""
    canvas = Image.new("RGBA", (1200, 675), "#0b1220")
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, 1200, 18), fill="#d43c32")
    draw.rounded_rectangle((70, 72, 1130, 603), radius=28, fill="#131f33")

    text_width = 970
    if player_image:
        try:
            player = Image.open(BytesIO(player_image.data)).convert("RGBA")
            player.thumbnail((470, 525), Image.Resampling.LANCZOS)
            x = 1110 - player.width
            y = 595 - player.height
            shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
            shadow_draw = ImageDraw.Draw(shadow)
            shadow_draw.ellipse((x - 35, 540, 1140, 635), fill=(0, 0, 0, 95))
            canvas = Image.alpha_composite(canvas, shadow)
            canvas.alpha_composite(player, (x, y))
            draw = ImageDraw.Draw(canvas)
            text_width = 590
        except (OSError, ValueError):
            pass

    if team_logo:
        try:
            logo = Image.open(BytesIO(team_logo.data)).convert("RGBA")
            logo = ImageOps.contain(logo, (90, 90), Image.Resampling.LANCZOS)
            canvas.alpha_composite(logo, (1000, 100))
        except (OSError, ValueError):
            pass

    eyebrow_font = _load_font(30, bold=True)
    title_font = _load_font(52 if player_image else 58, bold=True)
    source_font = _load_font(28, bold=False)
    draw.text((115, 120), "IRONBOUND  •  PLAYER NEWS", font=eyebrow_font, fill="#ef5a50")

    title_lines = _wrap_title(
        draw,
        headline or story.title,
        title_font,
        max_width=text_width,
        max_lines=5,
    )
    y = 195
    for line in title_lines:
        draw.text((115, y), line, font=title_font, fill="#f8fafc")
        y += 72
    draw.text((115, 540), story.source.upper(), font=source_font, fill="#a9b7cc")

    output = BytesIO()
    canvas.convert("RGB").save(output, format="PNG", optimize=True)
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
    presentation: StoryPresentation | None = None,
    team_emoji: str | None = None,
) -> dict[str, Any]:
    headline = presentation.headline if presentation else story.title
    thread_title = presentation.thread_title if presentation else story.title
    payload: dict[str, Any] = {
        "thread_name": thread_title[:DISCORD_THREAD_NAME_LIMIT],
        "content": format_story(story, headline=headline, team_emoji=team_emoji),
        "flags": SUPPRESS_EMBEDS,
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


def build_update_payload(
    story: NewsStory,
    attachment: ImageAttachment,
    presentation: StoryPresentation | None = None,
    team_emoji: str | None = None,
) -> dict[str, Any]:
    headline = presentation.headline if presentation else story.title
    return {
        "content": format_story(
            story,
            headline=headline,
            team_emoji=team_emoji,
            update=True,
        ),
        "flags": SUPPRESS_EMBEDS,
        "allowed_mentions": {"parse": []},
        "attachments": [
            {
                "id": 0,
                "filename": attachment.filename,
                "description": headline[:1_024],
            }
        ],
    }


def format_story(
    story: NewsStory,
    headline: str | None = None,
    team_emoji: str | None = None,
    update: bool = False,
) -> str:
    timestamp = int(story.published_at.timestamp())
    display_headline = (headline or story.title)[:300]
    summary = story.summary.strip()
    if len(summary) > 650:
        summary = summary[:647].rstrip() + "..."
    content = (
        f"{'### Follow-up: ' if update else '## '}{team_emoji + ' ' if team_emoji else ''}"
        f"{display_headline}\n\n"
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
) -> WebhookMessage:
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
    _raise_discord_error(response, "create Forum post")
    return _webhook_message(response)


def send_thread_update(
    webhook_url: str,
    thread_id: str,
    payload: Mapping[str, Any],
    attachment: ImageAttachment,
    session: requests.Session,
    timeout: int,
) -> WebhookMessage:
    response = session.post(
        webhook_url,
        params={"wait": "true", "thread_id": thread_id},
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
    _raise_discord_error(response, "add story to Forum thread")
    return _webhook_message(response)


def rename_forum_thread(
    bot_token: str,
    thread_id: str,
    name: str,
    tag_ids: Sequence[str],
    session: requests.Session,
    timeout: int,
) -> None:
    body: dict[str, Any] = {"name": name[:DISCORD_THREAD_NAME_LIMIT]}
    if tag_ids:
        body["applied_tags"] = list(tag_ids[:5])
    response = session.patch(
        f"https://discord.com/api/v10/channels/{thread_id}",
        headers={
            "Authorization": f"Bot {bot_token}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
        json=body,
        timeout=timeout,
    )
    _raise_discord_error(response, "rename Forum thread")


def team_emoji_markup(team: NflTeam | None, emoji_ids: Mapping[str, str]) -> str | None:
    if not team:
        return None
    emoji_id = emoji_ids.get(team.abbreviation)
    if not emoji_id:
        return None
    return f"<:{team.emoji_name}:{emoji_id}>"


def team_emoji_cdn_url(team: NflTeam | None, emoji_ids: Mapping[str, str]) -> str | None:
    if not team:
        return None
    emoji_id = emoji_ids.get(team.abbreviation)
    if not emoji_id:
        return None
    return f"https://cdn.discordapp.com/emojis/{emoji_id}.webp?size=128&quality=lossless"


def _webhook_message(response: requests.Response) -> WebhookMessage:
    try:
        data = response.json()
        return WebhookMessage(id=str(data["id"]), channel_id=str(data["channel_id"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Discord returned an incomplete webhook message") from exc


def _raise_discord_error(response: requests.Response, action: str) -> None:
    if response.ok:
        return
    detail = response.text.strip().replace("\n", " ")[:240]
    raise DiscordRequestError(action, response.status_code, detail)


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
