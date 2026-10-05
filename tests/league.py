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
from datetime import date, timedelta

import numpy as np
import pandas as pd

from front_office.domain.schema import conform_frame
from front_office.domain.seasons import Season
from front_office.domain.tables.players import PLAYER_GAME_LOGS, PLAYER_SEASONS, PLAYERS
from front_office.domain.tables.teams import (
    PLAYOFF_RESULTS,
    ROUND_NAMES,
    TEAM_GAMES,
    TEAM_SEASONS,
    TEAMS,
)

GAMES = 82
GAME_MINUTES = 48.0
TEAM_MINUTES = GAMES * GAME_MINUTES
POSSESSIONS = 8000
LEAGUE_RATING = 105.0
"""Every team scores and allows the same points, so the league's rating is exactly this."""
TEAM_POINTS = int(POSSESSIONS * LEAGUE_RATING / 100)
LOG_GAMES = 3
"""Log rows per stint. Only the split of minutes between teams is read from the logs."""
PLAYOFF_PATTERN = (True, True, False, False, True, False, True)
"""The home sequence of a best-of-seven series for the side that holds home court."""
PLAYOFF_TEAMS = 8
"""Teams a conference sends to the bracket."""
FIRST_ROUND_SEEDS = ((1, 8), (4, 5), (3, 6), (2, 7))
"""First-round pairs in slot order: the winners of the first two meet, and of the last two."""

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
class PlayoffGame:
    game_id: str
    day: date
    playoff_round: int
    home_team: int
    away_team: int
    home_won: bool


@dataclass
class PlayoffSeries:
    """One series as it was played. ``team_a`` held home court."""

    playoff_round: int
    team_a: int
    team_b: int
    games: list[PlayoffGame]

    @property
    def a_wins(self) -> int:
        return sum(game.home_won == (game.home_team == self.team_a) for game in self.games)

    @property
    def b_wins(self) -> int:
        return len(self.games) - self.a_wins

    @property
    def winner(self) -> int:
        return self.team_a if self.a_wins > self.b_wins else self.team_b

    @property
    def loser(self) -> int:
        return self.team_b if self.winner == self.team_a else self.team_a


