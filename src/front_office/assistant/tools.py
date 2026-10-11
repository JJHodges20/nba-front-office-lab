"""The tools the model may ask for: names, typed arguments, permission classes.

Decision 0018 and docs/AI_ASSISTANT_SPEC.md. The model sees each tool as a name, a short
description and a JSON schema made from the tool's Pydantic model; whatever it asks for
is validated against that model before anything runs. There is no write class: saving
anything is the user's own click, never a tool.

Enumerations are read from where the lab keeps them - the stages from ``domain.stages``,
the benchmark measures from the benchmark service, the scenario presets and budget modes
from their domain models - so that a list here cannot drift from the one the lab uses.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from front_office.domain.experiments import FAILURE_MODES, ModelKey, in_words
from front_office.domain.optimizer import BudgetMode
from front_office.domain.scenario import (
    FULL_SEASON_GAMES,
    MAX_DEVELOPMENT,
    MAX_PLAYERS,
    Availability,
    Development,
    SubjectKind,
)
from front_office.domain.stages import STAGES
from front_office.services.benchmarks import MEASURES


class Permission(StrEnum):
    """What running a tool may do. There is no class that writes."""

    READ = "read"
    """Reads the lab's database or model files through the services."""
    COMPUTE = "compute"
    """Runs the optimizer or the simulator; the result is kept in memory only."""
    NET = "net"
    """Reaches current data or the web; may fill a cache."""
    DRAFT = "draft"
    """Drafts something for the user to review: it travels with the answer, and only the
    user's click keeps it. It stores nothing and changes nothing (A8)."""


Season = Annotated[str, StringConstraints(pattern=r"^\d{4}-\d{2}$")]
SeasonPhase = Literal["regular", "playoffs"]
StageKey = Literal[tuple(stage.key for stage in STAGES)]  # type: ignore[valid-type]
MeasureKey = Literal[tuple(measure.key for measure in MEASURES)]  # type: ignore[valid-type]
SubjectName = Literal[tuple(kind.value for kind in SubjectKind)]  # type: ignore[valid-type]
AvailabilityName = Literal[tuple(preset.value for preset in Availability)]  # type: ignore[valid-type]
DevelopmentName = Literal[tuple(preset.value for preset in Development)]  # type: ignore[valid-type]
BudgetModeName = Literal[tuple(mode.value for mode in BudgetMode)]  # type: ignore[valid-type]
LastGames = Annotated[int, Field(ge=1, le=FULL_SEASON_GAMES)]


class ToolArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ResolveEntities(ToolArgs):
    text: str = Field(min_length=1, max_length=80, description="The name as the user wrote it.")
    kind: Literal["any", "player", "team"] = "any"


class DataStatus(ToolArgs):
    # It takes nothing. At A4 a model sent it a view, and then a season; they are ignored
    # rather than refused, as the call means the same without them.
    model_config = ConfigDict(extra="ignore", frozen=True)


class PlayerStats(ToolArgs):
    player_id: int
    season: Season
    season_type: SeasonPhase = "regular"
    view: Literal["season", "career", "games", "form"] = Field(
        "season",
        description="season: the season's figures; career: every season; games: the game "
        "log; form: averages over trailing games.",
    )
    last_games: LastGames | None = None


class ComparePlayers(ToolArgs):
    player_ids: list[int] = Field(min_length=2, max_length=5)
    season: Season
    season_type: SeasonPhase = "regular"
    # The other statistics tools take a view, and a model sent one here again and again (A1,
    # A2); it is given a meaning rather than refused.
    view: Literal["season", "form"] = Field(
        "season",
        description="season: the season so far; form: the last games (10 unless last_games).",
    )
    metrics: list[str] = Field(default_factory=list, max_length=8, description="Metric keys.")
    last_games: LastGames | None = None


class TeamStats(ToolArgs):
    team_id: int
    season: Season
    season_type: SeasonPhase = "regular"
    view: Literal["season", "history", "games", "form", "rotation"] = Field(
        "season",
        description="season: figures and league ranks; history: every season; games: the "
        "game log; form: trailing games; rotation: who played.",
    )
    last_games: LastGames | None = None


class LeagueContext(ToolArgs):
    view: Literal["standings", "team_ranks", "averages", "champions", "playoffs"]
    season: Season | None = None


class HistoricalBenchmarks(ToolArgs):
    stage: StageKey
    measure: MeasureKey = "net_rating"
    era: str = Field("all", description="An era key; all is every season on record.")
    first_season: Season | None = None
    last_season: Season | None = None


