"""Postseason odds for the workbench: a season's bracket and its series under the model,
every team's chance of each stage, and what a team of any strength can expect.

Everything is read off the model on file (``configs/models/postseason.json``) and the
season's tables. Nothing is fitted here. An interval on any figure comes from the
resampled parameter sets the file keeps, so that a probability is never shown without
how far it could plausibly lie from where it is drawn.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd

from front_office.analytics import teams as team_analytics
from front_office.config.models import load_postseason_model
from front_office.domain.metrics import MetricCatalog
from front_office.domain.postseason import PostseasonModel
from front_office.domain.seasons import SeasonType
from front_office.domain.stages import BRACKET_STAGE_KEYS, ROUND_STAGE_KEYS, stage
from front_office.domain.tables.players import PLAYER_GAME_LOGS
from front_office.modeling.postseason import (
    POSTSEASON_METRICS,
    BracketError,
    bracket_from_series,
    head_to_head,
    keyed,
    probability_key,
    propagate,
    series_table,
    series_win_probability,
    stage_probabilities,
    team_features,
)
from front_office.modeling.postseason.fitting import percentile_interval
from front_office.services.lab import Lab

REGULAR = SeasonType.REGULAR.value
FIT_COMMAND = "fol playoffs fit --write"
CURVE_RATINGS: tuple[float, ...] = tuple(float(value) / 2 for value in range(-20, 25))
"""Net ratings the curve is drawn at: -10 to +12 in halves."""
IDENTITY_COLUMNS = (
    "team_name",
    "abbreviation",
    "conference",
    "seed",
    "wins",
    "losses",
    "net_rating",
    "top_players",
)
BRACKET_COLUMNS = (
    *IDENTITY_COLUMNS,
    *(
        column
        for key in ROUND_STAGE_KEYS
        for column in (
            probability_key(key),
            f"{probability_key(key)}_low",
            f"{probability_key(key)}_high",
        )
    ),
    "result",
    "round_reached",
)
ODDS_COLUMNS = (
    *IDENTITY_COLUMNS,
    *(
        column
        for key in BRACKET_STAGE_KEYS
        for column in (
            probability_key(key),
            f"{probability_key(key)}_low",
            f"{probability_key(key)}_high",
        )
    ),
    "decided",
    "result",
)
SERIES_COLUMNS = (
    "round",
    "round_name",
    "conference",
    "home_team",
    "home_abbreviation",
    "home_seed",
    "visitor",
    "visitor_abbreviation",
    "visitor_seed",
    "probability",
    "low",
    "high",
    "favourite",
    "favourite_won",
    "result",
    "winner",
    "games",
)
STAGE_COLUMNS = ("key", "label", "probability", "low", "high")


class PostseasonError(RuntimeError):
    """The model on file cannot answer; the message says what is missing."""


@dataclass(frozen=True, slots=True)
class PostseasonStatus:
    revision: int | None
    """Revision of the model on file; ``None`` when none has been fitted."""
    fitted_at: datetime | None
    value_model_version: str | None
    """The value model whose impacts made every team's top-player quality when the
    model was fitted."""
    applied_value_version: str | None
    """The value model the database was built with."""
    seasons: tuple[str, ...]
    """Seasons whose postseason is decided and whose series are on record, newest first."""
    latest: str | None
    """The latest season with team statistics, decided or not."""

    @property
    def is_fitted(self) -> bool:
        return self.revision is not None

    @property
    def is_current(self) -> bool:
        """Whether the model was fitted against the value model the database now holds."""
        return self.is_fitted and self.value_model_version == self.applied_value_version


@dataclass(frozen=True, slots=True)
class BracketReport:
    """One postseason's sixteen teams with their chances before the first game."""

    season: str
    teams: pd.DataFrame
    """Indexed by ``team_id`` in bracket order: :data:`BRACKET_COLUMNS`. Empty when the
    bracket could not be read or an entrant's inputs are unknown."""
    missing: tuple[str, ...]
    """Entrants whose net rating or top-player quality is unknown."""
    note: str
    """Why there is nothing to show, when there is nothing."""
    favourite: str | None
    favourite_probability: float | None
    champion: str | None
    champion_probability: float | None

    @property
    def is_empty(self) -> bool:
        return self.teams.empty


