"""What may have changed since the user's contract file (A7): the league's moves and the
reported ones since its date, each beside what the file holds - and nothing imported."""

from __future__ import annotations

import shutil
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest

from front_office.assistant import tools as t
from front_office.assistant.contract_tools import contract_handlers
from front_office.assistant.web_tools import SourceBook
from front_office.config import Settings, load_settings
from front_office.domain.assistant import EvidenceKind, ResultStatus
from front_office.pipelines.current import refresh_current
from front_office.providers.nba_current import CurrentProvider
from front_office.services import Lab
from tests.current_fakes import FakeGet, league_files, move, movement
from tests.helpers import BOS, HART, NYK, PRITCHARD, TATUM
from tests.web_fakes import FakeWeb, Story, rss

NOW = datetime(2026, 10, 21, 21, 50)
MOVES = movement(
    move(
        TRANSACTION_DATE="2026-10-15T00:00:00",
        TRANSACTION_DESCRIPTION="Boston Celtics signed guard Payton Pritchard to a contract extension.",
        TEAM_ID=float(BOS),
        PLAYER_ID=float(PRITCHARD),
    ),
    move(
        TRANSACTION_DATE="2026-09-20T00:00:00",
        TRANSACTION_DESCRIPTION="Boston Celtics signed forward Jayson Tatum.",
        TEAM_ID=float(BOS),
        PLAYER_ID=float(TATUM),
        GroupSort="Signing 2",
    ),
)
"""One move after the contract file's date (2026-10-01), and one before it."""
HART_DEAL = Story(
    "Knicks Sign Josh Hart To Extension",
    "https://www.hoopsrumors.com/2026/10/knicks-hart-extension.html",
    datetime(2026, 10, 18, 15, 0),
    ("New York Knicks", "Transactions", "Josh Hart"),
)
PRITCHARD_DEAL = Story(
    "Celtics Sign Pritchard To Extension",
    "https://www.hoopsrumors.com/2026/10/celtics-pritchard-extension.html",
    datetime(2026, 10, 15, 20, 0),
    ("Boston Celtics", "Transactions", "Payton Pritchard (Player)"),
)


@pytest.fixture
def contracts(contract_template: Path, tmp_path: Path) -> Iterator[Lab]:
    """A private copy of the build with the invented contract file, as of 2026-10-01."""
    target = tmp_path / "lab"
    shutil.copytree(contract_template, target)
    with Lab(load_settings(target)) as lab:
        yield lab


def handlers(lab: Lab, *, league: FakeGet | None = None, feeds: FakeWeb | None = None):  # type: ignore[no-untyped-def]
    settings: Settings = lab.settings
    provider = CurrentProvider(
        get=league or league_files(moves=MOVES),
        now=lambda: NOW.replace(tzinfo=UTC),
        sleep=lambda _: None,
    )
    web = (feeds or FakeWeb(
        {
            "https://www.hoopsrumors.com/feed": rss(HART_DEAL, PRITCHARD_DEAL),
            "https://www.hoopsrumors.com/transactions/feed": rss(HART_DEAL, PRITCHARD_DEAL),
            "https://www.hoopsrumors.com/boston-celtics/feed/atom": rss(PRITCHARD_DEAL),
        }
    )).provider()  # fmt: skip

    def refresh(sources: Sequence[str]) -> object:
        return refresh_current(settings, sources=sources, now=lambda: NOW, provider=provider)

    def news_refresh(teams: Sequence[str]) -> object:
        return refresh_current(settings, sources=("news",), teams=teams, now=lambda: NOW, web=web)

    book = SourceBook(())
    return contract_handlers(refresh, news_refresh, book, now=lambda: NOW), book


def test_each_move_since_the_file_beside_what_the_file_holds(contracts: Lab) -> None:
    tools, book = handlers(contracts)
    found = tools["contract_updates"](contracts, t.ContractUpdates())
    assert found.status is ResultStatus.OK and found.kinds == ("reported",)
    lines = found.text.splitlines()
    assert lines[0].startswith(
        "Your contract file is as of 2026-10-01. Since then: 1 move(s) on the league's "
        "transactions file and 2 reported in the news feeds, newest first, each beside what "
        "your file holds for 2026-27."
    )
    assert "never imported" in lines[0] and "fol contracts preview" in lines[0]
    assert lines[1] == (
        "2026-10-15 league file, Signing: Boston Celtics signed guard Payton Pritchard to a "
        "contract extension. - Payton Pritchard: $7,000,000 for 2026-27 in your file"
    )
    assert lines[2] == (
        "s1: Knicks Sign Josh Hart To Extension - Hoops Rumors, 2026-10-18; "
        "Josh Hart: $12,000,000 for 2026-27 in your file"
    )
    assert lines[3].startswith("s2: Celtics Sign Pritchard To Extension"), "a (Player) tag counts"
    assert "Jayson Tatum" not in found.text, "a move before the file's date is not a change"
    assert [source.id for source in book.sources] == ["s1", "s2"], "each report can be read"
    kinds = [item.kind for item in found.evidence]
    assert kinds[0] is EvidenceKind.CONTRACTS and EvidenceKind.CURRENT in kinds
    assert found.limits == ()


def test_a_teams_moves_alone(contracts: Lab) -> None:
    tools, _ = handlers(contracts)
    found = tools["contract_updates"](contracts, t.ContractUpdates(team_id=NYK))
    assert "Since then about the New York Knicks: 0 move(s)" in found.text
    assert "Josh Hart" in found.text and "Pritchard" not in found.text


def test_no_move_since_is_said_with_its_limit(contracts: Lab) -> None:
    quiet = FakeWeb(
        {
            "https://www.hoopsrumors.com/feed": rss(),
            "https://www.hoopsrumors.com/transactions/feed": rss(),
        }
    )
    tools, _ = handlers(contracts, league=league_files(moves=movement()), feeds=quiet)
    found = tools["contract_updates"](contracts, t.ContractUpdates(player_id=TATUM))
    assert found.status is ResultStatus.OK and found.table is None
    assert found.limits and "which is not proof that nothing did" in found.limits[0]


def test_without_a_contract_file_there_is_nothing_to_compare(built_lab: Settings) -> None:
    with Lab(built_lab) as lab:
        tools, _ = handlers(lab)
        found = tools["contract_updates"](lab, t.ContractUpdates())
    assert found.status is ResultStatus.UNAVAILABLE
    assert "No contract file has been imported" in found.text


def test_nothing_reported_changes_the_contract_file(contracts: Lab) -> None:
    before = contracts.read("contract_years")
    tools, _ = handlers(contracts)
    tools["contract_updates"](contracts, t.ContractUpdates())
    assert contracts.read("contract_years").equals(before)
    assert int(contracts.contracts.salaries("2026-27").at[HART, "salary"]) == 12_000_000
