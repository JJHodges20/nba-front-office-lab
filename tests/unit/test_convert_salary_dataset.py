"""The converter from the MrBridge salary table to the lab's contract-file layout.

Every row here is invented; the columns are the dataset's.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from scripts.convert_salary_dataset import (
    EXPECTED_COLUMNS,
    OUTPUT_COLUMNS,
    ConversionError,
    convert,
    convert_file,
    main,
)

SOURCE = "HoopsHype salaries GraphQL endpoint, accessed 2026-07-07"


def row(
    player: str,
    team: str,
    season: str,
    salary: int,
    *,
    player_id: str = "",
    two_way: bool = False,
    team_option: bool = False,
    player_option: bool = False,
    qualifying_offer: bool = False,
    terminated: bool = False,
) -> dict[str, str]:
    return {
        "season_year": season[:4],
        "season": season,
        "player_id": player_id,
        "player": player,
        "salary": str(salary),
        "team_id": "1",
        "team": team,
        "team_option": str(team_option),
        "player_option": str(player_option),
        "qualifying_offer": str(qualifying_offer),
        "two_way": str(two_way),
        "terminated": str(terminated),
        "notes": "",
        "source": SOURCE,
    }


def test_a_plain_row_becomes_a_long_layout_row() -> None:
    written, report = convert([row("Pat Example", "Boston Celtics", "2025-26", 30_000_000)])
    assert written == [
        {
            "player_id": "",
            "player": "Pat Example",
            "team": "Boston Celtics",
            "season": "2025-26",
            "salary": "30000000",
            "type": "",
            "option": "",
        }
    ]
    assert tuple(written[0]) == OUTPUT_COLUMNS
    assert report.rows_read == 1 and report.rows_written == 1
    assert report.seasons == {"2025-26": 1}
    assert not report.merges and not report.aliases and not report.ids and not report.flagged


def test_two_way_and_options_are_carried() -> None:
    written, _ = convert(
        [
            row("Sam Sample", "Boston Celtics", "2025-26", 600_000, two_way=True),
            row("Pat Example", "Boston Celtics", "2026-27", 1_000_000, team_option=True),
            row("Lee Longshot", "Boston Celtics", "2026-27", 2_000_000, player_option=True),
        ]
    )
    by_name = {item["player"]: item for item in written}
    assert by_name["Sam Sample"]["type"] == "two-way"
    assert by_name["Pat Example"]["option"] == "team"
    assert by_name["Lee Longshot"]["option"] == "player"


def test_two_stints_with_one_team_in_one_season_are_added_up() -> None:
    written, report = convert(
        [
            row("Pat Example", "Boston Celtics", "2025-26", 1_000_000, player_id="7"),
            row("Pat Example", "New York Knicks", "2025-26", 500_000, player_id="7"),
            row("Pat Example", "Boston Celtics", "2025-26", 250_000, player_id="7"),
        ]
    )
    assert [(item["team"], item["salary"]) for item in written] == [
        ("Boston Celtics", "1250000"),
        ("New York Knicks", "500000"),
    ]
    (merge,) = report.merges
    assert (merge.player, merge.team, merge.kind) == ("Pat Example", "Boston Celtics", "standard")
    assert merge.lines == (2, 4) and merge.salaries == (1_000_000, 250_000)
    assert merge.total == 1_250_000


def test_a_two_way_stint_and_a_standard_one_stay_apart() -> None:
    """A two-way contract converted to a standard one is two contracts in the lab."""
    written, report = convert(
        [
            row("Pat Example", "Miami Heat", "2022-23", 350_000, two_way=True),
            row("Pat Example", "Miami Heat", "2022-23", 35_000),
        ]
    )
    assert [(item["type"], item["salary"]) for item in written] == [
        ("two-way", "350000"),
        ("", "35000"),
    ]
    assert not report.merges


def test_the_snapshot_id_tells_two_spellings_of_one_player_apart() -> None:
    """The dataset writes one player under two names; its own id joins them."""
    written, report = convert(
        [
            row("Nate Sample", "Boston Celtics", "2024-25", 100, player_id="42"),
            row("Jeenathan Sample", "Boston Celtics", "2024-25", 50, player_id="42"),
        ]
    )
    assert len(written) == 1 and written[0]["salary"] == "150"
    assert len(report.merges) == 1


def test_aliases_and_league_ids_are_applied_and_reported() -> None:
    written, report = convert(
        [
            row("Patrick Example", "Boston Celtics", "2025-26", 100),
            row("Chris Common", "Boston Celtics", "2025-26", 200),
        ],
        aliases={"Patrick Example": "Pat Example"},
        player_ids={"Chris Common": 1_628_000},
    )
    by_name = {item["player"]: item for item in written}
    assert "Pat Example" in by_name and "Patrick Example" not in by_name
    assert by_name["Chris Common"]["player_id"] == "1628000"
    assert report.aliases == {"Patrick Example": 1} and report.ids == {"Chris Common": 1}


def test_flags_the_lab_cannot_carry_are_reported_not_dropped() -> None:
    written, report = convert(
        [
            row("Pat Example", "Boston Celtics", "2025-26", 100, qualifying_offer=True),
            row("Sam Sample", "Boston Celtics", "2025-26", 100, terminated=True),
        ]
    )
    assert len(written) == 2
    assert [(item.player, item.flag) for item in report.flagged] == [
        ("Pat Example", "qualifying_offer"),
        ("Sam Sample", "terminated"),
    ]


def test_rows_are_written_season_then_team_then_largest_salary_first() -> None:
    written, _ = convert(
        [
            row("A", "New York Knicks", "2026-27", 1),
            row("B", "Boston Celtics", "2026-27", 1),
            row("C", "Boston Celtics", "2026-27", 2),
            row("D", "Boston Celtics", "2025-26", 1),
        ]
    )
    assert [item["player"] for item in written] == ["D", "C", "B", "A"]


@pytest.mark.parametrize(
    ("bad", "message"),
    [
        (row("", "Boston Celtics", "2025-26", 1), "names no player"),
        (row("Pat Example", "", "2025-26", 1), "names no team"),
        (row("Pat Example", "Boston Celtics", "2025", 1), "not like 2025-26"),
        ({**row("Pat Example", "Boston Celtics", "2025-26", 1), "salary": "1.5M"}, "whole number"),
        (row("Pat Example", "Boston Celtics", "2025-26", -1), "negative"),
        (
            {**row("Pat Example", "Boston Celtics", "2025-26", 1), "two_way": "maybe"},
            "true or false",
        ),
    ],
)
def test_a_bad_row_is_rejected_with_its_line(bad: dict[str, str], message: str) -> None:
    with pytest.raises(ConversionError, match=f"line 3.*{message}"):
        convert([row("Sam Sample", "Boston Celtics", "2025-26", 1), bad])


def test_a_row_missing_a_column_is_rejected() -> None:
    short = row("Pat Example", "Boston Celtics", "2025-26", 1)
    del short["two_way"]
    with pytest.raises(ConversionError, match="lacks column"):
        convert([short])


def test_both_options_on_one_player_season_is_rejected() -> None:
    with pytest.raises(ConversionError, match="both a team and a player option"):
        convert(
            [
                row("Pat Example", "Boston Celtics", "2025-26", 1, team_option=True),
                row("Pat Example", "Boston Celtics", "2025-26", 1, player_option=True),
            ]
        )


def test_convert_file_reads_the_dataset_and_writes_the_lab_layout(tmp_path: Path) -> None:
    source = tmp_path / "player_salaries.csv"
    with open(source, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=sorted(EXPECTED_COLUMNS))
        writer.writeheader()
        writer.writerow(row("Pat Example", "Boston Celtics", "2025-26", 30_000_000))
        writer.writerow(row("Pat Example", "Boston Celtics", "2025-26", 1_000, two_way=True))
    output = tmp_path / "out" / "contracts.csv"

    assert main([str(source), str(output)]) == 0
    with open(output, encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert [tuple(item.values()) for item in rows] == [
        ("", "Pat Example", "Boston Celtics", "2025-26", "30000000", "", ""),
        ("", "Pat Example", "Boston Celtics", "2025-26", "1000", "two-way", ""),
    ]
    report = convert_file(source, output)
    assert "wrote 2 rows" in report.render(source, output)


def test_the_wrong_file_is_named(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    wrong = tmp_path / "team_payrolls.csv"
    wrong.write_text("season,team,payroll\n2025-26,Boston Celtics,1\n", encoding="utf-8")
    assert main([str(wrong), str(tmp_path / "out.csv")]) == 1
    assert "not the dataset" in capsys.readouterr().err
    assert not (tmp_path / "out.csv").exists()


def test_a_team_is_named_as_the_league_names_it() -> None:
    """The league's index calls the Clippers "LA Clippers"; the dataset writes the city out."""
    written, _ = convert(
        [
            row("Pat Example", "Los Angeles Clippers", "2025-26", 1),
            row("Sam Sample", "Los Angeles Lakers", "2025-26", 1),
        ]
    )
    assert [item["team"] for item in written] == ["LA Clippers", "Los Angeles Lakers"]
    written, _ = convert(
        [row("Pat Example", "Los Angeles Clippers", "2025-26", 1)], team_aliases={}
    )
    assert written[0]["team"] == "Los Angeles Clippers"