class MetricDefinition(ToolArgs):
    metric: str = Field(min_length=1, max_length=60, description="A metric key or its name.")


class ContractInfo(ToolArgs):
    view: Literal["player", "team", "league", "cap_rules"]
    season: Season | None = Field(
        None, description="The season the question names; without one, the contract file's."
    )
    player_id: int | None = None
    team_id: int | None = None


PLAYERLESS_VALUE_VIEWS = frozenset({"season_leaders", "value_for_money", "model_evidence"})
"""The value views that read no single player."""


class PlayerValue(ToolArgs):
    view: Literal[
        "player",
        "season_leaders",
        "projections",
        "breakdown",
        "roles",
        "value_for_money",
        "model_evidence",
    ] = Field(
        description="player: one player's value by season and projection (player_id); "
        "season_leaders: the most valuable players of a season; projections: next season's "
        "(player_id for one player); breakdown: where a player's impact comes from "
        "(player_id, season); roles: the roles players fill and how often they carry over; "
        "value_for_money: salaries against value; model_evidence: how accurate the value "
        "model was on seasons it had not seen, against simpler methods."
    )
    player_id: int | None = None
    season: Season | None = None

    @model_validator(mode="before")
    @classmethod
    def _no_player_where_none_is_read(cls, data: Any) -> Any:
        # At A4 a model sent player_id 0 with model_evidence: an id a view does not read
        # is dropped, rather than refused as a player the lab does not hold.
        if isinstance(data, Mapping) and data.get("view") in PLAYERLESS_VALUE_VIEWS:
            return {key: value for key, value in data.items() if key != "player_id"}
        return data


class RosterFit(ToolArgs):
    view: Literal["profile", "evidence", "champions"] = "profile"
    team_id: int | None = None
    season: Season | None = None
    roster_id: int | None = None


class PostseasonOutlook(ToolArgs):
    view: Literal["team", "roster", "strength", "bracket", "season_odds", "model_record"] = Field(
        description="team: a real team in a season (team_id, season; the season ahead is "
        "drawn by the simulator); roster: a built roster (roster_id); strength: a "
        "hypothetical team of any net rating (net_rating) - the model reads net rating, not "
        "wins: for a team known by its record, historical_benchmarks with wins_per_82; "
        "bracket: a decided season's playoff teams; season_odds: every team of a season; "
        "model_record: how the postseason model did on seasons it had not seen."
    )
    team_id: int | None = None
    season: Season | None = None
    roster_id: int | None = None
    net_rating: float | None = Field(None, ge=-30, le=30)
    top_players: float | None = Field(None, ge=-10, le=15)


class PlayerAssumption(ToolArgs):
    player_id: int
    games_missed: float | None = Field(None, ge=0, le=FULL_SEASON_GAMES)
    development: float | None = Field(None, ge=-MAX_DEVELOPMENT, le=MAX_DEVELOPMENT)
    minutes_share: float | None = Field(None, ge=0, le=1)
    salary_millions: float | None = Field(None, ge=0, le=100)


class SimulateScenario(ToolArgs):
    subject: SubjectName
    subject_id: int = Field(description="The team id, or the built roster's id.")
    add_player_ids: list[int] = Field(default_factory=list, max_length=MAX_PLAYERS)
    remove_player_ids: list[int] = Field(default_factory=list, max_length=MAX_PLAYERS)
    player_assumptions: list[PlayerAssumption] = Field(default_factory=list, max_length=MAX_PLAYERS)
    availability: AvailabilityName = "as_projected"
    development: DevelopmentName = "expected"


class RoleMinimum(ToolArgs):
    role: str = Field(description="An archetype key, e.g. rim_protector.")
    count: int = Field(ge=1, le=5)


