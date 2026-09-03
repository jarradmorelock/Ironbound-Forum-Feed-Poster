"""Persistent exact and fuzzy story duplicate detection."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .models import NewsStory

TRACKING_PARAMETERS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "source",
}
STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "has",
    "have",
    "he",
    "his",
    "in",
    "is",
    "it",
    "its",
    "more",
    "new",
    "nfl",
    "of",
    "on",
    "says",
    "that",
    "the",
    "their",
    "this",
    "to",
    "with",
}
TOKEN_ALIASES = {
    "agreed": "agree",
    "agrees": "agree",
    "injured": "injury",
    "injuries": "injury",
    "practiced": "practice",
    "practicing": "practice",
    "released": "release",
    "releases": "release",
    "signed": "sign",
    "signing": "sign",
    "signs": "sign",
    "traded": "trade",
    "trades": "trade",
    "waived": "waive",
}


@dataclass
class SeenStory:
    source: str
    title: str
    normalized_title: str
    canonical_url: str
    title_tokens: list[str]
    content_tokens: list[str]
    seen_at: str


class DedupeStore:
    def __init__(self, path: Path, window_hours: int, similarity: float) -> None:
        self.path = path
        self.window = timedelta(hours=window_hours)
        self.similarity = similarity
        self.records = self._load()
        self.prune()

    def is_duplicate(self, story: NewsStory) -> bool:
        canonical = canonicalize_url(story.url)
        normalized_title = normalize_text(story.title)
        title_tokens = tokenize(story.title)
        content_tokens = tokenize(f"{story.title} {story.summary[:600]}")

        for record in self.records:
            if canonical and canonical == record.canonical_url:
                return True
            if normalized_title and normalized_title == record.normalized_title:
                return True
            if SequenceMatcher(None, normalized_title, record.normalized_title).ratio() >= 0.86:
                return True

            record_title_tokens = set(record.title_tokens)
            record_content_tokens = set(record.content_tokens)
            title_shared = len(title_tokens & record_title_tokens)
            title_overlap = _overlap_coefficient(title_tokens, record_title_tokens)
            content_shared = len(content_tokens & record_content_tokens)
            content_overlap = _overlap_coefficient(content_tokens, record_content_tokens)
            if title_shared >= 3 and title_overlap >= self.similarity:
                return True
            if content_shared >= 5 and content_overlap >= self.similarity:
                return True
        return False

    def remember(self, story: NewsStory, now: datetime | None = None) -> None:
        seen_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        self.records.append(
            SeenStory(
                source=story.source,
                title=story.title,
                normalized_title=normalize_text(story.title),
                canonical_url=canonicalize_url(story.url),
                title_tokens=sorted(tokenize(story.title)),
                content_tokens=sorted(tokenize(f"{story.title} {story.summary[:600]}")),
                seen_at=seen_at.isoformat(),
            )
        )

    def prune(self, now: datetime | None = None) -> None:
        cutoff = (now or datetime.now(timezone.utc)) - self.window
        retained: list[SeenStory] = []
        for record in self.records:
            try:
                seen_at = datetime.fromisoformat(record.seen_at)
                if seen_at.tzinfo is None:
                    seen_at = seen_at.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if seen_at >= cutoff:
                retained.append(record)
        self.records = retained

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary_path.write_text(
            json.dumps(
                {"version": 1, "stories": [asdict(record) for record in self.records]},
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(self.path)

    def _load(self) -> list[SeenStory]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return [SeenStory(**item) for item in data.get("stories", [])]
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return []


def canonicalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in TRACKING_PARAMETERS
    ]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))


def normalize_text(text: str) -> str:
    return " ".join(sorted(tokenize(text)))


def tokenize(text: str) -> set[str]:
    normalized = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    words = re.findall(r"[a-z0-9]+", normalized.lower())
    return {
        TOKEN_ALIASES.get(word, word)
        for word in words
        if len(word) > 1 and word not in STOP_WORDS
    }


def _overlap_coefficient(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / min(len(left), len(right))
