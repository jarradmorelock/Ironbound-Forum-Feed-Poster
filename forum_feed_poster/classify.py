"""Map story language to the Discord Forum's existing tag taxonomy."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence

from .models import NewsStory

TAG_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Practice Report",
        (
            "practice report",
            "did not practice",
            "dnp",
            "limited practice",
            "limited participant",
            "full participant",
            "returned to practice",
            "returns to practice",
            "missed practice",
        ),
    ),
    (
        "Injury",
        (
            "injury",
            "injured",
            "acl",
            "mcl",
            "concussion",
            "hamstring",
            "ankle",
            "knee",
            "shoulder",
            "illness",
            "injured reserve",
            "season-ending",
            "surgery",
        ),
    ),
    (
        "Legal Trouble",
        (
            "suspended",
            "suspends",
            "suspension",
            "discipline",
            "disciplinary",
            "arrested",
            "arrest",
            "charged with",
            "criminal charge",
            "legal trouble",
            "dui",
            "lawsuit",
            "under investigation",
        ),
    ),
    (
        "Contract",
        (
            "signed",
            "signs with",
            "agreed to",
            "extension",
            "contract",
            "restructured",
            "restructure",
            "franchise tag",
            "holdout",
        ),
    ),
    (
        "NFL Moves",
        (
            "released",
            "waived",
            "claimed",
            "traded",
            "activated",
            "promoted from",
            "elevated from",
        ),
    ),
    (
        "Depth Chart",
        (
            "depth chart",
            "named starter",
            "starter role",
            "starting job",
            "starting role",
            "first-team",
            "backup",
            "backup role",
            "demoted",
            "moves ahead of",
            "backfield outlook",
            "backfield role",
            "lead back",
            "lead-back",
            "workhorse",
            "committee",
            "timeshare",
            "pecking order",
            "same role",
        ),
    ),
    (
        "Waiver Watch",
        (
            "waiver wire",
            "waiver pickup",
            "must-add",
            "must add",
            "top pickup",
            "stash",
            "free-agent add",
        ),
    ),
    (
        "Fantasy Analysis",
        (
            "fantasy impact",
            "fantasy outlook",
            "start/sit",
            "start or sit",
            "ranking",
            "projection",
            "target share",
            "snap share",
            "touches",
            "usage",
            "breakout",
            "sleeper",
            "upside",
            "idp",
            "commentary",
        ),
    ),
)

BREAKING_TERMS = (
    "breaking",
    "ruled out",
    "out for season",
    "season-ending",
    "placed on injured reserve",
    "traded",
    "released",
    "suspended",
    "suspends",
    "arrested",
    "charged with",
    "agreed to",
    "signs with",
)


def classify_story(story: NewsStory) -> list[str]:
    text = " ".join((story.title, story.summary, *story.categories)).lower()
    tags: list[str] = []
    if _contains_term(text, BREAKING_TERMS):
        tags.append("Breaking")

    for tag_name, terms in TAG_RULES:
        if _contains_term(text, terms):
            tags.append(tag_name)

    if len(tags) == (1 if tags and tags[0] == "Breaking" else 0):
        tags.append("General News")
    return tags[:5]


def tag_ids_for_names(tag_names: Sequence[str], configured: Mapping[str, str]) -> list[str]:
    normalized_mapping = {_normalize_tag_name(name): tag_id for name, tag_id in configured.items()}
    return [
        normalized_mapping[_normalize_tag_name(name)]
        for name in tag_names
        if _normalize_tag_name(name) in normalized_mapping
    ][:5]


def _contains_term(text: str, terms: Sequence[str]) -> bool:
    return any(term in text for term in terms)


def _normalize_tag_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", normalized.lower()).strip()