class OptimizeRoster(ToolArgs):
    budget_mode: BudgetModeName = Field(
        "salary_cap",
        description="A line of the season's cap rules (salary_cap, luxury_tax, first_apron, "
        "second_apron), or custom when the user names an amount ($150M): then give "
        "budget_millions.",
    )
    budget_millions: float | None = Field(
        None,
        gt=0,
        le=1000,
        description="Only with budget_mode custom: the user's amount in millions (150 for $150M).",
    )
    min_players: int | None = Field(None, ge=1, le=MAX_PLAYERS)
    max_players: int | None = Field(None, ge=1, le=MAX_PLAYERS)
    min_guards: int | None = Field(None, ge=0, le=10)
    min_wings: int | None = Field(None, ge=0, le=10)
    min_bigs: int | None = Field(None, ge=0, le=10)
    role_minimums: list[RoleMinimum] = Field(default_factory=list, max_length=8)
    lock_player_ids: list[int] = Field(default_factory=list, max_length=MAX_PLAYERS)
    exclude_player_ids: list[int] = Field(default_factory=list, max_length=50)
    options: int = Field(
        3, ge=2, le=4, description="How many distinct rosters, 2 to 4; 3 unless the user says."
    )

    @model_validator(mode="after")
    def _a_custom_budget_names_its_amount(self) -> OptimizeRoster:
        if self.budget_mode == BudgetMode.CUSTOM.value and self.budget_millions is None:
            raise ValueError("a custom budget needs budget_millions")
        if self.budget_millions is not None and self.budget_mode != BudgetMode.CUSTOM.value:
            # Every model in the A1 benchmark sent an amount with the salary-cap mode.
            raise ValueError("budget_millions is for a custom budget: set budget_mode to custom")
        return self


class CurrentGames(ToolArgs):
    team_id: int | None = None
    since: date | None = None
    until: date | None = None


class InjuryReport(ToolArgs):
    team_id: int | None = None
    player_id: int | None = None


class Transactions(ToolArgs):
    team_id: int | None = None
    player_id: int | None = None
    since: date | None = None


class MovesAndRumors(ToolArgs):
    team_id: int | None = None
    player_id: int | None = None
    moves_only: bool = Field(
        False,
        description="Only signings, extensions, trades and waivers, as the site reports them.",
    )
    days: int = Field(14, ge=1, le=120, description="How many days back.")


class ContractUpdates(ToolArgs):
    team_id: int | None = None
    player_id: int | None = None


class WebSearch(ToolArgs):
    query: str = Field(min_length=3, max_length=200)
    max_results: int = Field(5, ge=1, le=10)


class ReadSource(ToolArgs):
    source_id: str = Field(
        pattern=r"^[a-z]{1,2}\d{1,4}$",
        description="A source's id: s1, s2... from moves_and_rumors or web_search, u1... from "
        "a pasted link. Never a result id like r1, never a URL.",
    )


class ResearchDocs(ToolArgs):
    query: str = Field(min_length=3, max_length=200)


InWords = Annotated[str, AfterValidator(in_words)]


# The model's idea for an experiment, in words: every figure in a proposal is the lab's,
# added from the model's file, so none can be made up and cited back (A8). No docstring:
# it would be sent with every request.
class ProposeExperiment(ToolArgs):
    model: ModelKey
    name: InWords = Field(min_length=3, max_length=80)
    observation: InWords = Field(min_length=10, max_length=600)
    hypothesis: InWords = Field(min_length=10, max_length=400, description="Testable.")
    change: InWords = Field(min_length=5, max_length=400, description="Feature or model change.")
    failure_modes: list[InWords] = Field(
        min_length=1, max_length=FAILURE_MODES, description="How it could fail."
    )


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    summary: str
    """What the model reads about the tool."""
    args: type[ToolArgs]
    permission: Permission
    milestone: str
    """The milestone that builds what the tool calls."""


R, C, N, D = Permission.READ, Permission.COMPUTE, Permission.NET, Permission.DRAFT

