"""The postseason model: what is specified before looking, and what a fit writes down.

Two models share one file. The *series model* says how likely one side is to win a
playoff series from the gap in regular-season net rating, the gap in the quality of each
side's best three players, and home court: a game-level logistic carried through the
series format. The *season model* says, for a team of a given strength before the
bracket is known, how likely each stage of the postseason is: a chain of conditional
steps, the roadmap's hierarchy. Both were tested on seasons they had not seen; the
evaluation is kept beside the parameters, so that every probability shown can be read
against how such probabilities have come out.

Like the value model, the file (``configs/models/postseason.json``) is written only by
``fol playoffs fit --write`` and read by the services; nothing fits inside a page.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, PositiveInt, field_validator, model_validator

from front_office.domain.seasons import Season
from front_office.domain.stages import BRACKET_STAGE_KEYS

FIRST_ROUND, SEMIFINALS, CONFERENCE_FINALS, FINALS = 1, 2, 3, 4
ROUNDS = (FIRST_ROUND, SEMIFINALS, CONFERENCE_FINALS, FINALS)
DEFAULT_PATTERN = "2-2-1-1-1"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def home_pattern(name: str) -> tuple[bool, ...]:
    """The home sequence a format name stands for: ``2-2-1-1-1`` is two games at the
    home-court side's arena, two away, then one of each. Blocks alternate, starting at
    home, and the series is the best of their total."""
    try:
        blocks = [int(part) for part in name.split("-")]
    except ValueError:
        raise ValueError(f"not a series format: {name!r} (expected e.g. '2-2-1-1-1')") from None
    if not blocks or any(block <= 0 for block in blocks) or sum(blocks) % 2 == 0:
        raise ValueError(f"a series format needs positive blocks adding to an odd length: {name!r}")
    pattern: list[bool] = []
    for position, block in enumerate(blocks):
        pattern.extend([position % 2 == 0] * block)
    return tuple(pattern)


class FormatRule(_Frozen):
    """A series format that applied to one round through a season: before that season
    (inclusive) the round was played in this pattern, afterwards in the default."""

    round: int = Field(ge=FIRST_ROUND, le=FINALS)
    through_season: str
    pattern: str

    @field_validator("through_season")
    @classmethod
    def _season_label(cls, value: str) -> str:
        return Season.parse(value).label

    @field_validator("pattern")
    @classmethod
    def _known_pattern(cls, value: str) -> str:
        home_pattern(value)
        return value


class PostseasonSpec(_Frozen):
    """How the model is fitted and tested: the choices made before looking."""

    first_test_season: str = "2006-07"
    """First season the model is scored on with only earlier seasons to learn from."""
    min_training_seasons: PositiveInt = 5
    top_players: PositiveInt = 3
    """How many of a team's best players, by the value model's impact, make its
    top-player quality: the mean of their impacts."""
    experience_seasons: PositiveInt = 3
    """How many previous seasons a player's playoff games count toward a team's
    experience - a candidate input, tested and reported."""
    neutral_postseasons: tuple[str, ...] = ("2019-20",)
    """Postseasons played with nobody at home: the 2020 bubble."""
    formats: tuple[FormatRule, ...] = (
        FormatRule(round=FIRST_ROUND, through_season="2001-02", pattern="2-2-1"),
        FormatRule(round=FINALS, through_season="2012-13", pattern="2-3-2"),
    )
    default_pattern: str = DEFAULT_PATTERN
    reliability_edges: tuple[float, ...] = (0.0, 0.05, 0.1, 0.2, 0.35, 0.5, 0.65, 0.8, 1.0)
    """Where predicted probabilities are grouped to compare them with what happened. A
    grouping, not a threshold."""
    resamples: PositiveInt = 2000
    kept_draws: PositiveInt = 200
    """How many resampled parameter sets the file keeps, for intervals on any probability."""
    seed: int = 0
    confidence: float = Field(default=0.95, gt=0.5, lt=1)

    @field_validator("first_test_season")
    @classmethod
    def _season_label(cls, value: str) -> str:
        return Season.parse(value).label

    @field_validator("neutral_postseasons")
    @classmethod
    def _season_labels(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(Season.parse(label).label for label in value)

    @field_validator("default_pattern")
    @classmethod
    def _known_pattern(cls, value: str) -> str:
        home_pattern(value)
        return value

    @field_validator("reliability_edges")
    @classmethod
    def _ascending_edges(cls, value: tuple[float, ...]) -> tuple[float, ...]:
        edges = tuple(float(edge) for edge in value)
        if len(edges) < 2 or edges[0] != 0.0 or edges[-1] != 1.0:
            raise ValueError("reliability_edges must run from 0 to 1")
        if any(b <= a for a, b in zip(edges, edges[1:], strict=False)):
            raise ValueError("reliability_edges must ascend")
        return edges

    @model_validator(mode="after")
    def _draws_fit_in_resamples(self) -> PostseasonSpec:
        if self.kept_draws > self.resamples:
            raise ValueError("kept_draws cannot exceed resamples")
        return self

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(self.model_dump(), sort_keys=True).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()[:12]

    def pattern_for(self, playoff_round: int, season: str) -> str:
        """The format a round was played in that season."""
        year = Season.parse(season).start_year
        for rule in self.formats:
            if rule.round == playoff_round and year <= Season.parse(rule.through_season).start_year:
                return rule.pattern
        return self.default_pattern

    def is_neutral(self, season: str) -> bool:
        return Season.parse(season).label in self.neutral_postseasons


# --- parameters ----------------------------------------------------------------------------


class Draw(_Frozen):
    """One resampled parameter set: the same three numbers, fitted to seasons drawn
    with replacement."""

    home: float
    net_rating: float
    top_players: float


class GameModel(_Frozen):
    """One playoff game: the log-odds that the home side wins are ``home_advantage`` plus
    ``net_rating`` per point of the gap in regular-season net rating plus
    ``top_players`` per point of the gap in top-player quality. On neutral ground the
    home advantage is nothing."""

    home_advantage: float
    home_low: float
    home_high: float
    net_rating: float
    net_low: float
    net_high: float
    top_players: float
    top_low: float
    top_high: float
    games: int
    draws: tuple[Draw, ...]

    def home_court_chance(self) -> float:
        """How often the home side wins a game between two sides equal on both inputs:
        the home advantage read back from log-odds."""
        return 1.0 / (1.0 + math.exp(-self.home_advantage))


class EraParameters(_Frozen):
    """The game model fitted to one era alone, to show how its parameters have moved."""

    key: str
    label: str
    first_season: str
    last_season: str
    games: int
    home_advantage: float
    net_rating: float
    top_players: float


class StepDraw(_Frozen):
    intercept: float
    net_rating: float
    top_players: float


class Step(_Frozen):
    """One step of the season model: the chance of reaching ``key`` for a team that
    reached ``from_key`` (every team, for the first step), as a logistic in net rating
    and top-player quality."""

    key: str
    from_key: str | None
    intercept: float
    net_rating: float
    net_low: float
    net_high: float
    top_players: float
    top_low: float
    top_high: float
    teams: int
    reached: int
    draws: tuple[StepDraw, ...]


class TypicalTop(_Frozen):
    """What a team's top-player quality has typically been at a net rating: a line, used
    only to fill the second input when a reader gives the first alone."""

    slope: float
    intercept: float

    def at(self, net_rating: float) -> float:
        return self.intercept + self.slope * net_rating


# --- the evaluation ------------------------------------------------------------------------


class Calibration(_Frozen):
    """Outcomes regressed on the model's log-odds, out of sample: a slope of 1 and an
    intercept of 0 is a model whose probabilities mean what they say; a slope below 1
    is one too sure of itself at the extremes."""

    slope: float
    intercept: float


class Baseline(_Frozen):
    """A simpler method scored on the same cases."""

    key: str
    label: str
    log_loss: float
    brier: float


class Comparison(_Frozen):
    """An alternative that was tried, scored on the same cases as the model, with the
    difference in log loss (alternative less model: negative is better) and its interval
    from resampling seasons."""

    key: str
    label: str
    log_loss: float
    brier: float
    difference: float
    low: float
    high: float

    @property
    def is_clearly_better(self) -> bool:
        return self.high < 0

    @property
    def is_clearly_worse(self) -> bool:
        return self.low > 0


class ReliabilityBin(_Frozen):
    """Cases whose predicted probability fell in one band: what was predicted on average
    and what happened, with the interval a share of that many cases carries."""

    lower: float
    upper: float
    cases: int
    predicted: float
    observed: float
    low: float
    high: float


class StageEvaluation(_Frozen):
    key: str
    cases: int
    reached: int
    mean_probability: float
    log_loss: float
    brier: float
    calibration: Calibration
    baselines: tuple[Baseline, ...]


class RoundEvaluation(_Frozen):
    round: int
    series: int
    home_side_won: int
    """How many series the home-court side won."""
    favourite_won: int
    """How many series the side the model favoured won."""
    mean_probability: float
    log_loss: float
    brier: float


class SpanEvaluation(_Frozen):
    """The series model scored on one era's series, out of sample."""

    key: str
    label: str
    first_season: str
    last_season: str
    series: int
    log_loss: float
    brier: float
    calibration: Calibration


