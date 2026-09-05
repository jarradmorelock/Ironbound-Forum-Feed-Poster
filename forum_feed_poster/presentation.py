"""Resolve player/team metadata and create concise player-first headlines."""

from __future__ import annotations

import csv
import re
import textwrap
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from .models import NewsStory
from .sources import USER_AGENT
from .teams import NflTeam, TEAMS_BY_ABBREVIATION, find_team_in_text

NFLVERSE_PLAYERS_URL = (
    "https://github.com/nflverse/nflverse-data/releases/download/players/players.csv"
)
NFLVERSE_TEAM_ALIASES = {"JAC": "JAX", "LA": "LAR", "WSH": "WAS"}


@dataclass(frozen=True)
class PlayerProfile:
    key: str
    display_name: str
    first_name: str
    last_name: str
    team: str | None
    headshot_url: str | None
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class StoryPresentation:
    headline: str
    thread_title: str
    player: PlayerProfile | None
    related_players: tuple[PlayerProfile, ...]
    team: NflTeam | None

    @property
    def player_key(self) -> str | None:
        return self.player.key if self.player else None


class PlayerDirectory:
    def __init__(self, profiles: tuple[PlayerProfile, ...]) -> None:
        self.profiles = profiles
        last_name_counts = Counter(_normalize(profile.last_name) for profile in profiles)
        self.unique_last_names = {
            name for name, count in last_name_counts.items() if name and count == 1
        }

    @classmethod
    def empty(cls) -> "PlayerDirectory":
        return cls(())

    @classmethod
    def from_csv(cls, content: str, current_year: int | None = None) -> "PlayerDirectory":
        year = current_year or datetime.now(timezone.utc).year
        profiles: list[PlayerProfile] = []
        for row in csv.DictReader(content.splitlines()):
            display_name = str(row.get("display_name") or "").strip()
            last_name = str(row.get("last_name") or "").strip()
            if not display_name or not last_name:
                continue
            try:
                last_season = int(row.get("last_season") or 0)
            except ValueError:
                last_season = 0
            if last_season < year - 2:
                continue

            team = str(row.get("latest_team") or "").strip().upper() or None
            team = NFLVERSE_TEAM_ALIASES.get(team or "", team)
            if team not in TEAMS_BY_ABBREVIATION:
                team = None
            first_name = str(
                row.get("common_first_name") or row.get("first_name") or ""
            ).strip()
            aliases = _player_aliases(row, display_name, first_name, last_name)
            if not aliases:
                continue
            profiles.append(
                PlayerProfile(
                    key=str(row.get("gsis_id") or _normalize(display_name)).strip(),
                    display_name=display_name,
                    first_name=first_name,
                    last_name=last_name,
                    team=team,
                    headshot_url=str(row.get("headshot") or "").strip() or None,
                    aliases=aliases,
                )
            )
        return cls(tuple(profiles))

    def find_players(self, story: NewsStory) -> tuple[PlayerProfile, ...]:
        title = _normalize(story.title)
        summary = _normalize(story.summary)
        candidates: list[tuple[int, int, int, PlayerProfile]] = []
        for profile in self.profiles:
            best: tuple[int, int, int] | None = None
            for alias in profile.aliases:
                title_match = re.search(rf"\b{re.escape(alias)}\b", title)
                if title_match:
                    candidate = (0, title_match.start(), -len(alias))
                else:
                    summary_match = re.search(rf"\b{re.escape(alias)}\b", summary)
                    if not summary_match:
                        continue
                    candidate = (1, summary_match.start(), -len(alias))
                if best is None or candidate < best:
                    best = candidate
            if best is not None:
                candidates.append((*best, profile))

        matched_keys = {candidate[3].key for candidate in candidates}
        if candidates:
            for profile in self.profiles:
                if profile.key in matched_keys:
                    continue
                normalized_last_name = _normalize(profile.last_name)
                if normalized_last_name not in self.unique_last_names:
                    continue
                last_name_match = re.search(
                    rf"\b{re.escape(normalized_last_name)}\b", summary
                )
                if last_name_match:
                    candidates.append(
                        (2, last_name_match.start(), -len(normalized_last_name), profile)
                    )

        candidates.sort(key=lambda item: item[:3])
        unique: list[PlayerProfile] = []
        seen_keys: set[str] = set()
        for _, _, _, profile in candidates:
            if profile.key not in seen_keys:
                unique.append(profile)
                seen_keys.add(profile.key)
        return tuple(unique)


def load_player_directory(
    session: requests.Session,
    cache_path: Path,
    timeout: int,
    max_age_hours: int = 24,
    now: datetime | None = None,
) -> PlayerDirectory:
    current_time = now or datetime.now(timezone.utc)
    if cache_path.exists():
        modified = datetime.fromtimestamp(cache_path.stat().st_mtime, tz=timezone.utc)
        if current_time - modified <= timedelta(hours=max_age_hours):
            return PlayerDirectory.from_csv(cache_path.read_text(encoding="utf-8"))

    try:
        response = session.get(
            NFLVERSE_PLAYERS_URL,
            headers={"Accept": "text/csv", "User-Agent": USER_AGENT},
            timeout=timeout,
        )
        response.raise_for_status()
        content = response.text
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = cache_path.with_suffix(cache_path.suffix + ".tmp")
        temporary_path.write_text(content, encoding="utf-8")
        temporary_path.replace(cache_path)
        return PlayerDirectory.from_csv(content)
    except (OSError, requests.RequestException):
        if cache_path.exists():
            return PlayerDirectory.from_csv(cache_path.read_text(encoding="utf-8"))
        raise


