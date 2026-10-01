from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from front_office.providers import contract_file
from front_office.providers.contract_file import read_contract_file
from front_office.providers.nba_stats import ProviderError

NOW = datetime(2026, 10, 1, 15, 30, tzinfo=UTC)
TEXT = "player,team,2026-27\nPat Example,BOS,1000000\n"


def read(path: Path, **kwargs):
    arguments = {
        "source_label": "my own spreadsheet",
        "as_of": date(2026, 9, 30),
        "now": lambda: NOW,
    }
    arguments.update(kwargs)
    return read_contract_file(path, **arguments)


def test_the_file_text_is_returned_unchanged_with_what_the_user_said_about_it(
    tmp_path: Path,
) -> None:
    path = tmp_path / "contracts.csv"
    path.write_text(TEXT, encoding="utf-8")
    snapshot = read(path)
    assert snapshot.source == "contract_file"
    assert snapshot.dataset == "contracts"
    assert snapshot.partition == {}
    assert snapshot.fetched_at == NOW
    assert snapshot.payload == {
        "filename": "contracts.csv",
        "source_label": "my own spreadsheet",
        "as_of": "2026-09-30",
        "text": TEXT,
    }
    assert snapshot.request == {"path": str(path)}


def test_excels_byte_order_mark_is_dropped(tmp_path: Path) -> None:
    path = tmp_path / "contracts.csv"
    path.write_text(TEXT, encoding="utf-8-sig")
    assert read(path).payload["text"] == TEXT


def test_accented_names_survive(tmp_path: Path) -> None:
    path = tmp_path / "contracts.csv"
    path.write_text("player,2026-27\nNikola Vučević,1\n", encoding="utf-8")
    assert "Vučević" in read(path).payload["text"]


def test_the_source_label_is_trimmed_and_required(tmp_path: Path) -> None:
    path = tmp_path / "contracts.csv"
    path.write_text(TEXT, encoding="utf-8")
    assert read(path, source_label="  team sheet  ").payload["source_label"] == "team sheet"
    with pytest.raises(ProviderError, match="where the contract figures came from"):
        read(path, source_label="   ")


def test_a_missing_file_is_reported(tmp_path: Path) -> None:
    with pytest.raises(ProviderError, match="contract file not found"):
        read(tmp_path / "nope.csv")


def test_a_directory_is_not_a_file(tmp_path: Path) -> None:
    with pytest.raises(ProviderError, match="not found"):
        read(tmp_path)


def test_an_empty_file_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "contracts.csv"
    path.write_bytes(b"")
    with pytest.raises(ProviderError, match="is empty"):
        read(path)


def test_a_file_in_another_encoding_explains_how_to_save_it(tmp_path: Path) -> None:
    path = tmp_path / "contracts.csv"
    path.write_bytes("player,2026-27\nNikola Vučević,1\n".encode("cp1250"))
    with pytest.raises(ProviderError, match="CSV UTF-8"):
        read(path)


def test_an_implausibly_large_file_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(contract_file, "MAX_FILE_BYTES", 10)
    path = tmp_path / "contracts.csv"
    path.write_text(TEXT, encoding="utf-8")
    with pytest.raises(ProviderError, match="implausibly large"):
        read(path)
