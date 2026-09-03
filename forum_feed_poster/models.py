"""Shared data models for the news poster."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class NewsSource:
    name: str
    url: str


@dataclass(frozen=True)
class NewsStory:
    source: str
    title: str
    summary: str
    url: str
    published_at: datetime
    image_url: str | None = None
    categories: tuple[str, ...] = ()
