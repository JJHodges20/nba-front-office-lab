"""Data contracts for the team domain and historical outcomes."""

from __future__ import annotations

from front_office.domain.schema import DType, Field, Provenance, TableContract
from front_office.domain.tables import _fields as f

ROUND_NAMES = ("First Round", "Conference Semifinals", "Conference Finals", "NBA Finals")

TEAMS = TableContract(
    name="teams",
    domain="teams",
    description="The thirty current franchises. A franchise keeps its id when it relocates or is renamed.",
    grain="One row per active franchise.",
    fields=(
        Field(
            "team_id",
            DType.INTEGER,
            "Franchise id assigned by the league.",
            nullable=False,
            provenance=Provenance.IDENTIFIER,
        ),
        f.label("abbreviation", "Current three-letter abbreviation.", nullable=False),
        f.label("city", "Current city or region name.", nullable=False),
        f.label("nickname", "Current nickname, e.g. Celtics.", nullable=False),
        f.label("full_name", "City and nickname.", nullable=False),
        f.label("conference", "Current conference.", nullable=False, allowed=f.CONFERENCES),
        f.label("division", "Current division.", nullable=False),
        f.count(
            "first_season_year", "Calendar year the franchise's first season began.", nullable=True
        ),
    ),
    primary_key=("team_id",),
)

_OUTCOME_NOTE = " Null until the season's postseason is complete."

TEAM_SEASONS = TableContract(
    name="team_seasons",
    domain="teams",
    description=(
        "Regular-season performance of each team with its postseason outcome: the "
        "team-season dataset that historical benchmark research is built on."
    ),
    grain="One row per team per season (regular season).",
    fields=(
        f.season(),
        f.team_id(),
        f.label("team_name", "Team name as it was that season.", nullable=False),
        f.label("team_abbreviation", "Abbreviation as it was that season."),
        f.label("conference", "Conference that season.", allowed=f.CONFERENCES),
        f.label("division", "Division that season."),
        Field(
            "conference_rank",
            DType.INTEGER,
            "Final position in the conference standings.",
            minimum=1,
            maximum=15,
        ),
        f.count("games_played", "Regular-season games played."),
        f.count("wins", "Regular-season wins."),
        f.count("losses", "Regular-season losses."),
        Field(
            "minutes",
            DType.FLOAT,
            "Game minutes played, overtime included (48 per regulation game).",
            nullable=False,
            unit="minutes",
            minimum=0,
        ),
        *f.box_score(),
        *f.box_score("opp_", "by opponents"),
        f.count("possessions", "Possessions, counted by the league from play-by-play."),
        Field(
            "pace",
            DType.FLOAT,
            "Possessions per 48 minutes, as published by the league.",
            nullable=False,
            unit="possessions per 48 minutes",
            minimum=0,
        ),
        f.rating(
            "off_rating",
            "Points scored per 100 possessions, as published by the league.",
            nullable=False,
        ),
        f.rating(
            "def_rating",
            "Points allowed per 100 possessions, as published by the league.",
            nullable=False,
        ),
        f.rating(
            "net_rating",
            "Offensive minus defensive rating, as published by the league.",
            nullable=False,
        ),
        Field(
            "made_play_in",
            DType.BOOLEAN,
            "Played in the play-in tournament." + _OUTCOME_NOTE,
            provenance=Provenance.DERIVED,
        ),
        Field(
            "made_playoffs",
            DType.BOOLEAN,
            "Played at least one playoff game." + _OUTCOME_NOTE,
            provenance=Provenance.DERIVED,
        ),
        Field(
            "playoff_round_reached",
            DType.INTEGER,
            "Furthest playoff round played: 0 none, 1 first round, 2 conference semifinals, "
            "3 conference finals, 4 NBA Finals." + _OUTCOME_NOTE,
            provenance=Provenance.DERIVED,
            minimum=0,
            maximum=4,
        ),
        Field(
            "playoff_series_won",
            DType.INTEGER,
            "Playoff series won." + _OUTCOME_NOTE,
            provenance=Provenance.DERIVED,
            minimum=0,
            maximum=4,
        ),
        Field(
            "playoff_wins",
            DType.INTEGER,
            "Playoff games won." + _OUTCOME_NOTE,
            provenance=Provenance.DERIVED,
            minimum=0,
        ),
        Field(
            "playoff_losses",
            DType.INTEGER,
            "Playoff games lost." + _OUTCOME_NOTE,
            provenance=Provenance.DERIVED,
            minimum=0,
        ),
        Field(
            "made_conference_finals",
            DType.BOOLEAN,
            "Reached the conference finals." + _OUTCOME_NOTE,
            provenance=Provenance.DERIVED,
        ),
        Field(
            "made_finals",
            DType.BOOLEAN,
            "Reached the NBA Finals." + _OUTCOME_NOTE,
            provenance=Provenance.DERIVED,
        ),
        Field(
            "won_championship",
            DType.BOOLEAN,
            "Won the NBA championship." + _OUTCOME_NOTE,
            provenance=Provenance.DERIVED,
        ),
    ),
    primary_key=("season", "team_id"),
    indexes=(("team_id",),),
)

