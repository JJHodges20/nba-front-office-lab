from __future__ import annotations

from pathlib import Path

import pytest

from front_office.config import eras_path, load_eras
from front_office.config.settings import ConfigError
from front_office.domain.eras import EraSet
from front_office.domain.seasons import Season


@pytest.fixture(scope="module")
def shipped(repo_root: Path) -> EraSet:
    return load_eras(repo_root / "configs")


def test_the_shipped_eras_are_the_filters_the_roadmap_asks_for(shipped: EraSet) -> None:
    """All history, the last 5 or 10 seasons, the modern era, the Play-In era."""
    assert [era.key for era in shipped] == ["all", "last_10", "last_5", "modern", "play_in"]
    assert shipped.default.key == "all"
    assert (shipped["last_10"].latest_seasons, shipped["last_5"].latest_seasons) == (10, 5)
    assert shipped["play_in"].first_season == "2020-21"


def test_every_era_says_why_it_is_drawn_where_it_is(shipped: EraSet) -> None:
    for era in shipped:
        assert len(era.note) > 20, era.key
    assert "convention" in shipped["modern"].note


def test_the_shipped_eras_resolve_against_thirty_seasons(shipped: EraSet) -> None:
    on_record = [season.label for season in Season.span("1996-97", "2025-26")]
    counts = {era.key: len(era.seasons(on_record)) for era in shipped}
    assert counts == {"all": 30, "last_10": 10, "last_5": 5, "modern": 11, "play_in": 6}
    assert shipped["last_5"].seasons(on_record)[0] == "2021-22"


def test_the_file_is_in_the_config_directory(project: Path) -> None:
    assert eras_path(project / "configs") == project / "configs" / "eras.yaml"
    assert len(load_eras(project / "configs")) == 5


def test_a_missing_file_is_named(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="configuration file not found"):
        load_eras(tmp_path)


def test_an_invalid_file_is_reported_with_its_path(project: Path) -> None:
    path = project / "configs" / "eras.yaml"
    path.write_text(
        "eras:\n  - key: all\n    name: All\n  - key: all\n    name: Twice\n", encoding="utf-8"
    )
    with pytest.raises(ConfigError, match=r"invalid eras in .*eras\.yaml") as error:
        load_eras(project / "configs")
    assert "repeated: all" in str(error.value)


def test_a_file_without_eras_is_refused(project: Path) -> None:
    (project / "configs" / "eras.yaml").write_text("# nothing here\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="invalid eras"):
        load_eras(project / "configs")
