"""Importing a contract file, against a private copy of the fixture store.

Salaries here are invented round numbers attached to fixture players by id; they are
test data, not anyone's actual contract.
"""

from __future__ import annotations

import csv
import shutil
from datetime import date
from pathlib import Path

import pytest

from front_office.config import Settings
from front_office.domain.datasets import CONTRACT_FILE, CONTRACT_FILE_DATASET
from front_office.pipelines.check import check_store
from front_office.pipelines.contracts import (
    ContractImportError,
    import_contract_file,
    write_contract_template,
)
from front_office.pipelines.normalize import normalize
from front_office.rawstore import RawStore
from tests.conftest import FIXTURE_RAW

BOS, NYK = 1610612738, 1610612752
TATUM, ANUNOBY = 1628369, 1628384
TODAY = date(2026, 10, 1)


@pytest.fixture
def lab(settings: Settings) -> Settings:
    """A throwaway project whose raw store is a copy of the fixture store."""
    shutil.copytree(FIXTURE_RAW, settings.raw_dir)
    return settings


def write(directory: Path, text: str, name: str = "contracts.csv") -> Path:
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path


def invented_file(directory: Path) -> Path:
    return write(
        directory,
        "player_id,player,team,2026-27,2027-28,2028-29\n"
        f"{TATUM},Jayson Tatum,BOS,40000000,44000000,48000000 PO\n"
        f"{ANUNOBY},OG Anunoby,NYK,30000000,,\n"
        ",Nobody Atall,BOS,1000000,,\n",
    )


def stored_imports(settings: Settings) -> int:
    return len(RawStore(settings.raw_dir).versions(CONTRACT_FILE, CONTRACT_FILE_DATASET, {}))


class TestImport:
    def test_a_valid_file_is_stored_and_reported(self, lab: Settings, tmp_path: Path) -> None:
        report = import_contract_file(
            lab, invented_file(tmp_path), source_label="invented for tests", as_of=TODAY
        )
        assert report.stored
        assert (report.rows_read, report.contracts, report.players) == (3, 2, 2)
        assert report.contract_years == 4
        assert report.seasons == ("2026-27", "2027-28", "2028-29")
        assert report.seasons_without_cap == ("2027-28", "2028-29")
        assert [(row.line, row.player) for row in report.unmatched] == [(4, "Nobody Atall")]
        assert stored_imports(lab) == 1

    def test_the_stored_file_feeds_the_next_build(self, lab, tmp_path, season_rules) -> None:
        import_contract_file(
            lab, invented_file(tmp_path), source_label="invented for tests", as_of=TODAY
        )
        result = normalize(RawStore(lab.raw_dir), season_rules=season_rules)
        assert result.errors == []
        years = result["contract_years"].set_index(["player_id", "season"])
        cap = next(rules.salary_cap for rules in season_rules if rules.season == "2026-27")
        assert years.loc[(TATUM, "2026-27"), "salary_cap_pct"] == pytest.approx(40_000_000 / cap)
        assert years.loc[(TATUM, "2028-29"), "option"] == "player"
        assert result["contracts"].set_index("player_id").loc[ANUNOBY, "team_id"] == NYK
        note = result.notes[-1]
        assert (note.table, note.scope) == ("contracts", "all seasons")
        assert "1 contract file row(s) left out: line 4 Nobody Atall (BOS)" in note.message

    def test_importing_the_same_file_again_stores_nothing_new(self, lab, tmp_path) -> None:
        path = invented_file(tmp_path)
        import_contract_file(lab, path, source_label="invented for tests", as_of=TODAY)
        again = import_contract_file(lab, path, source_label="invented for tests", as_of=TODAY)
        assert not again.stored
        assert stored_imports(lab) == 1

    def test_a_changed_file_is_stored_as_a_new_version(self, lab, tmp_path) -> None:
        import_contract_file(lab, invented_file(tmp_path), source_label="invented", as_of=TODAY)
        changed = write(tmp_path, f"player_id,team,2026-27\n{TATUM},BOS,41000000\n", "v2.csv")
        report = import_contract_file(lab, changed, source_label="invented", as_of=TODAY)
        assert report.stored
        assert stored_imports(lab) == 2
        latest = normalize(RawStore(lab.raw_dir))["contract_years"]
        assert latest["salary"].tolist() == [41_000_000]

    def test_a_malformed_file_is_refused_and_nothing_is_stored(self, lab, tmp_path) -> None:
        bad = write(tmp_path, "player,team,2026-27\nJayson Tatum,BOS,lots\n")
        with pytest.raises(ContractImportError, match="line 2, column 2026-27"):
            import_contract_file(lab, bad, source_label="invented", as_of=TODAY)
        assert stored_imports(lab) == 0

    def test_a_file_matching_nobody_is_refused(self, lab, tmp_path) -> None:
        nobody = write(tmp_path, "player,team,2026-27\nNobody Atall,BOS,1000000\n")
        with pytest.raises(ContractImportError, match="none of the 1 row"):
            import_contract_file(lab, nobody, source_label="invented", as_of=TODAY)
        assert stored_imports(lab) == 0

    def test_a_missing_file_is_refused(self, lab, tmp_path) -> None:
        with pytest.raises(ContractImportError, match="contract file not found"):
            import_contract_file(lab, tmp_path / "nope.csv", source_label="x", as_of=TODAY)

    def test_league_data_must_be_ingested_first(self, settings: Settings, tmp_path) -> None:
        with pytest.raises(
            ContractImportError, match="no league data has been ingested; run: fol ingest"
        ):
            import_contract_file(
                settings, invented_file(tmp_path), source_label="invented", as_of=TODAY
            )

    def test_players_are_matched_by_name_when_no_id_is_given(self, lab, tmp_path) -> None:
        path = write(tmp_path, "player,team,2026-27\nNikola Vucevic,BOS,5000000\n")
        report = import_contract_file(lab, path, source_label="invented", as_of=TODAY)
        assert report.unmatched == ()
        contracts = normalize(RawStore(lab.raw_dir))["contracts"]
        assert contracts["player_id"].tolist() == [202696]


