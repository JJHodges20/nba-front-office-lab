"""The postseason model: a series model carried through the bracket, and a season model
for a team's chances before the bracket is known - fitted on request and tested out of
sample."""

from front_office.modeling.postseason.bracket import (
    ENTRANTS,
    STANDARD_SLOTS,
    Bracket,
    BracketError,
    BracketOdds,
    Pair,
    bracket_from_series,
    holds_home_court,
    propagate,
    standard_bracket,
)
from front_office.modeling.postseason.catalog import (
    POSTSEASON_METRICS,
    SERIES_PROBABILITY,
    TOP_PLAYERS,
    probability_key,
)
from front_office.modeling.postseason.features import (
    FEATURE_TABLES,
    GAPS,
    TEAM_COLUMNS,
    head_to_head,
    keyed,
    pattern_for,
    playoff_games,
    series_table,
    team_features,
)
from front_office.modeling.postseason.fit import (
    SEASON_ALTERNATIVES,
    SERIES_ALTERNATIVES,
    UNIFORM,
    NotEnoughHistory,
    fit_postseason_model,
)
from front_office.modeling.postseason.hierarchy import (
    STEP_COLUMNS,
    stage_probabilities,
    step_weights,
)
from front_office.modeling.postseason.series import (
    GAME_COLUMNS,
    fit_game_model,
    game_probabilities,
    predict_series,
    series_probability,
    series_win_probability,
)

__all__ = [
    "ENTRANTS",
    "FEATURE_TABLES",
    "GAME_COLUMNS",
    "GAPS",
    "POSTSEASON_METRICS",
    "SEASON_ALTERNATIVES",
    "SERIES_ALTERNATIVES",
    "SERIES_PROBABILITY",
    "STANDARD_SLOTS",
    "STEP_COLUMNS",
    "TEAM_COLUMNS",
    "TOP_PLAYERS",
    "UNIFORM",
    "Bracket",
    "BracketError",
    "BracketOdds",
    "NotEnoughHistory",
    "Pair",
    "bracket_from_series",
    "fit_game_model",
    "fit_postseason_model",
    "game_probabilities",
    "head_to_head",
    "holds_home_court",
    "keyed",
    "pattern_for",
    "playoff_games",
    "predict_series",
    "probability_key",
    "propagate",
    "series_probability",
    "series_table",
    "series_win_probability",
    "stage_probabilities",
    "standard_bracket",
    "step_weights",
    "team_features",
]
