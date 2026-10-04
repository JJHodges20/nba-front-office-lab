"""An invented league for testing models: small, seeded, and shaped like the real tables.

The fixture store is real data, but it holds one season of players for two teams, and a
model fitted to team results needs many seasons of every team. This league supplies
them. Its players, minutes and box scores are drawn at random from a seed; its team
ratings are whatever a test plants, one season at a time, so a test can decide exactly
how results follow from the players and then ask the model to find that out.

Everything is kept twice: as plain Python records, which a test can walk with loops to
compute an answer the slow, obvious way, and as frames that satisfy the lab's data
contracts, which is what the code under test receives.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from front_office.domain.schema import conform_frame
from front_office.domain.seasons import Season
from front_office.domain.tables.players import PLAYER_GAME_LOGS, PLAYER_SEASONS, PLAYERS
from front_office.domain.tables.teams import TEAM_SEASONS, TEAMS

GAMES = 82
GAME_MINUTES = 48.0
TEAM_MINUTES = GAMES * GAME_MINUTES
POSSESSIONS = 8000
LEAGUE_RATING = 105.0
"""Every team scores and allows the same points, so the league's rating is exactly this."""
TEAM_POINTS = int(POSSESSIONS * LEAGUE_RATING / 100)
LOG_GAMES = 3
"""Log rows per stint. Only the split of minutes between teams is read from the logs."""

RATES = {  # per 100 possessions on the court: (league mean, spread between players)
    "fga": (17.0, 4.0),
    "fta": (5.0, 2.0),
    "oreb": (2.2, 1.2),
    "dreb": (6.5, 2.0),
    "ast": (4.5, 2.5),
    "tov": (2.8, 0.9),
    "stl": (1.6, 0.5),
    "blk": (1.0, 0.7),
    "pf": (4.2, 1.0),
}


@dataclass
class Line:
    """One player's season: what ``player_seasons`` holds, as plain values."""

    player_id: int
    year: int
    age: int
    team_id: int
    """The team the season ended with."""
    games: int
    minutes: float
    possessions: int | None
    totals: dict[str, int]
    off_rating: float | None
    def_rating: float | None
    plus_minus: int
    pie: float


@dataclass
class Stint:
    player_id: int
    year: int
    team_id: int
    minutes: float