class SeriesEvaluation(_Frozen):
    first_test_season: str
    last_test_season: str
    series: int
    home_side_won: int
    favourite_won: int
    log_loss: float
    brier: float
    calibration: Calibration
    baselines: tuple[Baseline, ...]
    comparisons: tuple[Comparison, ...]
    reliability: tuple[ReliabilityBin, ...]
    by_round: tuple[RoundEvaluation, ...]
    by_era: tuple[SpanEvaluation, ...]


class SeasonFavourite(_Frozen):
    """One postseason: whom the model favoured for the title before it began, and who
    won it."""

    season: str
    favourite_team_id: int
    favourite_probability: float
    champion_team_id: int
    champion_probability: float

    @property
    def favourite_won(self) -> bool:
        return self.favourite_team_id == self.champion_team_id


class BracketEvaluation(_Frozen):
    """The series model carried through each season's actual bracket before a game was
    played, scored on where every playoff team got to."""

    team_postseasons: int
    stages: tuple[StageEvaluation, ...]
    reliability: tuple[ReliabilityBin, ...]
    favourites: tuple[SeasonFavourite, ...]

    @property
    def favourite_won(self) -> int:
        return sum(item.favourite_won for item in self.favourites)


class SeasonEvaluation(_Frozen):
    """The season model scored on every team-season, out of sample."""

    team_seasons: int
    stages: tuple[StageEvaluation, ...]
    reliability: tuple[ReliabilityBin, ...]
    comparisons: tuple[Comparison, ...]