class TestQualityOfImportedContracts:
    def test_a_sparse_file_passes_the_error_checks_and_warns_about_coverage(
        self, lab, tmp_path, season_rules
    ) -> None:
        import_contract_file(lab, invented_file(tmp_path), source_label="invented", as_of=TODAY)
        report = check_store(RawStore(lab.raw_dir), season_rules)
        by_name = {check.check: check for check in report.checks}
        for name in (
            "contracts.totals_match_years",
            "contract_years.cap_shares_are_consistent",
            "contract_years.one_active_contract_per_player_team_season",
            "contract_years.salaries_are_plausible",
            "contracts.player_id_exists",
            "contract_years.contract_id_exists",
        ):
            assert by_name[name].passed, (name, by_name[name].examples)
        coverage = by_name["contract_years.teams_have_plausible_rosters"]
        assert coverage.failures == 30  # two players do not make thirty rosters
        assert coverage.examined == 30


class TestTemplate:
    def test_lists_every_rostered_player_with_blank_salaries(self, lab: Settings) -> None:
        path, players = write_contract_template(lab, today=TODAY)
        assert path == lab.imports_dir / "contract_template.csv"
        with open(path, encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.reader(handle))
        header, body = rows[0], rows[1:]
        assert header == [
            "player_id",
            "player",
            "team",
            "type",
            "2026-27",
            "2027-28",
            "2028-29",
            "2029-30",
            "2030-31",
            "2031-32",
            "guaranteed",
        ]
        assert len(body) == players > 0
        assert all(row[4:] == [""] * 7 for row in body)
        by_id = {int(row[0]): row for row in body}
        assert by_id[TATUM][1:3] == ["Jayson Tatum", "BOS"]
        assert [row[2] for row in body] == sorted(row[2] for row in body)

    def test_lists_only_players_who_are_on_a_team_now(self, lab: Settings) -> None:
        path, players = write_contract_template(lab, today=TODAY)
        with open(path, encoding="utf-8-sig", newline="") as handle:
            listed = {int(row[0]) for row in list(csv.reader(handle))[1:]}
        index = normalize(RawStore(lab.raw_dir))["players"]
        on_a_team = set(index.loc[index["current_team_id"].notna(), "player_id"])
        retired = set(index.loc[~index["is_active"], "player_id"])
        assert retired, "the fixture should include retired players"
        assert listed == on_a_team
        assert not listed & retired
        assert players == len(on_a_team)

    def test_has_a_byte_order_mark_so_excel_shows_accents(self, lab: Settings) -> None:
        path, _ = write_contract_template(lab, today=TODAY)
        assert path.read_bytes().startswith(b"\xef\xbb\xbf")
        assert "Vučević" in path.read_text(encoding="utf-8-sig")

    def test_seasons_start_at_the_current_league_year(self, lab: Settings, tmp_path) -> None:
        path, _ = write_contract_template(
            lab, today=date(2026, 6, 30), output=tmp_path / "t.csv", seasons=2
        )
        header = path.read_text(encoding="utf-8-sig").splitlines()[0].split(",")
        assert header[4:6] == ["2025-26", "2026-27"]

    def test_a_filled_in_template_imports(self, lab: Settings) -> None:
        path, _ = write_contract_template(lab, today=TODAY)
        with open(path, encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.reader(handle))
        # Fill one invented salary for every player; leave everything else blank.
        for row in rows[1:]:
            row[4] = "2000000"
        with open(path, "w", encoding="utf-8-sig", newline="") as handle:
            csv.writer(handle).writerows(rows)
        report = import_contract_file(lab, path, source_label="invented", as_of=TODAY)
        assert report.unmatched == ()
        assert report.contracts == len(rows) - 1

    def test_league_data_must_be_ingested_first(self, settings: Settings) -> None:
        with pytest.raises(ContractImportError, match="run: fol ingest"):
            write_contract_template(settings, today=TODAY)