@dataclass
class SyntheticLeague:
    """Seasons of invented players, with team ratings planted season by season."""

    team_ids: list[int]
    years: list[int]
    lines: dict[int, list[Line]] = field(default_factory=dict)
    stints: dict[int, list[Stint]] = field(default_factory=dict)
    ratings: dict[int, dict[int, tuple[float, float]]] = field(default_factory=dict)
    """Relative offensive and defensive rating of each team, for the seasons planted."""
    unfinished: set[int] = field(default_factory=set)
    """Seasons whose postseason is undecided: their outcomes are null."""

    def plant(self, year: int, ratings: dict[int, tuple[float, float]]) -> None:
        assert set(ratings) == set(self.team_ids), "a season needs a rating for every team"
        self.ratings[year] = dict(ratings)

    def plant_at_random(self, year: int, *, seed: int = 0, spread: float = 3.0) -> None:
        generator = np.random.default_rng([seed, year])
        self.plant(
            year,
            {
                team: (float(generator.normal(0, spread)), float(generator.normal(0, spread)))
                for team in self.team_ids
            },
        )

    def tables(self) -> dict[str, pd.DataFrame]:
        """The seasons planted so far, as the frames a build would hold."""
        years = sorted(self.ratings)
        return {
            "player_seasons": self._player_seasons(years),
            "player_game_logs": self._player_game_logs(years),
            "team_seasons": self._team_seasons(years),
        }

    def reference_tables(self) -> dict[str, pd.DataFrame]:
        """``teams`` and ``players``: who the ids in the other tables are."""
        teams = pd.DataFrame(
            [
                {
                    "team_id": team,
                    "abbreviation": f"T{team:02d}",
                    "city": f"City {team}",
                    "nickname": f"Team {team}",
                    "full_name": f"City {team} Team {team}",
                    "conference": "East" if place % 2 == 0 else "West",
                    "division": "Invented",
                    "first_season_year": self.years[0],
                }
                for place, team in enumerate(self.team_ids)
            ],
            columns=list(TEAMS.column_names),
        )
        seen: dict[int, list[int]] = {}
        for year in sorted(self.lines):
            for line in self.lines[year]:
                seen.setdefault(line.player_id, []).append(year)
        last = max(self.lines)
        team_now = {line.player_id: line.team_id for line in self.lines[last]}
        players = pd.DataFrame(
            [
                {
                    "player_id": player,
                    "full_name": f"Player {player}",
                    "first_name": "Player",
                    "last_name": str(player),
                    "position": ("G", "F", "C", "G-F", "F-C")[player % 5],
                    "height_inches": 74 + player % 12,
                    "weight_lbs": 190 + player % 60,
                    "birth_date": None,
                    "country": "USA",
                    "college": None,
                    "draft_year": None,
                    "draft_round": None,
                    "draft_number": None,
                    "first_season_year": years[0],
                    "last_season_year": years[-1],
                    "is_active": player in team_now,
                    "current_team_id": team_now.get(player),
                }
                for player, years in sorted(seen.items())
            ],
            columns=list(PLAYERS.column_names),
        )
        return {"teams": conform_frame(teams, TEAMS), "players": conform_frame(players, PLAYERS)}

    def _player_seasons(self, years: list[int]) -> pd.DataFrame:
        rows = []
        for year in years:
            teams_of = {}
            for stint in self.stints[year]:
                teams_of.setdefault(stint.player_id, set()).add(stint.team_id)
            for line in self.lines[year]:
                net = None if line.off_rating is None else line.off_rating - line.def_rating
                rows.append(
                    {
                        "player_id": line.player_id,
                        "season": Season(year).label,
                        "season_type": "regular",
                        "player_name": f"Player {line.player_id}",
                        "team_id": line.team_id,
                        "team_count": len(teams_of[line.player_id]),
                        "age": line.age,
                        "games_played": line.games,
                        "games_started": line.games // 2,
                        "wins": line.games // 2,
                        "losses": line.games - line.games // 2,
                        "minutes": line.minutes,
                        **line.totals,
                        "blocked_attempts": 0,
                        "fouls_drawn": 0,
                        "plus_minus": line.plus_minus,
                        "double_doubles": 0,
                        "triple_doubles": 0,
                        "possessions": line.possessions,
                        "off_rating": line.off_rating,
                        "def_rating": line.def_rating,
                        "net_rating": net,
                        # Not features of the value model: spread out so that the roles
                        # built on them have someone to fill them.
                        "usage_pct": 0.12 + (line.player_id * 7 % 20) / 100,
                        "assist_pct": 0.05 + (line.player_id * 11 % 30) / 100,
                        "oreb_pct": 0.05,
                        "dreb_pct": 0.15,
                        "reb_pct": 0.1,
                        "pace": 98.0,
                        "player_impact_estimate": line.pie,
                    }
                )
        frame = pd.DataFrame(rows, columns=list(PLAYER_SEASONS.column_names))
        return conform_frame(frame, PLAYER_SEASONS)

    def _player_game_logs(self, years: list[int]) -> pd.DataFrame:
        rows = []
        for year in years:
            for stint in self.stints[year]:
                for game in range(LOG_GAMES):
                    rows.append(
                        {
                            "player_id": stint.player_id,
                            "game_id": f"{year % 100:02d}{stint.team_id:04d}{game:04d}",
                            "season": Season(year).label,
                            "season_type": "regular",
                            "game_date": pd.Timestamp(year, 11, 1 + game),
                            "team_id": stint.team_id,
                            "opponent_team_id": self.team_ids[
                                (self.team_ids.index(stint.team_id) + 1) % len(self.team_ids)
                            ],
                            "is_home": True,
                            "is_neutral_site": False,
                            "won": True,
                            "minutes": round(stint.minutes / LOG_GAMES),
                            **dict.fromkeys(_BOX, 0),
                            "plus_minus": 0,
                        }
                    )
        frame = pd.DataFrame(rows, columns=list(PLAYER_GAME_LOGS.column_names))
        return conform_frame(frame, PLAYER_GAME_LOGS)

    def _team_seasons(self, years: list[int]) -> pd.DataFrame:
        rows = []
        for year in years:
            finished = year not in self.unfinished
            for place, team in enumerate(self.team_ids):
                offense, defense = self.ratings[year][team]
                wins = int(np.clip(round(41 + 2.5 * (offense + defense)), 0, GAMES))
                box = {
                    "fgm": 3100, "fga": 6800, "fg3m": 800, "fg3a": 2200, "ftm": 1400,
                    "fta": 1800, "oreb": 850, "dreb": 2700, "reb": 3550, "ast": 1900,
                    "tov": 1150, "stl": 620, "blk": 400, "pf": 1650, "pts": TEAM_POINTS,
                }  # fmt: skip
                rows.append(
                    {
                        "season": Season(year).label,
                        "team_id": team,
                        "team_name": f"Team {team}",
                        "team_abbreviation": f"T{team:02d}",
                        "conference": "East" if place % 2 == 0 else "West",
                        "division": None,
                        "conference_rank": None,
                        "games_played": GAMES,
                        "wins": wins,
                        "losses": GAMES - wins,
                        "minutes": TEAM_MINUTES,
                        **box,
                        **{f"opp_{name}": value for name, value in box.items()},
                        "possessions": POSSESSIONS,
                        "pace": POSSESSIONS / GAMES,
                        "off_rating": LEAGUE_RATING + offense,
                        "def_rating": LEAGUE_RATING - defense,
                        "net_rating": offense + defense,
                        "made_play_in": False if finished else None,
                        "made_playoffs": (place < 4) if finished else None,
                        "playoff_round_reached": 0 if finished else None,
                        "playoff_series_won": 0 if finished else None,
                        "playoff_wins": 0 if finished else None,
                        "playoff_losses": 0 if finished else None,
                        "made_conference_finals": False if finished else None,
                        "made_finals": False if finished else None,
                        "won_championship": (place == 0) if finished else None,
                    }
                )
        frame = pd.DataFrame(rows, columns=list(TEAM_SEASONS.column_names))
        return conform_frame(frame, TEAM_SEASONS)