class BeforeSeasonEvaluation(_Frozen):
    """The season model read the way a forecast reads it: from the net rating the value
    model predicted for each team-season before it was played, averaged over that
    prediction's error, with the top-player quality typical of such a rating. Scored out
    of sample on the team-seasons the value model's own test covers, with the steps and
    the typical quality fitted on earlier seasons."""

    team_seasons: int
    first_test_season: str
    last_test_season: str
    rating_basis: str
    """``"projected"`` where the rating came from the value model's test with the minutes
    projected, else ``"played"``."""
    rating_error: float
    """The error the ratings carry, which the chances are averaged over."""
    stages: tuple[StageEvaluation, ...]


class Evaluation(_Frozen):
    series: SeriesEvaluation
    bracket: BracketEvaluation
    season: SeasonEvaluation
    before_season: BeforeSeasonEvaluation | None = None
    """Missing in files fitted before it existed, or without a value model test to read."""


class FittedOn(_Frozen):
    first_season: str
    last_season: str
    seasons: int
    playoff_games: int
    series: int
    team_seasons: int


class PostseasonModel(_Frozen):
    """The fitted postseason model: the series model, the season model, and the evidence."""

    revision: PositiveInt
    fitted_at: datetime
    spec: PostseasonSpec
    value_model_version: str
    """The value model whose impacts made every team's top-player quality."""
    fitted_on: FittedOn
    game: GameModel
    by_era: tuple[EraParameters, ...]
    steps: tuple[Step, ...]
    typical_top: TypicalTop
    evaluation: Evaluation

    @field_validator("steps")
    @classmethod
    def _the_bracket_stages_in_order(cls, value: tuple[Step, ...]) -> tuple[Step, ...]:
        keys = tuple(step.key for step in value)
        if keys != BRACKET_STAGE_KEYS:
            raise ValueError(f"the season model's steps must be {BRACKET_STAGE_KEYS}, not {keys}")
        return value

    @property
    def version(self) -> str:
        """What anything computed with this model is stamped with."""
        return f"p{self.revision}"

    def step(self, key: str) -> Step:
        for step in self.steps:
            if step.key == key:
                return step
        raise KeyError(f"no step named {key!r}; known: {[step.key for step in self.steps]}")