def test_a_left_out_player_is_not_written_and_is_reported_with_the_reason() -> None:
    written, report = convert(
        [
            row("Pat Example", "Boston Celtics", "2017-18", 46_079),
            row("Sam Sample", "Boston Celtics", "2017-18", 1),
        ],
        left_out={"Pat Example": "played no NBA game"},
    )
    assert [item["player"] for item in written] == ["Sam Sample"]
    (left,) = report.left_out
    assert (left.line, left.player, left.salary, left.reason) == (
        2,
        "Pat Example",
        46_079,
        "played no NBA game",
    )
    assert report.rows_read == 2 and report.rows_written == 1
    assert "1 row(s) left out" in report.render(Path("a.csv"), Path("b.csv"))


def test_the_shipped_lists_name_real_differences_only() -> None:
    """An alias that changes nothing, or an id for a name also aliased, is a slip."""
    from scripts.convert_salary_dataset import ALIASES, LEFT_OUT, PLAYER_IDS, TEAM_ALIASES

    assert all(name != league for name, league in ALIASES.items())
    assert all(name != league for name, league in TEAM_ALIASES.items())
    assert not set(ALIASES) & set(PLAYER_IDS)
    assert not set(LEFT_OUT) & (set(ALIASES) | set(PLAYER_IDS))
    assert all(league_id > 0 for league_id in PLAYER_IDS.values())
