"""NFL team names, abbreviations, aliases, and Discord emoji names."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class NflTeam:
    abbreviation: str
    name: str
    emoji_name: str
    aliases: tuple[str, ...]


NFL_TEAMS = (
    NflTeam("ARI", "Arizona Cardinals", "cardinals", ("Arizona Cardinals", "Cardinals")),
    NflTeam("ATL", "Atlanta Falcons", "falcons", ("Atlanta Falcons", "Falcons")),
    NflTeam("BAL", "Baltimore Ravens", "ravens", ("Baltimore Ravens", "Ravens")),
    NflTeam("BUF", "Buffalo Bills", "bills", ("Buffalo Bills", "Bills")),
    NflTeam("CAR", "Carolina Panthers", "panthers", ("Carolina Panthers", "Panthers")),
    NflTeam("CHI", "Chicago Bears", "bears", ("Chicago Bears", "Bears")),
    NflTeam("CIN", "Cincinnati Bengals", "bengals", ("Cincinnati Bengals", "Bengals")),
    NflTeam("CLE", "Cleveland Browns", "browns", ("Cleveland Browns", "Browns")),
    NflTeam("DAL", "Dallas Cowboys", "cowboys", ("Dallas Cowboys", "Cowboys")),
    NflTeam("DEN", "Denver Broncos", "broncos", ("Denver Broncos", "Broncos")),
    NflTeam("DET", "Detroit Lions", "lions", ("Detroit Lions", "Lions")),
    NflTeam("GB", "Green Bay Packers", "packers", ("Green Bay Packers", "Packers")),
    NflTeam("HOU", "Houston Texans", "texans", ("Houston Texans", "Texans")),
    NflTeam("IND", "Indianapolis Colts", "colts", ("Indianapolis Colts", "Colts")),
    NflTeam("JAX", "Jacksonville Jaguars", "jaguars", ("Jacksonville Jaguars", "Jaguars", "Jags")),
    NflTeam("KC", "Kansas City Chiefs", "chiefs", ("Kansas City Chiefs", "Chiefs")),
    NflTeam("LV", "Las Vegas Raiders", "raiders", ("Las Vegas Raiders", "Raiders")),
    NflTeam("LAC", "Los Angeles Chargers", "chargers", ("Los Angeles Chargers", "Chargers")),
    NflTeam("LAR", "Los Angeles Rams", "rams", ("Los Angeles Rams", "Rams")),
    NflTeam("MIA", "Miami Dolphins", "dolphins", ("Miami Dolphins", "Dolphins")),
    NflTeam("MIN", "Minnesota Vikings", "vikings", ("Minnesota Vikings", "Vikings")),
    NflTeam("NE", "New England Patriots", "patriots", ("New England Patriots", "Patriots", "Pats")),
    NflTeam("NO", "New Orleans Saints", "saints", ("New Orleans Saints", "Saints")),
    NflTeam("NYG", "New York Giants", "giants", ("New York Giants", "Giants")),
    NflTeam("NYJ", "New York Jets", "jets", ("New York Jets", "Jets")),
    NflTeam("PHI", "Philadelphia Eagles", "eagles", ("Philadelphia Eagles", "Eagles")),
    NflTeam("PIT", "Pittsburgh Steelers", "steelers", ("Pittsburgh Steelers", "Steelers")),
    NflTeam("SEA", "Seattle Seahawks", "seahawks", ("Seattle Seahawks", "Seahawks")),
    NflTeam("SF", "San Francisco 49ers", "49rs", ("San Francisco 49ers", "49ers", "Niners")),
    NflTeam("TB", "Tampa Bay Buccaneers", "buccaneers", ("Tampa Bay Buccaneers", "Buccaneers", "Bucs")),
    NflTeam("TEN", "Tennessee Titans", "titans", ("Tennessee Titans", "Titans")),
    NflTeam("WAS", "Washington Commanders", "commanders", ("Washington Commanders", "Commanders")),
)

TEAMS_BY_ABBREVIATION = {team.abbreviation: team for team in NFL_TEAMS}
TEAM_EMOJI_NAMES = {team.abbreviation: team.emoji_name for team in NFL_TEAMS}


def find_team_in_text(text: str) -> NflTeam | None:
    normalized = _normalize(text)
    matches: list[tuple[int, int, NflTeam]] = []
    for team in NFL_TEAMS:
        for alias in team.aliases:
            normalized_alias = _normalize(alias)
            match = re.search(rf"\b{re.escape(normalized_alias)}\b", normalized)
            if match:
                matches.append((match.start(), -len(normalized_alias), team))
    if not matches:
        return None
    return min(matches)[2]


def _normalize(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return " ".join(re.findall(r"[a-z0-9]+", ascii_value.lower()))
