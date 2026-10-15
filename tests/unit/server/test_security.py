"""The key that signs the API's tokens: the user's own, or one made once and kept."""

from __future__ import annotations

from pathlib import Path

import pytest

from front_office.config import ConfigError, Settings
from front_office.server.security import (
    KEY_FILE,
    SECRET_MIN_BYTES,
    SECRET_VARIABLE,
    TokenRefused,
    Tokens,
    signing_secret,
)

OWN_KEY = "the user's own signing key, kept in their environment"


def test_the_environment_comes_first(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    (settings.project_root / ".env").write_text(
        f"{SECRET_VARIABLE}=a key in the file, which the environment overrides\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(SECRET_VARIABLE, OWN_KEY)
    assert signing_secret(settings) == OWN_KEY
    assert not (settings.api_dir / KEY_FILE).exists()


def test_then_the_projects_env_file(settings: Settings) -> None:
    (settings.project_root / ".env").write_text(
        f"FOL_OLLAMA_API_KEY=\n{SECRET_VARIABLE}={OWN_KEY}\n", encoding="utf-8"
    )
    assert signing_secret(settings) == OWN_KEY
    assert not (settings.api_dir / KEY_FILE).exists()


def test_otherwise_a_key_is_made_once_and_kept(settings: Settings) -> None:
    (settings.project_root / ".env").write_text(f"{SECRET_VARIABLE}=\n", encoding="utf-8")
    made = signing_secret(settings)
    path = settings.api_dir / KEY_FILE
    assert path.read_text(encoding="utf-8").strip() == made
    assert len(made.encode()) >= SECRET_MIN_BYTES
    assert signing_secret(settings) == made  # kept: tokens survive a restart


def test_each_project_makes_its_own_key(tmp_path: Path, settings: Settings) -> None:
    other = settings.model_copy(update={"data_dir": tmp_path / "other"})
    assert signing_secret(settings) != signing_secret(other)


def test_a_short_key_is_refused(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(SECRET_VARIABLE, "too short")
    with pytest.raises(ConfigError, match=f"at least {SECRET_MIN_BYTES} characters"):
        signing_secret(settings)
    monkeypatch.delenv(SECRET_VARIABLE)
    path = settings.api_dir / KEY_FILE
    path.parent.mkdir(parents=True)
    path.write_text("short\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="no usable signing key"):
        signing_secret(settings)


def test_tokens_never_show_their_key() -> None:
    tokens = Tokens(OWN_KEY, minutes=60)
    assert OWN_KEY not in repr(tokens)
    with pytest.raises(ValueError, match="at least"):
        Tokens("short", minutes=60)


def test_a_token_reads_back_to_its_user() -> None:
    tokens = Tokens(OWN_KEY, minutes=60)
    assert tokens.user_id(tokens.issue(42).token) == 42
    with pytest.raises(TokenRefused):
        Tokens(OWN_KEY + "!", minutes=60).user_id(tokens.issue(42).token)


def test_the_template_names_every_key_with_no_value(repo_root: Path) -> None:
    """``.env.example`` is committed: a value there would be a key published."""
    lines = (repo_root / ".env.example").read_text(encoding="utf-8").splitlines()
    settings_named = [line for line in lines if "=" in line and not line.startswith("#")]
    assert f"{SECRET_VARIABLE}=" in settings_named
    assert all(line.endswith("=") for line in settings_named), settings_named
