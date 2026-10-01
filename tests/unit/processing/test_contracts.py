"""Contract-file parsing and matching.

Every player and salary here is invented. The cast is chosen to exercise matching:
accents, suffixes, punctuation, and two players who share a name.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from front_office.domain.schema import validate_frame
from front_office.domain.tables.finance import CONTRACT_YEARS, CONTRACTS
from front_office.processing.contracts import (
    ContractFileError,
    UnmatchedRow,
    build_contracts,
    describe_unmatched,
    normalize_name,
    parse_amount,
    parse_salary_cell,
)
from tests.helpers import snapshot

BOS, NYK = 1610612738, 1610612752
CAPS = {"2026-27": 100_000_000, "2027-28": 110_000_000}

TEAMS = pd.DataFrame(
    {
        "team_id": [BOS, NYK],
        "abbreviation": ["BOS", "NYK"],
        "full_name": ["Boston Celtics", "New York Knicks"],
        "nickname": ["Celtics", "Knicks"],
    }
)
PLAYERS = pd.DataFrame(
    {
        "player_id": [1, 2, 3, 4, 5, 6, 7],
        "full_name": [
            "Pat Example",
            "José Ejemplo",
            "Sam Sample Jr.",
            "D.J. O'Test",
            "Chris Common",  # retired
            "Chris Common",  # active, Boston
            "Chris Common",  # active, New York
        ],
        "is_active": [True, True, True, True, False, True, True],
        "current_team_id": pd.array([BOS, BOS, NYK, NYK, None, BOS, NYK], dtype="Int64"),
    }
)


def build(text: str, **kwargs):
    payload = {
        "filename": "contracts.csv",
        "source_label": "invented for tests",
        "as_of": "2026-10-01",
        "text": text,
    }
    arguments = {"players": PLAYERS, "teams": TEAMS, "caps": CAPS}
    arguments.update(kwargs)
    return build_contracts(snapshot("contracts", payload, source="contract_file"), **arguments)


class TestNormalizeName:
    @pytest.mark.parametrize(
        ("written", "expected"),
        [
            ("Nikola Vučević", "nikola vucevic"),
            ("Jaren Jackson Jr.", "jaren jackson"),
            ("Gary Payton II", "gary payton"),
            ("O.G. Anunoby", "og anunoby"),
            ("De'Aaron Fox", "deaaron fox"),
            ("Shai Gilgeous-Alexander", "shai gilgeous alexander"),
            ("  LeBron   James  ", "lebron james"),
            ("Nene", "nene"),
        ],
    )
    def test_reduces_a_name_to_what_matters(self, written: str, expected: str) -> None:
        assert normalize_name(written) == expected


class TestParseAmount:
    @pytest.mark.parametrize(
        ("text", "dollars"),
        [
            ("30000000", 30_000_000),
            ("$30,000,000", 30_000_000),
            (" $ 1,234,567 ", 1_234_567),
            ("30.5M", 30_500_000),
            ("$2.3m", 2_300_000),
            ("850K", 850_000),
            ("678,882", 678_882),
            ("0", 0),
        ],
    )
    def test_reads_dollar_amounts(self, text: str, dollars: int) -> None:
        assert parse_amount(text) == dollars

    @pytest.mark.parametrize(
        "text", ["", "thirty", "30,00", "1,2345", "-5", "30000000.50", "$", "30 million", "3e7"]
    )
    def test_rejects_anything_else(self, text: str) -> None:
        with pytest.raises(ValueError):
            parse_amount(text)


class TestParseSalaryCell:
    @pytest.mark.parametrize(
        ("cell", "expected"),
        [
            ("$30,000,000", (30_000_000, None, None)),
            ("32400000 PO", (32_400_000, "player", None)),
            ("$32,400,000 (TO)", (32_400_000, "team", None)),
            ("5M ETO", (5_000_000, "early_termination", None)),
            ("2,000,000 NG", (2_000_000, None, "none")),
            ("2,000,000 (TO) (PG)", (2_000_000, "team", "partial")),
            ("$ 30,000,000 g", (30_000_000, None, "full")),
        ],
    )
    def test_reads_salary_and_markers(self, cell: str, expected: tuple) -> None:
        assert parse_salary_cell(cell) == expected

    @pytest.mark.parametrize("cell", ["30M XYZ", "30M PO TO", "PO", "()", "30M NG PG"])
    def test_rejects_unknown_or_repeated_markers(self, cell: str) -> None:
        with pytest.raises(ValueError):
            parse_salary_cell(cell)


WIDE = """player,team,2026-27,2027-28,2028-29,guaranteed
Pat Example,BOS,"$30,000,000","$33,000,000 PO",,"$45,000,000"
Jose Ejemplo,BOS,2500000 NG,,,
Sam Sample,NYK,10M,11M,12M TO,
"""

LONG = """player,team,season,salary,option,guarantee,guaranteed
Pat Example,BOS,2026-27,30000000,,,45000000
Pat Example,BOS,2027-28,33000000,player,,45000000
Jose Ejemplo,BOS,2026-27,2500000,,none,
Sam Sample,NYK,2026-27,10000000,,,
Sam Sample,NYK,2027-28,11000000,,,
Sam Sample,NYK,2028-29,12000000,team,,
"""


class TestWideLayout:
    def test_tables_satisfy_their_contracts(self) -> None:
        result = build(WIDE)
        assert validate_frame(result.contracts, CONTRACTS) == []
        assert validate_frame(result.contract_years, CONTRACT_YEARS) == []
        assert result.rows_read == 3
        assert result.unmatched == []

    def test_one_contract_per_player(self) -> None:
        contracts = build(WIDE).contracts.set_index("player_id")
        pat = contracts.loc[1]
        assert pat["contract_id"] == f"1-{BOS}-2026-27"
        assert (pat["team_id"], pat["player_name"]) == (BOS, "Pat Example")
        assert (pat["contract_type"], pat["status"]) == ("standard", "active")
        assert (pat["first_season"], pat["last_season"], pat["seasons"]) == (
            "2026-27",
            "2027-28",
            2,
        )
        assert pat["total_salary"] == 63_000_000
        assert pat["guaranteed_amount"] == 45_000_000
        assert pat["source_label"] == "invented for tests"
        assert pat["as_of_date"] == pd.Timestamp("2026-10-01")
        assert pd.isna(contracts.loc[2, "guaranteed_amount"])
        assert contracts.loc[3, "total_salary"] == 33_000_000

    def test_each_season_carries_salary_cap_share_and_markers(self) -> None:
        years = build(WIDE).contract_years.set_index(["player_id", "season"])
        first, second = years.loc[(1, "2026-27")], years.loc[(1, "2027-28")]
        assert (first["salary"], first["salary_cap_pct"]) == (30_000_000, 0.30)
        assert second["salary_cap_pct"] == pytest.approx(0.30)  # 33M of a 110M cap
        assert pd.isna(first["option"]) and second["option"] == "player"
        assert (first["years_remaining"], second["years_remaining"]) == (1, 0)
        assert years.loc[(2, "2026-27"), "guarantee"] == "none"
        assert years.loc[(3, "2028-29"), "option"] == "team"
        assert years.loc[(3, "2026-27"), "years_remaining"] == 2

    def test_a_season_without_a_configured_cap_has_no_cap_share(self) -> None:
        years = build(WIDE).contract_years.set_index(["player_id", "season"])
        assert pd.isna(years.loc[(3, "2028-29"), "salary_cap_pct"])
        assert years.loc[(3, "2027-28"), "salary_cap_pct"] == pytest.approx(0.10)

    def test_blank_lines_and_a_byte_order_mark_are_tolerated(self) -> None:
        text = WIDE.replace("Jose Ejemplo", "\nJose Ejemplo") + ",,,,,\n"
        assert len(build(text).contracts) == 3

    def test_column_names_are_case_and_space_insensitive(self) -> None:
        text = WIDE.replace("player,team,", " Player , TEAM ,")
        assert len(build(text).contracts) == 3


class TestLongLayout:
    def test_gives_the_same_tables_as_the_wide_layout(self) -> None:
        wide, long = build(WIDE), build(LONG)
        pd.testing.assert_frame_equal(wide.contracts, long.contracts)
        pd.testing.assert_frame_equal(wide.contract_years, long.contract_years)
        assert long.rows_read == 6

    def test_spelled_out_markers_are_accepted(self) -> None:
        text = "player,team,season,salary,option,guarantee\nPat Example,BOS,2026-27,1M,Early Termination,Partial\n"
        year = build(text).contract_years.iloc[0]
        assert (year["option"], year["guarantee"]) == ("early_termination", "partial")


class TestContractShapes:
    def test_a_gap_between_seasons_separates_two_contracts(self) -> None:
        text = "player,team,2026-27,2027-28,2028-29\nPat Example,BOS,10M,,12M\n"
        contracts = build(text).contracts
        assert contracts["contract_id"].tolist() == [f"1-{BOS}-2026-27", f"1-{BOS}-2028-29"]
        assert contracts["seasons"].tolist() == [1, 1]

    def test_two_way_and_dead_money_rows(self) -> None:
        text = (
            "player,team,type,status,2026-27\n"
            "Pat Example,BOS,two-way,,600K\n"
            "Sam Sample,NYK,,dead,4M\n"
            "Sam Sample,BOS,,,2M\n"
        )
        contracts = build(text).contracts.set_index("contract_id")
        assert contracts.loc[f"1-{BOS}-2026-27-2w", "contract_type"] == "two_way"
        assert contracts.loc[f"3-{NYK}-2026-27-dead", "status"] == "dead_money"
        assert contracts.loc[f"3-{BOS}-2026-27", "status"] == "active"

    def test_a_row_without_a_team_is_kept_with_a_null_team(self) -> None:
        text = "player,2026-27\nPat Example,5M\n"
        contract = build(text).contracts.iloc[0]
        assert pd.isna(contract["team_id"])
        assert contract["contract_id"] == "1-0-2026-27"

    def test_teams_may_be_named_in_full_or_by_nickname(self) -> None:
        text = "player,team,2026-27\nPat Example,Boston Celtics,5M\nSam Sample,knicks,5M\n"
        assert build(text).contracts["team_id"].tolist() == [BOS, NYK]


class TestMatching:
    def test_accents_suffixes_and_punctuation_do_not_matter(self) -> None:
        text = "player,team,2026-27\nJose Ejemplo,BOS,1M\nSam Sample,NYK,1M\nDJ OTest,NYK,1M\n"
        result = build(text)
        assert result.unmatched == []
        assert sorted(result.contracts["player_id"]) == [2, 3, 4]

    def test_a_player_id_overrides_the_name(self) -> None:
        text = "player_id,player,team,2026-27\n3,Whatever Spelling,NYK,1M\n"
        assert build(text).contracts["player_id"].tolist() == [3]

    def test_a_file_may_identify_players_by_id_alone(self) -> None:
        text = "player_id,team,2026-27\n3,NYK,1M\n"
        contract = build(text).contracts.iloc[0]
        assert (contract["player_id"], contract["player_name"]) == (3, "player 3")

    def test_an_unknown_name_is_left_out_and_reported(self) -> None:
        text = "player,team,2026-27,2027-28\nNobody Atall,BOS,1M,1M\nPat Example,BOS,2M,\n"
        result = build(text)
        assert result.contracts["player_id"].tolist() == [1]
        assert result.unmatched == [
            UnmatchedRow(2, "Nobody Atall", "BOS", "no player with this name")
        ]
        assert result.rows_read == 2

    def test_an_unknown_player_id_is_left_out(self) -> None:
        text = "player_id,player,team,2026-27\n999,Pat Example,BOS,1M\n"
        result = build(text)
        assert len(result.contracts) == 0
        assert result.unmatched[0].reason == "player_id 999 is not a known player"

    def test_an_unknown_team_is_left_out(self) -> None:
        text = "player,team,2026-27\nPat Example,SEA,1M\n"
        assert build(text).unmatched[0].reason == "unknown team 'SEA'"

    def test_shared_names_resolve_to_the_active_player_on_the_named_team(self) -> None:
        text = "player,team,2026-27\nChris Common,BOS,1M\nChris Common,NYK,2M\n"
        result = build(text)
        assert result.unmatched == []
        assert result.contracts.set_index("team_id")["player_id"].to_dict() == {BOS: 6, NYK: 7}

    def test_shared_names_without_a_deciding_team_are_left_out(self) -> None:
        text = "player,2026-27\nChris Common,1M\n"
        result = build(text)
        assert len(result.contracts) == 0
        assert "3 players share this name; add a player_id column" in result.unmatched[0].reason

    def test_a_single_active_namesake_wins_over_a_retired_one(self) -> None:
        players = PLAYERS[PLAYERS["player_id"] != 7]
        text = "player,2026-27\nChris Common,1M\n"
        assert build(text, players=players).contracts["player_id"].tolist() == [6]

    def test_describe_unmatched(self) -> None:
        assert describe_unmatched([]) is None
        rows = [
            UnmatchedRow(2, "Nobody Atall", "BOS", "no player with this name"),
            UnmatchedRow(5, "Chris Common", None, "ambiguous"),
        ]
        assert describe_unmatched(rows) == (
            "2 contract file row(s) left out: line 2 Nobody Atall (BOS): no player with "
            "this name; line 5 Chris Common: ambiguous"
        )
        many = [UnmatchedRow(n, f"P{n}", None, "x") for n in range(40)]
        assert describe_unmatched(many).endswith("; and 15 more")


class TestFileErrors:
    @pytest.mark.parametrize(
        ("text", "message"),
        [
            ("", "no header row"),
            ("player,team\nPat Example,BOS\n", "no season columns"),
            ("player,team,season,salary,2026-27\n", "use one layout"),
            (
                "player,team,2026-2027\nPat Example,BOS,1M\n",
                r"\['2026-2027'\] look like seasons; write a season as both years, like 2026-27",
            ),
            ("player,team,2026-27,2027/28\nPat Example,BOS,1M,1M\n", "look like seasons"),
            ("player,team,2026\nPat Example,BOS,1M\n", "look like seasons"),
            ("player,team,salry,season\nPat Example,BOS,1M,2026-27\n", "unrecognised column"),
            ("team,2026-27\nBOS,1M\n", "needs a 'player' column"),
            ("player,team,season\nPat Example,BOS,2026-27\n", "needs a 'salary' column"),
            ("player,player,2026-27\nPat,Pat,1M\n", "repeats columns"),
            ("player,team,2026-27\n", "lists no salaries"),
            ("player,team,2026-27\nPat Example,BOS,\n", r"line 2 \(Pat Example\) lists no salary"),
            (
                "player,team,2026-27\nPat Example,BOS,lots\n",
                "line 2, column 2026-27: not a dollar amount",
            ),
            ("player,team,2026-27\nPat Example,BOS,1M XX\n", "unrecognised marker 'XX'"),
            (
                "player,team,2026-27\nPat Example,BOS,1M,extra\n",
                "line 2 has 4 values for 3 columns",
            ),
            ("player,team,2026-27\n,BOS,1M\n", "line 2 names no player"),
            ("player_id,2026-27\nabc,1M\n", "player_id 'abc' is not a number"),
            ("player,type,2026-27\nPat Example,loan,1M\n", "contract type 'loan'"),
            ("player,status,2026-27\nPat Example,injured,1M\n", "status 'injured'"),
            ("player,guaranteed,2026-27\nPat Example,most,1M\n", "line 2, guaranteed"),
            ("player,team,season,salary\nPat Example,BOS,2026,1M\n", "line 2: not a season label"),
            (
                "player,team,season,salary,option\nPat Example,BOS,2026-27,1M,maybe\n",
                "unrecognised option",
            ),
            (
                "player,team,season,salary,guarantee\nPat Example,BOS,2026-27,1M,ish\n",
                "unrecognised guarantee",
            ),
            ("player,team,2026-27\nPat Example,BOS,1000000.50\n", "whole dollars"),
        ],
    )
    def test_a_malformed_file_is_rejected_with_a_pointer(self, text: str, message: str) -> None:
        with pytest.raises(ContractFileError, match=message):
            build(text)

    def test_the_same_player_season_twice_is_rejected(self) -> None:
        text = "player,team,2026-27\nPat Example,BOS,1M\nPat Example,BOS,2M\n"
        with pytest.raises(ContractFileError, match="lines 2 and 3 both give Pat Example"):
            build(text)

    def test_differently_spelled_duplicates_are_still_caught(self) -> None:
        text = "player,team,2026-27\nJosé Ejemplo,BOS,1M\nJose Ejemplo,BOS,2M\n"
        with pytest.raises(ContractFileError, match="lines 2 and 3"):
            build(text)

    def test_a_malformed_snapshot_is_rejected(self) -> None:
        broken = snapshot("contracts", {"text": WIDE}, source="contract_file")
        with pytest.raises(ContractFileError, match="snapshot is malformed"):
            build_contracts(broken, players=PLAYERS, teams=TEAMS, caps=CAPS)

    def test_nothing_matched_gives_empty_conforming_tables(self) -> None:
        result = build("player,team,2026-27\nNobody Atall,BOS,1M\n")
        assert len(result.contracts) == 0 and len(result.contract_years) == 0
        assert validate_frame(result.contracts, CONTRACTS) == []
        assert tuple(result.contract_years.columns) == CONTRACT_YEARS.column_names


def test_the_as_of_date_is_carried_from_the_snapshot() -> None:
    payload = {"filename": "f.csv", "source_label": "s", "as_of": "2026-07-15", "text": WIDE}
    result = build_contracts(
        snapshot("contracts", payload, source="contract_file"),
        players=PLAYERS,
        teams=TEAMS,
        caps=CAPS,
    )
    assert set(result.contracts["as_of_date"]) == {pd.Timestamp(date(2026, 7, 15))}