@dataclass(frozen=True, slots=True)
class Outlook:
    """What a team of one strength can expect, before the bracket is known."""

    net_rating: float
    top_players: float
    error: float | None
    """The standard error of the net rating when it is a projection; ``None`` when the
    rating is taken as known."""
    stages: pd.DataFrame
    """One row per stage: :data:`STAGE_COLUMNS`."""


TEAM, ROSTER = "team", "roster"


@dataclass(frozen=True, slots=True)
class SubjectOutlook:
    """A real team or a built roster read as a team of some strength, with the season
    model's chances for a team like it."""

    kind: str
    """``team`` or ``roster``."""
    key: int
    name: str
    season: str
    """The season the inputs are read from."""
    net_rating: float | None
    top_players: float | None
    top_names: tuple[str, ...]
    """The players whose impacts make the top-player quality, best first."""
    error: float | None
    """The standard error carried into the chances; ``None`` when the rating is known."""
    note: str
    """How the inputs were taken - or, when there is no outlook, why."""
    outlook: Outlook | None

    @property
    def is_empty(self) -> bool:
        return self.outlook is None


class PostseasonService:
    def __init__(self, lab: Lab) -> None:
        self._lab = lab

    @property
    def metrics(self) -> MetricCatalog:
        return POSTSEASON_METRICS

    def model(self) -> PostseasonModel | None:
        """The model on file, if one has been fitted."""
        return load_postseason_model(self._lab.settings.config_dir)

    def seasons(self) -> tuple[str, ...]:
        """Seasons whose postseason is decided and on record, newest first."""
        teams = self._lab.read("team_seasons")
        decided = set(teams.loc[teams["made_playoffs"].notna(), "season"].astype(str))
        on_record = set(self._lab.warehouse.distinct("playoff_results", "season"))
        return tuple(sorted(decided & on_record, reverse=True))

    def status(self) -> PostseasonStatus:
        model = self.model()
        seasons = self._lab.warehouse.distinct("team_seasons", "season")
        return PostseasonStatus(
            revision=None if model is None else model.revision,
            fitted_at=None if model is None else model.fitted_at,
            value_model_version=None if model is None else model.value_model_version,
            applied_value_version=self._lab.value.status().applied_revision,
            seasons=self.seasons(),
            latest=max(seasons) if seasons else None,
        )

    # --- a season --------------------------------------------------------------------------

    def bracket(self, season: str) -> BracketReport:
        """The season's playoff teams and their chances of each round, as the model would
        have put them before the first playoff game, beside where they got to."""
        model = self._require()
        tables = self._season_tables(season)
        features = team_features(tables, model.spec)
        series = series_table(tables, features, model.spec)
        series = series[series["season"] == season]
        empty = pd.DataFrame(columns=list(BRACKET_COLUMNS)).rename_axis("team_id")
        if series.empty:
            return BracketReport(
                season,
                empty,
                (),
                f"No playoff series are on record for {season}.",
                None,
                None,
                None,
                None,
            )
        try:
            bracket = bracket_from_series(series)
        except BracketError:
            return BracketReport(
                season,
                empty,
                (),
                f"The {season} postseason is not complete, so its bracket cannot be read yet.",
                None,
                None,
                None,
                None,
            )
        teams = keyed(features).loc[season]
        names = self._lab.team_labels()
        lacking = [
            team
            for team in bracket.entrants
            if team not in teams.index
            or not np.isfinite(teams.at[team, "net_rating"])
            or not np.isfinite(teams.at[team, "top_players"])
        ]
        if lacking:
            missing = tuple(str(names["full_name"].get(team, f"Team {team}")) for team in lacking)
            return BracketReport(
                season,
                empty,
                missing,
                "The model needs every entrant's net rating and top-player quality, and "
                f"{len(missing)} of the sixteen have no players the value model scored.",
                None,
                None,
                None,
                None,
            )
        home, net, top = self._parameters(model)
        odds = propagate(
            bracket,
            teams,
            home,
            net,
            top,
            spec=model.spec,
            head_to_head=head_to_head(tables["team_games"]),
        )
        rows = teams.loc[list(bracket.entrants)]
        frame = self._identity(rows, names)
        for key in ROUND_STAGE_KEYS:
            values = odds.by_stage[key]
            column = probability_key(key)
            frame[column] = values[:, 0]
            frame[f"{column}_low"], frame[f"{column}_high"] = self._bounds(values, model)
        frame["result"] = team_analytics.postseason_result(
            tables["team_seasons"].set_index("team_id").loc[frame.index]
        ).to_numpy()
        frame["round_reached"] = rows["round_reached"].to_numpy()
        frame = frame[list(BRACKET_COLUMNS)]
        title = probability_key("won_championship")
        favourite = frame[title].idxmax()
        champions = frame.index[rows["won_championship"].to_numpy().astype(bool)]
        champion = int(champions[0]) if len(champions) else None
        return BracketReport(
            season,
            frame,
            (),
            "",
            str(frame.at[favourite, "team_name"]),
            float(frame.at[favourite, title]),
            None if champion is None else str(frame.at[champion, "team_name"]),
            None if champion is None else float(frame.at[champion, title]),
        )

    def series(self, season: str) -> pd.DataFrame:
        """Every decided series of the season in bracket order, with the model's chance for
        the side that held home court and what happened: :data:`SERIES_COLUMNS`."""
        model = self._require()
        tables = self._season_tables(season)
        features = team_features(tables, model.spec)
        series = series_table(tables, features, model.spec)
        series = series[series["season"] == season].reset_index(drop=True)
        if series.empty:
            return pd.DataFrame(columns=list(SERIES_COLUMNS))
        home, net, top = self._parameters(model)
        estimate = np.full(len(series), np.nan)
        low = np.full(len(series), np.nan)
        high = np.full(len(series), np.nan)
        for position, row in enumerate(series.itertuples(index=False)):
            if not (np.isfinite(row.net_rating_diff) and np.isfinite(row.top_players_diff)):
                continue
            values = np.asarray(
                series_win_probability(
                    home,
                    net,
                    top,
                    float(row.net_rating_diff),
                    float(row.top_players_diff),
                    pattern=row.pattern,
                    neutral=bool(row.neutral),
                )
            )
            estimate[position] = values[0]
            low[position], high[position] = percentile_interval(values[1:], model.spec.confidence)
        labels = self._lab.team_labels()
        names, short = labels["full_name"], labels["abbreviation"]
        teams = keyed(features).loc[season]
        results = tables["playoff_results"].set_index("series_id")
        conference_a = series["team_a_id"].map(teams["conference"])
        conference_b = series["team_b_id"].map(teams["conference"])
        home_team = series["team_a_id"].map(names)
        visitor = series["team_b_id"].map(names)
        favoured_home = estimate >= 0.5
        frame = pd.DataFrame(
            {
                "round": series["round"],
                "round_name": series["series_id"].map(results["round_name"]),
                "conference": conference_a.where(conference_a == conference_b),
                "home_team": home_team,
                "home_abbreviation": series["team_a_id"].map(short),
                "home_seed": series["team_a_id"].map(teams["conference_rank"]),
                "visitor": visitor,
                "visitor_abbreviation": series["team_b_id"].map(short),
                "visitor_seed": series["team_b_id"].map(teams["conference_rank"]),
                "probability": estimate,
                "low": low,
                "high": high,
                "favourite": np.where(
                    np.isnan(estimate), None, np.where(favoured_home, home_team, visitor)
                ),
                "favourite_won": np.where(
                    np.isnan(estimate), None, favoured_home == (series["a_won"].to_numpy() == 1)
                ),
                "result": series["team_a_wins"].astype(str)
                + "-"
                + series["team_b_wins"].astype(str),
                "winner": np.where(series["a_won"] == 1, home_team, visitor),
                "games": series["team_a_wins"] + series["team_b_wins"],
            }
        )
        return frame[list(SERIES_COLUMNS)]

    def season_odds(self, season: str) -> pd.DataFrame:
        """Every team of the season under the season model - its chance of each stage
        from its net rating and top-player quality alone, as a team of that strength
        entering any season - with what happened: :data:`ODDS_COLUMNS`, best first."""
        model = self._require()
        tables = self._season_tables(season)
        features = keyed(team_features(tables, model.spec)).loc[season]
        names = self._lab.team_labels()
        frame = self._identity(features, names)
        known = np.isfinite(features["net_rating"].to_numpy(dtype="float64")) & np.isfinite(
            features["top_players"].to_numpy(dtype="float64")
        )
        for key in BRACKET_STAGE_KEYS:
            column = probability_key(key)
            frame[column] = np.nan
            frame[f"{column}_low"] = np.nan
            frame[f"{column}_high"] = np.nan
        for team, flag in zip(features.index, known, strict=True):
            if not flag:
                continue
            outlook = self.outlook(
                float(features.at[team, "net_rating"]), float(features.at[team, "top_players"])
            ).stages.set_index("key")
            for key in BRACKET_STAGE_KEYS:
                column = probability_key(key)
                frame.at[team, column] = outlook.at[key, "probability"]
                frame.at[team, f"{column}_low"] = outlook.at[key, "low"]
                frame.at[team, f"{column}_high"] = outlook.at[key, "high"]
        frame["decided"] = features["decided"].to_numpy()
        frame["result"] = team_analytics.postseason_result(
            tables["team_seasons"].set_index("team_id").loc[frame.index]
        ).to_numpy()
        ordered = frame.sort_values(
            [probability_key("won_championship"), "net_rating"], ascending=[False, False]
        )
        return ordered[list(ODDS_COLUMNS)]

    # --- any team -----------------------------------------------------------------------------

    def outlook(
        self, net_rating: float, top_players: float | None = None, *, error: float | None = None
    ) -> Outlook:
        """A team of this strength: its chance of each stage with an interval. Without
        ``top_players`` the quality typical of teams at that rating is taken. With
        ``error`` the rating is a projection, and the chances are averaged over where the
        true rating may lie."""
        model = self._require()
        top = model.typical_top.at(net_rating) if top_players is None else float(top_players)
        estimate = stage_probabilities(model.steps, net_rating, top, error=error)
        sampled = stage_probabilities(model.steps, net_rating, top, draws=True, error=error)
        rows = []
        for key in BRACKET_STAGE_KEYS:
            low, high = percentile_interval(np.asarray(sampled[key]), model.spec.confidence)
            rows.append(
                {
                    "key": key,
                    "label": stage(key).label,
                    "probability": float(estimate[key]),
                    "low": low,
                    "high": high,
                }
            )
        return Outlook(
            float(net_rating), top, error, pd.DataFrame(rows, columns=list(STAGE_COLUMNS))
        )

    def curve(self, top_players: float | None = None) -> pd.DataFrame:
        """Each stage's chance along a range of net ratings, for the chart: one row per
        rating in :data:`CURVE_RATINGS` with ``net_rating``, ``top_players`` and, per
        stage, the chance and its interval. Without ``top_players`` each rating takes the
        quality typical of teams at that rating."""
        rows = []
        for rating in CURVE_RATINGS:
            outlook = self.outlook(rating, top_players)
            row = {"net_rating": rating, "top_players": outlook.top_players}
            for item in outlook.stages.itertuples(index=False):
                column = probability_key(item.key)
                row[column] = item.probability
                row[f"{column}_low"] = item.low
                row[f"{column}_high"] = item.high
            rows.append(row)
        return pd.DataFrame(rows)

    def typical_top(self, net_rating: float) -> float:
        """The top-player quality typical of teams at a net rating."""
        return float(self._require().typical_top.at(net_rating))

    # --- a subject -----------------------------------------------------------------------------

    def team(self, team_id: int, season: str) -> SubjectOutlook:
        """A real team as a team of its strength: its regular-season net rating and
        top-player quality in the season, and the season model's chances for a team
        like it - before any bracket, as if entering any season."""
        model = self._require()
        names = self._lab.team_labels()
        name = str(names["full_name"].get(team_id, f"Team {team_id}"))
        tables = self._season_tables(season)
        features = keyed(team_features(tables, model.spec))
        if (season, team_id) not in features.index:
            return SubjectOutlook(
                TEAM, int(team_id), name, season, None, None, (), None,
                f"{name} has no statistics on record for {season}.", None,
            )  # fmt: skip
        row = features.loc[(season, team_id)]
        net, top = float(row["net_rating"]), float(row["top_players"])
        if not np.isfinite(top):
            return SubjectOutlook(
                TEAM, int(team_id), name, season, net, None, (), None,
                f"None of the players who finished {season} with {name} has been valued by "
                "the value model, so the team's top-player quality is unknown.", None,
            )  # fmt: skip
        count = model.spec.top_players
        return SubjectOutlook(
            TEAM,
            int(team_id),
            name,
            season,
            net,
            top,
            self._top_names(tables, int(team_id), count),
            None,
            f"The regular-season net rating of {name} in {season} and the mean impact of the "
            f"{count} players with the highest impact who finished the season with the team: "
            "what the season model reads a team by.",
            self.outlook(net, top),
        )

    def roster(self, roster_id: int) -> SubjectOutlook:
        """A roster the user built, as a team of the strength its players showed in the
        roster's statistics season: the sum of the parts, with the value model's error,
        and the mean impact of the best of them."""
        model = self._require()
        report = self._lab.fit.roster(roster_id)
        members = report.members
        valued = (
            members["impact"].dropna().astype("float64")
            if not members.empty
            else pd.Series(dtype="float64")
        )
        if report.is_empty or valued.empty or not np.isfinite(report.parts.impact):
            return SubjectOutlook(
                ROSTER, int(roster_id), report.name, report.season, None, None, (), None,
                f"No player on {report.name} has an impact on record for {report.season}, so "
                "there is no strength to read.", None,
            )  # fmt: skip
        best = valued.nlargest(model.spec.top_players)
        net, top, error = float(report.parts.impact), float(best.mean()), report.parts.error
        return SubjectOutlook(
            ROSTER,
            int(roster_id),
            report.name,
            report.season,
            net,
            top,
            tuple(str(members.at[player, "player_name"]) for player in best.index),
            error,
            f"The players' impacts in {report.season} added up for the minutes they played - "
            "the net rating a team would have if its players simply added up - taken with the "
            f"value model's error, and the mean impact of the {len(best)} best of them.",
            self.outlook(net, top, error=error),
        )

    @staticmethod
    def _top_names(tables: dict[str, pd.DataFrame], team_id: int, count: int) -> tuple[str, ...]:
        lines = tables["player_seasons"]
        mine = lines.loc[lines["team_id"] == team_id, ["player_id", "player_name"]]
        scores = tables["player_value_scores"][["player_id", "impact"]].dropna(subset=["impact"])
        best = mine.merge(scores, on="player_id").nlargest(count, "impact")
        return tuple(str(name) for name in best["player_name"])

    # --- assembly ----------------------------------------------------------------------------

    def _require(self) -> PostseasonModel:
        model = self.model()
        if model is None:
            raise PostseasonError(f"no postseason model has been fitted; run: {FIT_COMMAND}")
        return model

    def _season_tables(self, season: str) -> dict[str, pd.DataFrame]:
        read = self._lab.read
        return {
            "team_seasons": read("team_seasons", {"season": season}),
            "team_games": read("team_games", {"season": season}),
            "playoff_results": read("playoff_results", {"season": season}),
            "player_seasons": read("player_seasons", {"season": season, "season_type": REGULAR}),
            "player_value_scores": read("player_value_scores", {"season": season}),
            # Experience is not an input of the model, so the logs it is counted from are
            # not read; the feature is left missing.
            "player_game_logs": PLAYER_GAME_LOGS.empty_frame(),
        }

    @staticmethod
    def _parameters(model: PostseasonModel) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """The fitted parameters first, then every kept draw."""
        game = model.game
        home = np.array([game.home_advantage, *(draw.home for draw in game.draws)])
        net = np.array([game.net_rating, *(draw.net_rating for draw in game.draws)])
        top = np.array([game.top_players, *(draw.top_players for draw in game.draws)])
        return home, net, top

    @staticmethod
    def _bounds(values: np.ndarray, model: PostseasonModel) -> tuple[np.ndarray, np.ndarray]:
        """The interval of each row of ``values`` over its draws (every column but the
        first, which is the estimate)."""
        tail = 100 * (1 - model.spec.confidence) / 2
        low, high = np.percentile(values[:, 1:], [tail, 100 - tail], axis=1)
        return low, high

    @staticmethod
    def _identity(rows: pd.DataFrame, names: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "team_name": rows.index.map(
                    lambda team: names["full_name"].get(team, f"Team {team}")
                ),
                "abbreviation": rows.index.map(lambda team: names["abbreviation"].get(team, "")),
                "conference": rows["conference"].to_numpy(),
                "seed": rows["conference_rank"].to_numpy(),
                "wins": rows["wins"].to_numpy(),
                "losses": rows["losses"].to_numpy(),
                "net_rating": rows["net_rating"].to_numpy(),
                "top_players": rows["top_players"].to_numpy(),
            },
            index=pd.Index(rows.index, name="team_id"),
        )
