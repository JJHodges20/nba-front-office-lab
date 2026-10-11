"""Check a contract file against the one in use before importing it (decision 0018, A7).

The contract-update review. A candidate file is read and matched exactly as
``pipelines.contracts.import_contract_file`` would read it, and compared with the file in
use, season by season and team by team; what needs checking is said in plain sentences.
This module only reads - the candidate, the raw store's imports, the league's index and the
cap rules - and stores nothing, which is why the assistant may reach it and not the import
beside it. The import stays the user's own command, once they have checked the source.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from front_office.config.season_rules import load_all_season_rules
from front_office.config.settings import Settings
from front_office.domain.contract_review import ContractPreview, InUse
from front_office.domain.datasets import CONTRACT_FILE, CONTRACT_FILE_DATASET
from front_office.domain.tables.finance import CONTRACT_YEARS
from front_office.pipelines.normalize import reference_tables
from front_office.processing.contracts import (
    ContractFileError,
    UnmatchedRow,
    build_contracts,
    compare_contract_years,
)
from front_office.providers.contract_file import read_contract_file
from front_office.providers.nba_stats import ProviderError
from front_office.rawstore import RawStore, RawStoreError


class ContractReviewError(RuntimeError):
    """The file could not be checked; the message says why. Nothing was stored."""


def preview_contract_file(
    settings: Settings, path: Path, *, source_label: str, as_of: date
) -> ContractPreview:
    """A candidate contract file against the one in use: read and matched as an import
    would read it, compared season by season, with what to check before importing it.
    Nothing is stored."""
    store = RawStore(settings.raw_dir)
    try:
        teams, players = reference_tables(store)
        rules = load_all_season_rules(settings.season_rules_dir)
        caps = {season.label: season_rules.salary_cap for season, season_rules in rules.items()}
        snapshot = read_contract_file(path, source_label=source_label, as_of=as_of)
        candidate = build_contracts(snapshot, players=players, teams=teams, caps=caps)
        imported = [
            store.load(stored)
            for stored in store.versions(CONTRACT_FILE, CONTRACT_FILE_DATASET, {})
        ]
        current = imported[-1] if imported else None
        in_use = (
            None
            if current is None
            else build_contracts(current, players=players, teams=teams, caps=caps)
        )
    except (LookupError, ProviderError, ContractFileError, RawStoreError) as error:
        raise ContractReviewError(str(error)) from error

    names = dict(
        zip(players["player_id"].astype(int), players["full_name"].astype(str), strict=True)
    )
    abbreviations = dict(
        zip(teams["team_id"].astype(int), teams["abbreviation"].astype(str), strict=True)
    )
    changes, unchanged = compare_contract_years(
        CONTRACT_YEARS.empty_frame() if in_use is None else in_use.contract_years,
        candidate.contract_years,
        names=names,
        teams=abbreviations,
    )
    label = source_label.strip()
    seasons = tuple(sorted(candidate.contract_years["season"].unique()))
    using = (
        None
        if current is None
        else InUse(
            file_name=str(current.payload.get("filename", "")),
            source_label=str(current.payload["source_label"]),
            as_of=date.fromisoformat(str(current.payload["as_of"])),
            imported_at=pd.Timestamp(current.fetched_at).tz_convert(None).to_pydatetime(),
        )
    )
    flags = []
    if candidate.contracts.empty:
        flags.append("No row could be matched to a known player: an import would store nothing.")
    if label not in {str(stored.payload["source_label"]) for stored in imported}:
        flags.append(
            f"“{label}” has not been imported before. Check that its terms allow this use, and "
            "record it in docs/DATA_SOURCE_REGISTER.md, before importing."
        )
    if using is None:
        flags.append("No contract file is in use yet: every row would be new.")
    elif as_of < using.as_of:
        flags.append(
            f"Its figures are as of {as_of:%Y-%m-%d}, older than those in use "
            f"({using.as_of:%Y-%m-%d}): importing it would make it the file in use."
        )
    if candidate.unmatched:
        flags.append(
            f"{len(candidate.unmatched)} row(s) name a player or team the league's index does "
            "not hold; an import would leave them out, never guess them."
        )
    configured = {season.label for season in rules}
    without = [season for season in seasons if season not in configured]
    if without:
        flags.append(
            f"No cap rules are configured for {', '.join(without)}: salaries there would have no "
            "share of the cap."
        )
    return ContractPreview(
        file_name=path.name,
        source_label=label,
        as_of=as_of,
        rows_read=candidate.rows_read,
        players=int(candidate.contracts["player_id"].nunique()),
        seasons=seasons,
        in_use=using,
        changes=tuple(changes),
        unchanged=unchanged,
        unmatched=tuple(_unmatched(row) for row in candidate.unmatched),
        flags=tuple(flags),
        command=f'fol contracts import "{path}" --source "{label}" --as-of {as_of:%Y-%m-%d}',
    )


def _unmatched(row: UnmatchedRow) -> str:
    team = f" ({row.team})" if row.team else ""
    return f"line {row.line}: {row.player}{team} - {row.reason}"