_BOX = ("fgm", "fga", "fg3m", "fg3a", "ftm", "fta", "oreb", "dreb", "reb", "ast", "tov", "stl",
        "blk", "pf", "pts")  # fmt: skip


def make_league(
    *,
    seed: int = 0,
    teams: int = 10,
    seasons: int = 9,
    roster: int = 11,
    first_year: int = 2000,
    turnover: float = 0.2,
    trades: int = 2,
) -> SyntheticLeague:
    """A league of invented players. No team ratings are planted yet.

    Each season every team has ``roster`` players of its own, whose minutes add up to
    the team's; about ``turnover`` of them are replaced by newcomers before the next
    season, the rest change teams now and then, and ``trades`` players a season finish
    with a second team. One player a season is listed with no possessions at all.
    """
    generator = np.random.default_rng(seed)
    team_ids = [101 + number for number in range(teams)]
    league = SyntheticLeague(team_ids, [first_year + offset for offset in range(seasons)])
    talent: dict[int, dict[str, float]] = {}
    born: dict[int, int] = {}
    next_id = 1
    rosters: dict[int, list[int]] = {team: [] for team in team_ids}

    def newcomer(year: int) -> int:
        nonlocal next_id
        player = next_id
        next_id += 1
        talent[player] = {
            **{
                name: max(0.2, generator.normal(mean, spread))
                for name, (mean, spread) in RATES.items()
            },
            "fg_pct": float(np.clip(generator.normal(0.46, 0.04), 0.3, 0.65)),
            "three_share": float(np.clip(generator.normal(0.3, 0.15), 0.0, 0.8)),
            "three_pct": float(np.clip(generator.normal(0.35, 0.04), 0.2, 0.5)),
            "ft_pct": float(np.clip(generator.normal(0.76, 0.08), 0.4, 0.95)),
            "role": float(generator.uniform(0.2, 1.0)),
            "on_off": float(generator.normal(0, 3.0)),
        }
        born[player] = year - int(generator.integers(19, 34))
        return player

    for year in league.years:
        for team in team_ids:
            kept = [player for player in rosters[team] if generator.random() > turnover]
            rosters[team] = kept + [newcomer(year) for _ in range(roster - len(kept))]
        # A few players swap teams between seasons, so that players carry what they are
        # from one team's results to another's.
        for _ in range(teams):
            first, second = generator.choice(len(team_ids), size=2, replace=False)
            slot = int(generator.integers(0, roster))
            a, b = team_ids[first], team_ids[second]
            rosters[a][slot], rosters[b][slot] = rosters[b][slot], rosters[a][slot]

        stints: list[Stint] = []
        for team in team_ids:
            weights = np.array([talent[player]["role"] for player in rosters[team]])
            weights = weights * generator.uniform(0.6, 1.4, size=len(weights))
            minutes = 5 * TEAM_MINUTES * weights / weights.sum()
            # Nobody plays more than every minute: hand the excess to the others.
            for _ in range(len(minutes)):
                excess = np.clip(minutes - 0.9 * TEAM_MINUTES, 0, None)
                if not excess.any():
                    break
                room = minutes < 0.9 * TEAM_MINUTES
                minutes = minutes - excess + room * excess.sum() / room.sum()
            stints += [
                Stint(player, year, team, float(played))
                for player, played in zip(rosters[team], minutes, strict=True)
            ]
        # Mid-season trades: two players exchange what is left of their seasons.
        for _ in range(trades):
            first, second = generator.choice(len(stints), size=2, replace=False)
            one, other = stints[first], stints[second]
            if one.team_id == other.team_id or one.player_id == other.player_id:
                continue
            # Whole log games on each side of the trade, so that the game logs, which
            # hold whole minutes, split a traded player's season exactly as it was.
            moved = float(LOG_GAMES * round(0.4 * min(one.minutes, other.minutes) / LOG_GAMES))
            one.minutes = float(LOG_GAMES * round((one.minutes - moved) / LOG_GAMES))
            other.minutes = float(LOG_GAMES * round((other.minutes - moved) / LOG_GAMES))
            stints.append(Stint(one.player_id, year, other.team_id, moved))
            stints.append(Stint(other.player_id, year, one.team_id, moved))
        league.stints[year] = stints
        league.lines[year] = _lines(year, stints, _uncounted(stints), talent, born, generator)
    return league


