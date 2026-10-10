"""Names to ids: the players, teams and seasons the lab holds.

For the AI research assistant's pre-pass (decision 0018): a name resolves to the ids whose
recorded names match it once case, accents and punctuation are folded away. A name that
matches several is ambiguous and the caller asks which; nothing is guessed, ranked or
fitted. Players are matched on their full name, then their last name, then their first;
teams on their names as the league's index and every season's record have them, their
nickname, city or abbreviation.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

import pandas as pd

from front_office.domain.seasons import Season, SeasonType
from front_office.services.lab import Lab

Kind = Literal["player", "team", "season"]

SUFFIXES = frozenset({"jr", "sr", "ii", "iii", "iv", "v"})
# One city written two ways: the league's index gives the Clippers' city as "LA" and the
# Lakers' as "Los Angeles". A reader means either team by either.
SAME_CITY = {"la": "los angeles"}
SEASON_LABEL = re.compile(r"(?<!\d)((?:19|20)\d{2})\s*[-/]\s*((?:19|20)\d{2}|\d{2})(?![\d-])")
BARE_YEAR = re.compile(r"(?<![\d-])((?:19|20)\d{2})(?![\d-])")


def fold(text: str) -> str:
    """Lower case, accents dropped, punctuation turned to spaces: how names are compared."""
    decomposed = unicodedata.normalize("NFKD", text)
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^0-9a-z]+", " ", plain.lower()).split())


def _without_suffix(folded: str) -> str:
    words = folded.split()
    while len(words) > 1 and words[-1] in SUFFIXES:
        words.pop()
    return " ".join(words)


@dataclass(frozen=True, slots=True)
class Candidate:
    """One reading of a name."""

    kind: Kind
    id: int | str
    name: str
    detail: str
    """What tells two readings apart: a team and a span of seasons, or a franchise's name
    in a season."""
    match: str
    """How the name matched: full name, last name, first name, nickname, city..."""


class EntityService:
    """Folded name tables are kept by the instance, which lives for one answer: the lab
    reads fresh for the next."""

    def __init__(self, lab: Lab) -> None:
        self._lab = lab
        self._players: pd.DataFrame | None = None
        self._team_names: pd.DataFrame | None = None

    # --- seasons ------------------------------------------------------------------------

    def seasons(self, text: str) -> tuple[Candidate, ...]:
        """The seasons ``text`` can mean: ``2025-26`` one, a bare ``2013`` two (2012-13,
        which ended in it, and 2013-14, which began in it)."""
        labelled = SEASON_LABEL.search(text)
        if labelled:
            start = int(labelled.group(1))
            end = labelled.group(2)[-2:]
            if f"{(start + 1) % 100:02d}" != end:
                return ()
            label = Season(start).label
            return (Candidate("season", label, label, label, "season"),)
        bare = BARE_YEAR.search(text)
        if not bare:
            return ()
        year = int(bare.group(1))
        return tuple(
            Candidate("season", label, label, f"the season that {how} in {year}", "year")
            for label, how in ((Season(year - 1).label, "ended"), (Season(year).label, "began"))
        )

    # --- players ------------------------------------------------------------------------

    def players(self) -> pd.DataFrame:
        """Every player in the league's index, indexed by ``player_id``: names folded for
        matching, and the span of seasons played."""
        if self._players is not None:
            return self._players
        players = self._lab.read("players").set_index("player_id")
        full = players["full_name"].fillna("").map(fold)
        self._players = pd.DataFrame(
            {
                "full_name": players["full_name"],
                "full": full,
                "base": full.map(_without_suffix),
                "first": players["first_name"].fillna("").map(fold),
                "last": players["last_name"].fillna("").map(fold).map(_without_suffix),
                "first_season": players["first_season_year"],
                "last_season": players["last_season_year"],
            }
        )
        return self._players

    def _teams_in(self, season: str) -> pd.Series:
        """Each player's team abbreviation in a regular season, by ``player_id``."""
        rows = self._lab.read(
            "player_seasons", {"season": season, "season_type": SeasonType.REGULAR.value}
        )
        labels = self._lab.team_labels()["abbreviation"]
        teams = rows.set_index("player_id")["team_id"].map(labels)
        return teams[~teams.index.duplicated()]

    def find_players(self, text: str, season: str | None = None) -> tuple[Candidate, ...]:
        """The players ``text`` names. Within ``season``, those whose careers span it, if
        any do; a player named for a season they did not play is still that player."""
        wanted = fold(text)
        if not wanted:
            return ()
        players = self.players()
        tiers = (
            ("full", "full name"),
            ("base", "full name"),
            ("last", "last name"),
            ("first", "first name"),
        )
        matched = next(
            (
                (players[players[column] == wanted], how)
                for column, how in tiers
                if (players[column] == wanted).any()
            ),
            None,
        )
        if matched is None:
            return ()
        found, how = matched
        teams = pd.Series(dtype=object)
        if season is not None:
            start = Season.parse(season).start_year
            spanning = found[(found["first_season"] <= start) & (found["last_season"] >= start)]
            if not spanning.empty:
                found = spanning
            teams = self._teams_in(season)
        return tuple(
            Candidate(
                "player",
                int(player_id),
                str(row["full_name"]),
                _career(row, teams.get(player_id)),
                how,
            )
            for player_id, row in found.sort_values("full_name").iterrows()
        )

    # --- teams --------------------------------------------------------------------------

    def team_names(self) -> pd.DataFrame:
        """Every name a franchise has gone by: ``team_id``, ``name`` (folded), ``label`` (as
        written), ``team`` (the franchise's name then), ``how``, and ``season`` - one row
        per season a recorded name was used, or none for the names the franchise has now."""
        if self._team_names is not None:
            return self._team_names
        rows = []
        for team in self._lab.read("teams").itertuples():
            for how, value in (
                ("full name", team.full_name),
                ("nickname", team.nickname),
                ("city", team.city),
                ("abbreviation", team.abbreviation),
            ):
                rows.append((team.team_id, value, team.full_name, how, None))
        columns = ["season", "team_id", "team_name", "team_abbreviation"]
        for season in self._lab.read("team_seasons")[columns].itertuples():
            name = str(season.team_name)
            rows.append((season.team_id, name, name, "name that season", season.season))
            rows.append(
                (season.team_id, name.split()[-1], name, "nickname that season", season.season)
            )
            if isinstance(season.team_abbreviation, str):
                rows.append(
                    (
                        season.team_id,
                        season.team_abbreviation,
                        name,
                        "abbreviation that season",
                        season.season,
                    )
                )
        names = pd.DataFrame(rows, columns=["team_id", "label", "team", "how", "season"])
        names["name"] = names["label"].fillna("").map(fold).replace(SAME_CITY)
        self._team_names = names.drop_duplicates(["team_id", "name", "season"])
        return self._team_names

    def find_teams(self, text: str, season: str | None = None) -> tuple[Candidate, ...]:
        """The franchises ``text`` names: in ``season`` if one is given, by the name the
        franchise had that season, else by any name it has had or has now."""
        wanted = SAME_CITY.get(fold(text), fold(text))
        if not wanted:
            return ()
        found = self.team_names()
        found = found[found["name"] == wanted]
        if season is not None:
            then = found[found["season"] == season]
            if not then.empty:
                found = found[found["team_id"].isin(then["team_id"])]
        current_names = self._lab.team_labels()["full_name"]
        candidates = []
        for team_id, rows in found.groupby("team_id"):
            dated = rows[rows["season"].notna()]
            best = rows.iloc[0] if dated.empty else dated.iloc[0]
            detail = (
                str(best["team"]) if dated.empty else f"{best['team']}, {_runs(dated['season'])}"
            )
            candidates.append(
                Candidate(
                    "team",
                    int(team_id),
                    str(current_names.get(team_id, best["team"])),
                    detail,
                    str(rows.iloc[0]["how"]),
                )
            )
        return tuple(sorted(candidates, key=lambda candidate: candidate.name))

    def resolve(
        self, text: str, kind: Literal["any", "player", "team"] = "any", season: str | None = None
    ) -> tuple[Candidate, ...]:
        """Every reading of ``text`` as a team or a player. A team name is read as a team."""
        if kind in ("any", "team"):
            teams = self.find_teams(text, season)
            if teams or kind == "team":
                return teams
        return self.find_players(text, season)


def _runs(seasons: pd.Series) -> str:
    """Seasons as unbroken runs: ``1996-97 to 2001-02, 2014-15 to 2025-26``."""
    years = sorted({Season.parse(label).start_year for label in seasons})
    runs: list[list[int]] = []
    for year in years:
        if runs and year == runs[-1][-1] + 1:
            runs[-1].append(year)
        else:
            runs.append([year])
    return ", ".join(
        Season(run[0]).label
        if len(run) == 1
        else f"{Season(run[0]).label} to {Season(run[-1]).label}"
        for run in runs
    )


def _career(row: pd.Series, team: object) -> str:
    first, last = row["first_season"], row["last_season"]
    span = "" if pd.isna(first) else f"{Season(int(first)).label} to {Season(int(last)).label}"
    return ", ".join(part for part in (team if isinstance(team, str) else "", span) if part)