TEAM_GAMES = TableContract(
    name="team_games",
    domain="teams",
    description="Each team's box score for each game: regular season, play-in and playoffs.",
    grain="One row per team per game (two rows per game).",
    fields=(
        f.game_id(),
        f.team_id(),
        f.season(),
        f.season_type(),
        Field("game_date", DType.DATE, "Date the game was played.", nullable=False),
        f.team_id("opponent_team_id", "The other team in the game."),
        Field(
            "is_home",
            DType.BOOLEAN,
            "Whether the team played at home. False for both teams at a neutral site.",
            nullable=False,
        ),
        Field(
            "is_neutral_site",
            DType.BOOLEAN,
            "Whether the game was played at a neutral site, with neither team at home.",
            nullable=False,
        ),
        Field("won", DType.BOOLEAN, "Whether the team won. Null if the game is unfinished."),
        f.count(
            "minutes",
            "Player-minutes credited to the team (240 in regulation, 25 more per overtime).",
            unit="player-minutes",
        ),
        *f.box_score(),
        f.count("opp_pts", "Points scored by the opponent."),
    ),
    primary_key=("game_id", "team_id"),
    indexes=(("season", "season_type"), ("team_id", "game_date")),
)

PLAYOFF_RESULTS = TableContract(
    name="playoff_results",
    domain="historical_outcomes",
    description="Every playoff series, derived from game results.",
    grain="One row per playoff series.",
    fields=(
        f.season(),
        f.label(
            "series_id",
            "Series key: season, round and the two team ids.",
            nullable=False,
        ),
        Field(
            "round",
            DType.INTEGER,
            "Playoff round, 1 (first round) to 4 (NBA Finals).",
            nullable=False,
            provenance=Provenance.DERIVED,
            minimum=1,
            maximum=4,
        ),
        f.label("round_name", "Name of the round.", nullable=False, allowed=ROUND_NAMES),
        f.team_id("team_a_id", "The team that hosted game 1."),
        f.team_id("team_b_id", "The team that visited in game 1."),
        f.count("team_a_wins", "Games won by team A."),
        f.count("team_b_wins", "Games won by team B."),
        f.count("games_played", "Games played in the series."),
        Field(
            "best_of",
            DType.INTEGER,
            "Scheduled length of the series: 5 or 7 games.",
            nullable=False,
            minimum=5,
            maximum=7,
        ),
        Field(
            "is_complete",
            DType.BOOLEAN,
            "Whether one team has won enough games to take the series.",
            nullable=False,
            provenance=Provenance.DERIVED,
        ),
        f.team_id(
            "winner_team_id", "Series winner. Null while the series is undecided.", nullable=True
        ),
        f.team_id(
            "loser_team_id", "Series loser. Null while the series is undecided.", nullable=True
        ),
        Field("start_date", DType.DATE, "Date of the first game.", nullable=False),
        Field("end_date", DType.DATE, "Date of the most recent game.", nullable=False),
    ),
    primary_key=("season", "series_id"),
    indexes=(("season", "round"),),
)

TABLES: tuple[TableContract, ...] = (TEAMS, TEAM_SEASONS, TEAM_GAMES, PLAYOFF_RESULTS)