def present_story(story: NewsStory, directory: PlayerDirectory) -> StoryPresentation:
    players = directory.find_players(story)
    player = players[0] if players else None
    team = TEAMS_BY_ABBREVIATION.get(player.team) if player and player.team else None
    if team is None:
        team = find_team_in_text(f"{story.title} {story.summary}")

    headline = editorial_headline(story, player, players[1:], team)
    prefix = f"[{team.abbreviation}] " if team else ""
    thread_title = textwrap.shorten(
        f"{prefix}{headline}", width=100, placeholder="…"
    )
    return StoryPresentation(
        headline=headline,
        thread_title=thread_title,
        player=player,
        related_players=players[1:],
        team=team,
    )


def editorial_headline(
    story: NewsStory,
    player: PlayerProfile | None,
    related_players: tuple[PlayerProfile, ...] = (),
    team: NflTeam | None = None,
) -> str:
    title = " ".join(story.title.split()).strip()
    title = re.sub(
        r"^(?:breaking|report|news|update|analysis)\s*[:\-–—]\s*",
        "",
        title,
        flags=re.IGNORECASE,
    )
    if not player:
        return textwrap.shorten(title, width=92, placeholder="…")

    lowered_title = title.lower().replace("’", "'")
    lowered_summary = story.summary.lower().replace("’", "'")
    negative_draft_advice = re.search(
        r"(?:should(?:n't| not)|don't)\s+(?:bother\s+)?drafting|avoid drafting|draft fade",
        lowered_title,
    )
    role_context = any(
        phrase in lowered_summary
        for phrase in ("same role", "backfield role", "workhorse", "committee", "timeshare")
    )
    absence_context = any(
        phrase in lowered_summary
        for phrase in ("goes down", "misses time", "were injured", "is injured")
    )
    if negative_draft_advice and role_context and absence_context and related_players:
        other = next(
            (
                candidate
                for candidate in related_players
                if re.search(
                    rf"\b{re.escape(candidate.last_name.lower())}\b.{{0,30}}"
                    r"\b(?:goes down|misses time|is injured|were injured)\b",
                    lowered_summary,
                )
            ),
            related_players[0],
        )
        return (
            f"{player.display_name} Unlikely to Become Workhorse if "
            f"{other.last_name} Misses Time"
        )
    if negative_draft_advice:
        return f"{player.display_name} Carries Significant Fantasy Draft Risk"

    availability_headline = _availability_headline(story, player, team)
    if availability_headline:
        return availability_headline

    normalized_title = _normalize(title)
    primary_alias = next(
        (alias for alias in player.aliases if re.search(rf"\b{re.escape(alias)}\b", normalized_title)),
        None,
    )
    if primary_alias and not normalized_title.startswith(primary_alias):
        title = f"{player.display_name}: {title}"
    return textwrap.shorten(title, width=92, placeholder="…")


def _availability_headline(
    story: NewsStory, player: PlayerProfile, team: NflTeam | None
) -> str | None:
    title = story.title.lower().replace("’", "'")
    summary = story.summary.lower().replace("’", "'")
    text = f"{title} {summary}"
    week_match = re.search(r"\bweek\s+([0-9]{1,2})\b", text)
    week_suffix = f" Week {week_match.group(1)}" if week_match else ""

    if any(
        phrase in text
        for phrase in (
            "ruled out",
            "will not play",
            "won't play",
            "inactive for",
        )
    ):
        return f"{player.display_name} Ruled Out{' for' if week_suffix else ''}{week_suffix}"

    for status, label in (("doubtful", "Doubtful"), ("questionable", "Questionable")):
        if status in text:
            return f"{player.display_name} {label}{' for' if week_suffix else ''}{week_suffix}"

    expected_to_play = any(
        phrase in text
        for phrase in (
            "will play",
            "expected to play",
            "set to play",
            "on track to play",
            "cleared to play",
        )
    ) or bool(re.search(r"\bconfirms?\b.{0,60}\bfor week\b", title))
    if not expected_to_play:
        return None

    travel_context = any(term in text for term in ("travel", "trip", "in australia"))
    if "australia" in text:
        return f"{player.display_name} Expected to Play{week_suffix} in Australia"
    if travel_context and team:
        nickname = team.name.rsplit(" ", 1)[-1]
        return (
            f"{player.display_name} Expected to Play{week_suffix} "
            f"After Joining {nickname} Trip"
        )
    return f"{player.display_name} Expected to Play{week_suffix}"


def _player_aliases(
    row: dict[str, str], display_name: str, first_name: str, last_name: str
) -> tuple[str, ...]:
    raw_aliases = {
        display_name,
        f"{first_name} {last_name}",
        f"{row.get('first_name') or ''} {last_name}",
        f"{row.get('football_name') or ''} {last_name}",
    }
    aliases = {
        _normalize(alias)
        for alias in raw_aliases
        if len(_normalize(alias).split()) >= 2
    }
    return tuple(sorted(aliases, key=lambda value: (-len(value), value)))


def _normalize(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return " ".join(re.findall(r"[a-z0-9]+", ascii_value.lower()))
