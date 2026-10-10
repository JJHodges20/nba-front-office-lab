from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from front_office.assistant.evaluation import load_cases
from front_office.assistant.tools import (
    BY_NAME,
    REGISTRY,
    OptimizeRoster,
    Permission,
    ReadSource,
    SimulateScenario,
    ToolSpec,
    tool_schema,
    tool_schemas,
)
from front_office.domain.optimizer import BudgetMode
from front_office.domain.scenario import Availability, Development, SubjectKind
from front_office.domain.stages import STAGES
from front_office.services.benchmarks import MEASURES

CASES = Path(__file__).resolve().parents[2] / "assistant" / "fixtures" / "cases.yaml"


def _keys(node: Any) -> set[str]:
    if isinstance(node, dict):
        return set(node) | set().union(*(_keys(value) for value in node.values()))
    if isinstance(node, list):
        return set().union(*(_keys(item) for item in node)) if node else set()
    return set()


class TestTheRegistry:
    def test_names_are_unique_and_plain(self) -> None:
        names = [spec.name for spec in REGISTRY]
        assert len(names) == len(set(names)) == len(BY_NAME)
        assert all(re.fullmatch(r"[a-z][a-z_]*", name) for name in names)

    def test_nothing_writes(self) -> None:
        """Saving is the user's click. The permission classes have no member that writes."""
        assert {permission.value for permission in Permission} == {
            "read",
            "compute",
            "net",
            "draft",
        }
        assert {spec.permission for spec in REGISTRY} <= set(Permission)

    def test_no_tool_takes_sql_code_a_file_or_a_url(self) -> None:
        fields = {name for spec in REGISTRY for name in spec.args.model_fields}
        assert not fields & {"sql", "query_sql", "code", "command", "path", "file", "url"}

    def test_every_tool_says_when_it_is_built(self) -> None:
        assert {spec.milestone for spec in REGISTRY} <= {"A2", "A4", "A5"}

    def test_enumerations_are_the_labs_own(self) -> None:
        schema = {spec.name: tool_schema(spec)["function"]["parameters"] for spec in REGISTRY}
        benchmarks = schema["historical_benchmarks"]["properties"]
        assert benchmarks["stage"]["enum"] == [stage.key for stage in STAGES]
        assert benchmarks["measure"]["enum"] == [measure.key for measure in MEASURES]
        scenario = schema["simulate_scenario"]["properties"]
        assert scenario["subject"]["enum"] == [kind.value for kind in SubjectKind]
        assert scenario["availability"]["enum"] == [preset.value for preset in Availability]
        assert scenario["development"]["enum"] == [preset.value for preset in Development]
        modes = schema["optimize_roster"]["properties"]["budget_mode"]["enum"]
        assert modes == [mode.value for mode in BudgetMode]


class TestTheSchemas:
    def test_each_is_a_flat_function_definition(self) -> None:
        for definition in tool_schemas():
            assert definition["type"] == "function"
            parameters = definition["function"]["parameters"]
            assert parameters["type"] == "object"
            assert not _keys(parameters) & {
                "$ref",
                "$defs",
                "anyOf",
                "title",
                "additionalProperties",
            }

    def test_optional_arguments_are_simply_not_required(self) -> None:
        team = tool_schema(BY_NAME["team_stats"])["function"]["parameters"]
        assert team["required"] == ["team_id", "season"]
        assert team["properties"]["last_games"] == {"type": "integer", "minimum": 1, "maximum": 82}

    def test_an_argument_called_title_survives(self) -> None:
        class Titled(BaseModel):
            title: str

        spec = ToolSpec("titled", "A test.", Titled, Permission.READ, "A2")  # type: ignore[arg-type]
        assert "title" in tool_schema(spec)["function"]["parameters"]["properties"]

    def test_the_whole_registry_is_a_few_thousand_tokens(self) -> None:
        """What every request carries: kept small enough to leave room in the context."""
        assert len(json.dumps(tool_schemas())) < 14_000


class TestValidation:
    def test_a_custom_budget_needs_its_amount(self) -> None:
        with pytest.raises(ValidationError, match="budget_millions"):
            OptimizeRoster(budget_mode="custom")
        assert OptimizeRoster(budget_mode="custom", budget_millions=150).budget_millions == 150

    def test_a_source_is_read_by_id_never_by_address(self) -> None:
        assert ReadSource(source_id="u1").source_id == "u1"
        with pytest.raises(ValidationError):
            ReadSource(source_id="https://example.com/page")

    def test_unknown_arguments_are_refused(self) -> None:
        with pytest.raises(ValidationError):
            SimulateScenario(subject="team", subject_id=1, save=True)

    def test_data_status_ignores_what_it_does_not_take(self) -> None:
        """A4: a model sent data_status a view, then a season."""
        assert BY_NAME["data_status"].args(view="data_build", season="2025-26") is not None

    def test_a_player_id_a_value_view_does_not_read_is_dropped(self) -> None:
        """A4: a model sent player_id 0 with model_evidence."""
        value = BY_NAME["player_value"].args
        assert value(view="model_evidence", player_id=0).player_id is None
        assert value(view="season_leaders", player_id=7).player_id is None
        assert value(view="projections", player_id=7).player_id == 7

    def test_a_season_is_written_like_2025_26(self) -> None:
        with pytest.raises(ValidationError):
            BY_NAME["team_stats"].args(team_id=1, season="2025")


def test_every_expected_call_in_the_cases_fits_its_tool() -> None:
    """A case can only expect what the registry can be asked for."""
    for case in load_cases(CASES).cases:
        for option in case.expect.calls:
            spec = BY_NAME[option.tool]
            unknown = set(option.args) - set(spec.args.model_fields)
            assert not unknown, f"{case.id}: {option.tool} has no {sorted(unknown)}"
        for tool in case.expect.forbid_calls:
            assert tool in BY_NAME, case.id
