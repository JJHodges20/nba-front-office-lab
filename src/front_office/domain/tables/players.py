"""Data contracts for the player and player-performance domains."""

from __future__ import annotations

from front_office.domain.schema import DType, Field, Provenance, TableContract
from front_office.domain.tables import _fields as f

_PLAYER_NAME = f.label("player_name", "Player name as the source listed it.", nullable=False)


def _size_fields() -> tuple[Field, ...]:
    return (
        f.label("position", "Listed position: G, F, C or a combination such as G-F."),
        Field(
            "height_inches", DType.INTEGER, "Listed height.", unit="inches", minimum=60, maximum=96
        ),
        Field(
            "weight_lbs", DType.INTEGER, "Listed weight.", unit="pounds", minimum=100, maximum=400
        ),
    )


PLAYERS = TableContract(
    name="players",
    domain="players",
    description="Everyone who has played in the league: identity and profile fields.",
    grain="One row per player.",
    fields=(
        Field(
            "player_id",
            DType.INTEGER,
            "Player id assigned by the league.",
            nullable=False,
            provenance=Provenance.IDENTIFIER,
        ),
        f.label("full_name", "First and last name.", nullable=False),
        f.label("first_name", "First name. Null for players known by a single name."),
        f.label("last_name", "Last name.", nullable=False),
        *_size_fields(),
        Field(
            "birth_date",
            DType.DATE,
            "Date of birth. Known only for players who appear on an ingested roster.",
        ),
        f.label("country", "Country."),
        f.label("college", "College or last team before the NBA."),
        f.count("draft_year", "Year drafted. Null if undrafted.", nullable=True),
        f.count("draft_round", "Draft round. Null if undrafted.", nullable=True),
        f.count("draft_number", "Overall pick number. Null if undrafted.", nullable=True),
        f.count(
            "first_season_year", "Calendar year the player's first season began.", nullable=True
        ),
        f.count(
            "last_season_year",
            "Calendar year the player's most recent season began.",
            nullable=True,
        ),
        Field("is_active", DType.BOOLEAN, "Whether the player is on a roster now.", nullable=False),
        f.team_id(
            "current_team_id", "Team the player is on now. Null if not on a roster.", nullable=True
        ),
    ),
    primary_key=("player_id",),
    indexes=(("current_team_id",),),
)

PLAYER_SEASONS = TableContract(
    name="player_seasons",
    domain="player_performance",
    description=(
        "Each player's season totals with the league's on-court measurements. A player "
        "traded mid-season has one row covering every team played for."
    ),
    grain="One row per player per season per season type.",
    fields=(
        f.player_id(),
        f.season(),
        f.season_type(),
        _PLAYER_NAME,
        f.team_id(description="Team the player finished the season with."),
        f.count("team_count", "Number of teams the player appeared for."),
        Field("age", DType.INTEGER, "Age during the season.", unit="years", minimum=15, maximum=60),
        f.count("games_played", "Games played."),
        f.count("games_started", "Games started.", nullable=True),
        f.count("wins", "Team wins in games the player appeared in."),
        f.count("losses", "Team losses in games the player appeared in."),
        Field("minutes", DType.FLOAT, "Minutes played.", nullable=False, unit="minutes", minimum=0),
        *f.box_score(),
        f.count("blocked_attempts", "Field goal attempts by the player that were blocked."),
        f.count("fouls_drawn", "Personal fouls drawn."),
        Field("plus_minus", DType.INTEGER, "Team point margin while the player was on the court."),
        f.count("double_doubles", "Double-doubles."),
        f.count("triple_doubles", "Triple-doubles."),
        f.count(
            "possessions", "Team possessions while the player was on the court.", nullable=True
        ),
        f.rating("off_rating", "Team points per 100 possessions with the player on the court."),
        f.rating("def_rating", "Opponent points per 100 possessions with the player on the court."),
        f.rating("net_rating", "On-court offensive minus defensive rating."),
        f.share("usage_pct", "Share of team plays used by the player while on the court."),
        f.share(
            "assist_pct", "Share of teammates' field goals the player assisted while on the court."
        ),
        f.share(
            "oreb_pct", "Share of available offensive rebounds the player took while on the court."
        ),
        f.share(
            "dreb_pct", "Share of available defensive rebounds the player took while on the court."
        ),
        f.share("reb_pct", "Share of available rebounds the player took while on the court."),
        Field(
            "pace",
            DType.FLOAT,
            "Team possessions per 48 minutes with the player on the court.",
            unit="possessions per 48 minutes",
            minimum=0,
        ),
        Field(
            "player_impact_estimate",
            DType.FLOAT,
            "The league's PIE: the player's share of the game events in games played.",
            unit="fraction",
        ),
    ),
    primary_key=("player_id", "season", "season_type"),
    indexes=(("season", "season_type"), ("team_id", "season")),
)

