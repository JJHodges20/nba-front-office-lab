"""``configs/api.yaml``: the API's settings, with no room for a key."""

from __future__ import annotations

from pathlib import Path

import pytest

from front_office.config import ConfigError, api_settings_path, load_api_settings


def test_the_shipped_settings(project: Path) -> None:
    api = load_api_settings(project / "configs")
    assert api.version == 1
    assert api.sign_in.token_minutes == 60
    assert api.sign_in.password_rounds == 12


def _write(project: Path, text: str) -> Path:
    path = api_settings_path(project / "configs")
    path.write_text(text, encoding="utf-8")
    return project / "configs"


def test_a_key_cannot_be_kept_in_the_file(project: Path) -> None:
    configs = _write(project, "version: 1\nsecret: abc\n")
    with pytest.raises(ConfigError, match="secret"):
        load_api_settings(configs)


@pytest.mark.parametrize(
    "sign_in", ["token_minutes: 0", "password_rounds: 3", "password_rounds: 17"]
)
def test_limits(project: Path, sign_in: str) -> None:
    configs = _write(project, f"version: 1\nsign_in:\n  {sign_in}\n")
    with pytest.raises(ConfigError, match="invalid API settings"):
        load_api_settings(configs)