def _uncounted(stints: list[Stint]) -> int:
    """Leave one player a single minute, and return who.

    The league lists a few players each season with no possessions at all: a few seconds
    on the floor and nothing counted. Here it is the least-used player who stayed with
    one team; the rest of those minutes go to the next least-used teammate, so the
    team's minutes still add up.
    """
    appearances: dict[int, int] = {}
    for stint in stints:
        appearances[stint.player_id] = appearances.get(stint.player_id, 0) + 1
    settled = [stint for stint in stints if appearances[stint.player_id] == 1]
    chosen = min(settled, key=lambda stint: stint.minutes)
    mate = min(
        (stint for stint in settled if stint.team_id == chosen.team_id and stint is not chosen),
        key=lambda stint: stint.minutes,
    )
    mate.minutes += chosen.minutes - 1.0
    chosen.minutes = 1.0
    return chosen.player_id


def _lines(
    year: int,
    stints: list[Stint],
    uncounted: int,
    talent: dict[int, dict[str, float]],
    born: dict[int, int],
    generator: np.random.Generator,
) -> list[Line]:
    by_player: dict[int, list[Stint]] = {}
    for stint in stints:
        by_player.setdefault(stint.player_id, []).append(stint)
    lines = []
    for player, played in sorted(by_player.items()):
        minutes = sum(stint.minutes for stint in played)
        if player == uncounted:
            nothing = dict.fromkeys(_BOX, 0)
            age, team = year - born[player], played[0].team_id
            lines.append(
                Line(player, year, age, team, 1, minutes, None, nothing, None, None, 0, 0.0)
            )
            continue
        skill = talent[player]
        per_game = 6 + 30 * skill["role"]
        games = int(np.clip(round(minutes / per_game), 1, GAMES))
        possessions = max(1, round(minutes * 2.03))

        def count(
            name: str, skill: dict[str, float] = skill, possessions: int = possessions
        ) -> int:
            rate = max(0.0, skill[name] * generator.normal(1.0, 0.1))
            return round(rate * possessions / 100)

        fga, fta = count("fga"), count("fta")
        fg3a = min(fga, round(fga * skill["three_share"]))
        fg3m = round(fg3a * skill["three_pct"])
        fgm = min(fga, fg3m + round((fga - fg3a) * (skill["fg_pct"] + 0.05)))
        ftm = min(fta, round(fta * skill["ft_pct"]))
        oreb, dreb = count("oreb"), count("dreb")
        totals = {
            "fgm": fgm, "fga": fga, "fg3m": fg3m, "fg3a": fg3a, "ftm": ftm, "fta": fta,
            "oreb": oreb, "dreb": dreb, "reb": oreb + dreb, "ast": count("ast"),
            "tov": count("tov"), "stl": count("stl"), "blk": count("blk"), "pf": count("pf"),
            "pts": 2 * fgm + fg3m + ftm,
        }  # fmt: skip
        offense = round(LEAGUE_RATING + skill["on_off"] / 2 + generator.normal(0, 2.5), 1)
        defense = round(LEAGUE_RATING - skill["on_off"] / 2 + generator.normal(0, 2.5), 1)
        lines.append(
            Line(
                player_id=player,
                year=year,
                age=year - born[player],
                team_id=played[-1].team_id,
                games=games,
                minutes=minutes,
                possessions=possessions,
                totals=totals,
                off_rating=offense,
                def_rating=defense,
                plus_minus=round((offense - defense) * possessions / 100),
                pie=round(0.1 + skill["on_off"] / 100 + float(generator.normal(0, 0.01)), 3),
            )
        )
    return lines