PLAYER_GAME_LOGS = TableContract(
    name="player_game_logs",
    domain="player_performance",
    description="Each player's box score for each game played.",
    grain="One row per player per game.",
    fields=(
        f.player_id(),
        f.game_id(),
        f.season(),
        f.season_type(),
        Field("game_date", DType.DATE, "Date the game was played.", nullable=False),
        f.team_id(description="Team the player appeared for."),
        f.team_id("opponent_team_id", "The other team in the game."),
        Field(
            "is_home",
            DType.BOOLEAN,
            "Whether the player's team played at home. False at a neutral site.",
            nullable=False,
        ),
        Field(
            "is_neutral_site",
            DType.BOOLEAN,
            "Whether the game was played at a neutral site, with neither team at home.",
            nullable=False,
        ),
        Field(
            "won", DType.BOOLEAN, "Whether the player's team won. Null if the game is unfinished."
        ),
        f.count(
            "minutes", "Minutes played, rounded to the whole minute by the source.", unit="minutes"
        ),
        *f.box_score(),
        Field("plus_minus", DType.INTEGER, "Team point margin while the player was on the court."),
    ),
    primary_key=("player_id", "game_id"),
    indexes=(("season", "season_type"), ("player_id", "game_date"), ("game_id", "team_id")),
)

TEAM_ROSTERS = TableContract(
    name="team_rosters",
    domain="players",
    description=(
        "Roster membership as the league lists it for a season: the final roster of a "
        "finished season, or the roster as of the fetch for the current league year."
    ),
    grain="One row per player per team per season.",
    fields=(
        f.season(),
        f.team_id(),
        f.player_id(),
        _PLAYER_NAME,
        f.label("jersey_number", "Jersey number; text because 0 and 00 are different numbers."),
        *_size_fields(),
        Field("birth_date", DType.DATE, "Date of birth."),
        f.count(
            "experience_years",
            "Completed NBA seasons; 0 for a rookie.",
            nullable=True,
            unit="years",
        ),
        f.label("school", "College or last team before the NBA."),
        f.label("how_acquired", "How the team acquired the player, as the league describes it."),
    ),
    primary_key=("season", "team_id", "player_id"),
    indexes=(("player_id",),),
)

PLAYER_ON_OFF = TableContract(
    name="player_on_off",
    domain="player_performance",
    description="A team's ratings with each player on the court and off it.",
    grain="One row per player per team per season per season type.",
    fields=(
        f.player_id(),
        f.season(),
        f.season_type(),
        f.team_id(),
        Field(
            "on_court_minutes",
            DType.FLOAT,
            "Minutes the player was on the court.",
            unit="minutes",
            minimum=0,
        ),
        f.rating("on_court_off_rating", "Team offensive rating with the player on the court."),
        f.rating("on_court_def_rating", "Team defensive rating with the player on the court."),
        f.rating("on_court_net_rating", "Team net rating with the player on the court."),
        Field(
            "off_court_minutes",
            DType.FLOAT,
            "Minutes the team played without the player.",
            unit="minutes",
            minimum=0,
        ),
        f.rating("off_court_off_rating", "Team offensive rating with the player off the court."),
        f.rating("off_court_def_rating", "Team defensive rating with the player off the court."),
        f.rating("off_court_net_rating", "Team net rating with the player off the court."),
    ),
    primary_key=("player_id", "season", "season_type", "team_id"),
    indexes=(("season", "team_id"),),
)

TABLES: tuple[TableContract, ...] = (
    PLAYERS,
    PLAYER_SEASONS,
    PLAYER_GAME_LOGS,
    TEAM_ROSTERS,
    PLAYER_ON_OFF,
)
