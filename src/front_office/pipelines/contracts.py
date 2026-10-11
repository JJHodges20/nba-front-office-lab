"""Bring a user-supplied contract file into the raw store, and write the template for one.

A contract file is validated *before* it is stored. A file that cannot be parsed never
becomes the newest snapshot, so a bad import cannot break the next build. To check a file
against the one in use before importing it: ``pipelines.contract_review`` (A7).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from front_office.config.season_rules import load_all_season_rules
from front_office.config.settings import Settings
from front_office.domain.seasons import Season
from front_office.pipelines.normalize import reference_tables
from front_office.processing.contracts import ContractFileError, UnmatchedRow, build_contracts
from front_office.providers.contract_file import read_contract_file
from front_office.providers.nba_stats import ProviderError
from front_office.rawstore import RawStore, RawStoreError

TEMPLATE_NAME = "contract_template.csv"
TEMPLATE_SEASONS = 6


class ContractImportError(RuntimeError):
    """The contract file was not imported; nothing was stored."""


@dataclass(frozen=True, slots=True)
class ContractImportReport:
    rows_read: int
    contracts: int
    contract_years: int
    players: int
    seasons: tuple[str, ...]
    seasons_without_cap: tuple[str, ...]
    unmatched: tuple[UnmatchedRow, ...]
    stored: bool
    """False when the file's content was identical to the newest stored import."""


def import_contract_file(
    settings: Settings, path: Path, *, source_label: str, as_of: date
) -> ContractImportReport:
    """Validate a contract file against the known players and teams, then store it."""
    store = RawStore(settings.raw_dir)
    try:
        teams, players = reference_tables(store)
        rules = load_all_season_rules(settings.season_rules_dir)
        snapshot = read_contract_file(path, source_label=source_label, as_of=as_of)
        tables = build_contracts(
            snapshot,
            players=players,
            teams=teams,
            caps={season.label: season_rules.salary_cap for season, season_rules in rules.items()},
        )
        if tables.contracts.empty:
            raise ContractImportError(
                f"none of the {tables.rows_read} row(s) in {path.name} could be matched to a "
                "known player; nothing was imported"
            )
        saved = store.save(snapshot)
    except (LookupError, ProviderError, ContractFileError, RawStoreError) as error:
        raise ContractImportError(str(error)) from error

    seasons = tuple(sorted(tables.contract_years["season"].unique()))
    configured = {season.label for season in rules}
    return ContractImportReport(
        rows_read=tables.rows_read,
        contracts=len(tables.contracts),
        contract_years=len(tables.contract_years),
        players=int(tables.contracts["player_id"].nunique()),
        seasons=seasons,
        seasons_without_cap=tuple(season for season in seasons if season not in configured),
        unmatched=tuple(tables.unmatched),
        stored=saved.created,
    )


def write_contract_template(
    settings: Settings,
    *,
    today: date,
    output: Path | None = None,
    seasons: int = TEMPLATE_SEASONS,
) -> tuple[Path, int]:
    """Write a contract file with every rostered player filled in and salaries blank.

    Returns the path written and the number of players listed.
    """
    try:
        teams, players = reference_tables(RawStore(settings.raw_dir))
    except (LookupError, RawStoreError) as error:
        raise ContractImportError(str(error)) from error

    # An inner join: a player with no current team, retired or unsigned, drops out.
    rostered = players.merge(
        teams[["team_id", "abbreviation"]], left_on="current_team_id", right_on="team_id"
    )
    rostered = rostered.sort_values(["abbreviation", "last_name", "full_name"])
    first = Season.league_year_on(today)
    season_columns = [first.offset(step).label for step in range(seasons)]

    target = output or settings.imports_dir / TEMPLATE_NAME
    target.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig: Excel only shows accented names correctly when the file has a BOM.
    with open(target, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["player_id", "player", "team", "type", *season_columns, "guaranteed"])
        for player in rostered.itertuples():
            writer.writerow(
                [player.player_id, player.full_name, player.abbreviation, "", *[""] * seasons, ""]
            )
    return target, len(rostered)