REGISTRY: tuple[ToolSpec, ...] = (
    ToolSpec("resolve_entities", "Find a player's or team's id from a name.", ResolveEntities, R, "A2"),
    ToolSpec("data_status", "What the lab holds: seasons covered, data build, model versions, contract file date, freshness.", DataStatus, R, "A2"),
    ToolSpec("player_stats", "One player's statistics: a season, a career, a game log or recent form.", PlayerStats, R, "A2"),
    ToolSpec("compare_players", "Several players side by side on chosen metrics in one season.", ComparePlayers, R, "A2"),
    ToolSpec("team_stats", "One team's season: record, ratings and league ranks, history, games, form or rotation.", TeamStats, R, "A2"),
    ToolSpec("league_context", "The league: standings, every team's ranks, league averages, every champion with its record and net rating rank (to compare champions), a season's playoff series.", LeagueContext, R, "A2"),
    ToolSpec("historical_benchmarks", "How often past teams in each band of a measure reached a playoff stage: frequencies with counts and intervals, not chances.", HistoricalBenchmarks, R, "A2"),
    ToolSpec("metric_definition", "What a metric means, its unit and where it comes from.", MetricDefinition, R, "A2"),
    ToolSpec("contract_info", "Salaries and payrolls from the user's contract file, with its date: a player's salary by season; a team's payroll against the cap, the tax line and the aprons; every team's payroll; the cap rules.", ContractInfo, R, "A2"),
    ToolSpec("player_value", "The player value model: a player's impact and wins by season and next season's projection, a season's leaders, where an impact comes from, roles, value for money, and how accurate the model was on seasons it had not seen.", PlayerValue, R, "A4"),
    ToolSpec("roster_fit", "How a team's or built roster's players fit together, as description; the evidence on whether fit predicts anything.", RosterFit, R, "A4"),
    ToolSpec("postseason_outlook", "The postseason model's chance of each playoff stage, with intervals: a real team's season, a built roster, or a hypothetical team of any net rating; every team of a season; the model's record.", PostseasonOutlook, R, "A4"),
    ToolSpec("simulate_scenario", "Simulate next season for a team or built roster, before and after changes the user assumes.", SimulateScenario, C, "A4"),
    ToolSpec("optimize_roster", "Find several distinct hypothetical rosters under a payroll budget and role requirements. How it chooses them is in research_docs.", OptimizeRoster, C, "A5"),
    ToolSpec("current_games", "Recently completed games, newer than the lab's data build.", CurrentGames, N, "A2"),
    ToolSpec("injury_report", "The league's official injury report, with its time.", InjuryReport, N, "A2"),
    ToolSpec("transactions", "Signings, trades and waivers announced by the league, with dates: what has changed on a roster since the lab's build.", Transactions, N, "A2"),
    ToolSpec("moves_and_rumors", "Recent roster moves and rumors from the news feeds the lab reads, dated: signings, extensions, trades, waivers, injuries, for a team, a player or the league, from the last few weeks.", MovesAndRumors, N, "A7"),
    ToolSpec("contract_updates", "Only when the user asks whether their contract file or its salaries are out of date: the moves since the file's date, beside what the file holds. Nothing is imported.", ContractUpdates, N, "A7"),
    ToolSpec("web_search", "Search the web for reporting; returns sources with ids.", WebSearch, N, "A2"),
    ToolSpec("read_source", "Read one source by its id: a search result, a feed item or a link the user pasted.", ReadSource, N, "A2"),
    ToolSpec("research_docs", "Search the lab's own documentation and research: how a figure is computed, how a tool or model works and was tested, why something was decided.", ResearchDocs, R, "A4"),
    ToolSpec("propose_experiment", "Only when the user asks for an experiment, or an idea to improve one of the lab's models: writes it up as a proposal for the user to review - a plan, so its data need not exist yet. Give your idea in words, without figures; the lab adds the model's test, what a change must beat and what was tried before. Nothing is fitted or changed.", ProposeExperiment, D, "A8"),
)  # fmt: skip

BY_NAME: Mapping[str, ToolSpec] = {spec.name: spec for spec in REGISTRY}


def tool_schema(spec: ToolSpec) -> dict[str, Any]:
    """The tool as Ollama's ``tools`` field takes it, with a flat, small JSON schema."""
    raw = spec.args.model_json_schema()
    schema = _simplify(raw, raw.get("$defs", {}))
    return {
        "type": "function",
        "function": {"name": spec.name, "description": spec.summary, "parameters": schema},
    }


def tool_schemas(specs: Sequence[ToolSpec] = REGISTRY) -> list[dict[str, Any]]:
    return [tool_schema(spec) for spec in specs]


_DROPPED = frozenset({"title", "$defs", "additionalProperties"})
"""Schema keys the model does not need: validation enforces them regardless."""


def _simplify(node: Any, definitions: Mapping[str, Any]) -> Any:
    """Inline references, drop titles and the like, and turn "this or null" into "this":
    an optional argument is simply one the model may leave out."""
    if isinstance(node, list):
        return [_simplify(item, definitions) for item in node]
    if not isinstance(node, dict):
        return node
    if "$ref" in node:
        return _simplify(definitions[node["$ref"].rsplit("/", 1)[-1]], definitions)
    options = node.get("anyOf")
    if isinstance(options, list):
        concrete = [option for option in options if option != {"type": "null"}]
        if len(concrete) == 1 and len(concrete) < len(options):
            merged = {**{k: v for k, v in node.items() if k != "anyOf"}, **concrete[0]}
            return _simplify(merged, definitions)
    simplified: dict[str, Any] = {}
    for key, value in node.items():
        if key in _DROPPED or (key == "default" and value is None):
            continue
        if key == "properties":
            # Property names are argument names, kept whatever they are called.
            simplified[key] = {name: _simplify(item, definitions) for name, item in value.items()}
        else:
            simplified[key] = _simplify(value, definitions)
    return simplified