@dataclass
class Postseason:
    """One season's playoffs as they were played: every team's seed, every series in order."""

    year: int
    seeds: dict[int, int]
    """Conference rank of every team in the league that season."""
    series: list[PlayoffSeries]

    @property
    def champion(self) -> int:
        return self.series[-1].winner

    def played(self, team: int) -> list[PlayoffSeries]:
        return [series for series in self.series if team in (series.team_a, series.team_b)]

    def round_reached(self, team: int) -> int:
        return max((series.playoff_round for series in self.played(team)), default=0)

    def series_won(self, team: int) -> int:
        return sum(series.winner == team for series in self.played(team))

    def record(self, team: int) -> tuple[int, int]:
        wins = losses = 0
        for series in self.played(team):
            mine = series.a_wins if series.team_a == team else series.b_wins
            wins += mine
            losses += len(series.games) - mine
        return wins, losses


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
    postseasons: dict[int, Postseason] = field(default_factory=dict)
    """Playoffs played by :meth:`plant_postseason`, by season. Without one a finished
    season's outcomes are a fixed convention and no playoff game is on record."""

    def plant(self, year: int, ratings: dict[int, tuple[float, float]]) -> None:
        assert set(ratings) == set(self.team_ids), "a season needs a rating for every team"
        self.ratings[year] = dict(ratings)

    def plant_postseason(
        self,
        year: int,
        strengths: dict[int, tuple[float, float]],
        *,
        home_advantage: float,
        net_slope: float,
        top_slope: float,
        seed: int = 0,
    ) -> None:
        """Play the season's playoffs by a game model and keep every game and series.

        The log-odds that the home side wins a game are ``home_advantage`` plus
        ``net_slope`` per point of the gap in the first number of ``strengths`` (net
        rating) plus ``top_slope`` per point of the gap in the second (top-player
        quality). Eight teams a conference, seeded by record, best of seven in the
        2-2-1-1-1 pattern; the better seed hosts the first round, and later home court
        goes by record, then seed within a conference, then net rating.
        """
        assert set(strengths) == set(self.team_ids), "a strength for every team"
        assert year in self.ratings and year not in self.unfinished, "a finished season"
        generator = np.random.default_rng([seed, year, 7])
        conference = self._conferences()
        net = {team: strengths[team][0] for team in self.team_ids}
        top = {team: strengths[team][1] for team in self.team_ids}
        wins = {team: self._wins(*self.ratings[year][team]) for team in self.team_ids}
        seeds: dict[int, int] = {}
        order: dict[str, list[int]] = {}
        for name in ("East", "West"):
            members = sorted(
                (team for team in self.team_ids if conference[team] == name),
                key=lambda team: (-wins[team], -net[team], team),
            )
            assert len(members) >= PLAYOFF_TEAMS, "a conference needs eight teams for a bracket"
            order[name] = members
            seeds.update({team: place for place, team in enumerate(members, start=1)})
        played: list[PlayoffSeries] = []
        start = date(year + 1, 4, 15)

        def holds_home(mine: int, theirs: int) -> bool:
            if wins[mine] != wins[theirs]:
                return wins[mine] > wins[theirs]
            if conference[mine] == conference[theirs]:
                return seeds[mine] < seeds[theirs]
            if net[mine] != net[theirs]:
                return net[mine] > net[theirs]
            return mine < theirs

        def play(a: int, b: int, playoff_round: int) -> int:
            """A series in which ``a`` holds home court; returns the winner."""
            edge = net_slope * (net[a] - net[b]) + top_slope * (top[a] - top[b])
            need = len(PLAYOFF_PATTERN) // 2 + 1
            games: list[PlayoffGame] = []
            a_wins = b_wins = 0
            for at_home in PLAYOFF_PATTERN:
                home = home_advantage if at_home else -home_advantage
                a_won = bool(generator.random() < 1.0 / (1.0 + np.exp(-(home + edge))))
                number = sum(len(series.games) for series in played) + len(games)
                games.append(
                    PlayoffGame(
                        game_id=f"{year % 100:02d}9{playoff_round}{number:06d}",
                        day=start + timedelta(days=number),
                        playoff_round=playoff_round,
                        home_team=a if at_home else b,
                        away_team=b if at_home else a,
                        home_won=a_won if at_home else not a_won,
                    )
                )
                a_wins += a_won
                b_wins += not a_won
                if max(a_wins, b_wins) == need:
                    break
            series = PlayoffSeries(playoff_round, a, b, games)
            played.append(series)
            return series.winner

        def meet(x: int, y: int, playoff_round: int) -> int:
            if holds_home(x, y):
                return play(x, y, playoff_round)
            return play(y, x, playoff_round)

        finalists = []
        for name in ("East", "West"):
            seeded = order[name]
            first = [play(seeded[high - 1], seeded[low - 1], 1) for high, low in FIRST_ROUND_SEEDS]
            semis = [meet(first[0], first[1], 2), meet(first[2], first[3], 2)]
            finalists.append(meet(semis[0], semis[1], 3))
        meet(finalists[0], finalists[1], 4)
        self.postseasons[year] = Postseason(year, seeds, played)

    def _conferences(self) -> dict[int, str]:
        return {
            team: "East" if place % 2 == 0 else "West" for place, team in enumerate(self.team_ids)
        }

    @staticmethod
    def _wins(offense: float, defense: float) -> int:
        return int(np.clip(round(41 + 2.5 * (offense + defense)), 0, GAMES))

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
        frames = {
            "player_seasons": self._player_seasons(years),
            "player_game_logs": self._player_game_logs(years),
            "team_seasons": self._team_seasons(years),
        }
        if self.postseasons:
            frames["team_games"] = self._team_games(years)
            frames["playoff_results"] = self._playoff_results(years)
        return frames

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
                    "conference": conference,
                    "division": "Invented",
                    "first_season_year": self.years[0],
                }
                for team, conference in self._conferences().items()
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
        conference = self._conferences()
        for year in years:
            finished = year not in self.unfinished
            postseason = self.postseasons.get(year)
            for place, team in enumerate(self.team_ids):
                offense, defense = self.ratings[year][team]
                wins = self._wins(offense, defense)
                if postseason is None:
                    outcome = {
                        "conference_rank": None,
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
                else:
                    reached = postseason.round_reached(team)
                    won, lost = postseason.record(team)
                    outcome = {
                        "conference_rank": postseason.seeds[team],
                        "made_play_in": False,
                        "made_playoffs": reached >= 1,
                        "playoff_round_reached": reached,
                        "playoff_series_won": postseason.series_won(team),
                        "playoff_wins": won,
                        "playoff_losses": lost,
                        "made_conference_finals": reached >= 3,
                        "made_finals": reached >= 4,
                        "won_championship": postseason.champion == team,
                    }
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
                        "conference": conference[team],
                        "division": None,
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
                        **outcome,
                    }
                )
        frame = pd.DataFrame(rows, columns=list(TEAM_SEASONS.column_names))
        return conform_frame(frame, TEAM_SEASONS)

    def _team_games(self, years: list[int]) -> pd.DataFrame:
        """Every playoff game played, twice: once from each side."""
        rows = []
        for year in years:
            postseason = self.postseasons.get(year)
            if postseason is None:
                continue
            for series in postseason.series:
                for game in series.games:
                    sides = (
                        (game.home_team, game.away_team, True),
                        (game.away_team, game.home_team, False),
                    )
                    for team, opponent, is_home in sides:
                        won = game.home_won == is_home
                        rows.append(
                            {
                                "game_id": game.game_id,
                                "team_id": team,
                                "season": Season(year).label,
                                "season_type": "playoffs",
                                "game_date": pd.Timestamp(game.day),
                                "opponent_team_id": opponent,
                                "is_home": is_home,
                                "is_neutral_site": False,
                                "won": won,
                                "minutes": 240,
                                **dict.fromkeys(_BOX, 0),
                                "pts": 100 if won else 95,
                                "opp_pts": 95 if won else 100,
                            }
                        )
        frame = pd.DataFrame(rows, columns=list(TEAM_GAMES.column_names))
        return conform_frame(frame, TEAM_GAMES)

    def _playoff_results(self, years: list[int]) -> pd.DataFrame:
        rows = []
        for year in years:
            postseason = self.postseasons.get(year)
            if postseason is None:
                continue
            label = Season(year).label
            for series in postseason.series:
                rows.append(
                    {
                        "season": label,
                        "series_id": f"{label}-{series.playoff_round}-{series.team_a}-{series.team_b}",
                        "round": series.playoff_round,
                        "round_name": ROUND_NAMES[series.playoff_round - 1],
                        "team_a_id": series.team_a,
                        "team_b_id": series.team_b,
                        "team_a_wins": series.a_wins,
                        "team_b_wins": series.b_wins,
                        "games_played": len(series.games),
                        "best_of": len(PLAYOFF_PATTERN),
                        "is_complete": True,
                        "winner_team_id": series.winner,
                        "loser_team_id": series.loser,
                        "start_date": pd.Timestamp(series.games[0].day),
                        "end_date": pd.Timestamp(series.games[-1].day),
                    }
                )
        frame = pd.DataFrame(rows, columns=list(PLAYOFF_RESULTS.column_names))
        return conform_frame(frame, PLAYOFF_RESULTS)


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
