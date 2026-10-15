from __future__ import annotations

from pathlib import Path

import pytest

from front_office.config import ConfigError, load_assistant_settings
from front_office.config.assistant import OLLAMA_HOST_VARIABLE, assistant_settings_path
from front_office.domain.assistant import Mode, is_cloud_model, is_docker_url, is_loopback_url

REPO_CONFIGS = Path(__file__).resolve().parents[3] / "configs"

VALID = """\
version: 1
ollama:
  host: "{host}"
default_model: "{model}"
fallback_model: "qwen3:4b-instruct"
quick: {{context_tokens: 8192, think: false, max_output_tokens: 1024}}
deep: {{context_tokens: 8192, think: true, max_output_tokens: 3072}}
"""


def write(config_dir: Path, text: str) -> None:
    assistant_settings_path(config_dir).write_text(text, encoding="utf-8")


def test_the_shipped_settings_load_and_stay_local() -> None:
    settings = load_assistant_settings(REPO_CONFIGS)
    assert is_loopback_url(settings.ollama.host)
    assert not is_cloud_model(settings.default_model)
    assert settings.fallback_model is None or not is_cloud_model(settings.fallback_model)
    assert settings.mode(Mode.QUICK) is settings.quick
    assert settings.mode(Mode.DEEP) is settings.deep


def test_the_shipped_feeds_are_the_registers_and_every_team_has_one() -> None:
    """A7: Hoops Rumors alone, by the user's choice of 2026-10-10 - its general feed, its
    feed of moves, and each team's own."""
    news = load_assistant_settings(REPO_CONFIGS).news
    assert {feed.site for feed in news.feeds} == {"Hoops Rumors"}
    assert all(feed.url.startswith("https://www.hoopsrumors.com/") for feed in news.feeds)
    assert [feed.id for feed in news.general] == ["hoopsrumors", "hoopsrumors-transactions"]
    assert [feed.transactions for feed in news.general] == [False, True]
    assert len([feed for feed in news.feeds if feed.team]) == 30
    assert news.team_feed("BOS") is not None and news.team_feed("XYZ") is None


@pytest.mark.parametrize(
    ("feeds", "why"),
    [
        (
            '[{id: a, site: S, url: "http://example.org/feed"}]',
            "String should match pattern",
        ),
        (
            '[{id: a, site: S, url: "https://example.org/1"}, {id: a, site: S, url: "https://example.org/2"}]',
            "a feed id is listed twice",
        ),
        (
            '[{id: a, site: S, url: "https://example.org/1"}, {id: b, site: S, url: "https://example.org/1"}]',
            "a feed url is listed twice",
        ),
        (
            '[{id: a, site: S, team: BOS, url: "https://example.org/1"}, {id: b, site: S, team: BOS, url: "https://example.org/2"}]',
            "a team has two feeds",
        ),
    ],
)
def test_a_feed_list_that_cannot_be_right_is_refused(project: Path, feeds: str, why: str) -> None:
    text = (
        VALID.format(host="http://127.0.0.1:11434", model="qwen3:8b") + f"news:\n  feeds: {feeds}\n"
    )
    write(project / "configs", text)
    with pytest.raises(ConfigError, match=why):
        load_assistant_settings(project / "configs")


def test_an_address_off_this_machine_is_refused(project: Path) -> None:
    write(project / "configs", VALID.format(host="http://192.168.1.20:11434", model="qwen3:8b"))
    with pytest.raises(ConfigError, match="loopback"):
        load_assistant_settings(project / "configs")


def test_a_cloud_model_is_refused(project: Path) -> None:
    write(
        project / "configs", VALID.format(host="http://127.0.0.1:11434", model="gpt-oss:120b-cloud")
    )
    with pytest.raises(ConfigError, match="cloud model"):
        load_assistant_settings(project / "configs")


def test_there_is_no_field_for_a_key(project: Path) -> None:
    text = VALID.format(host="http://127.0.0.1:11434", model="qwen3:8b") + 'api_key: "secret"\n'
    write(project / "configs", text)
    with pytest.raises(ConfigError, match="api_key"):
        load_assistant_settings(project / "configs")


def test_a_context_length_is_bounded(project: Path) -> None:
    text = VALID.format(host="http://127.0.0.1:11434", model="qwen3:8b").replace(
        "context_tokens: 8192, think: false", "context_tokens: 512, think: false"
    )
    write(project / "configs", text)
    with pytest.raises(ConfigError, match="context_tokens"):
        load_assistant_settings(project / "configs")


@pytest.mark.parametrize(
    ("url", "local"),
    [
        ("http://127.0.0.1:11434", True),
        ("https://localhost", True),
        ("http://[::1]:11434", True),
        ("http://127.9.9.9", True),
        ("http://10.0.0.5:11434", False),
        ("http://0.0.0.0:11434", False),
        ("https://ollama.com", False),
        ("file:///etc/passwd", False),
        ("http://127.0.0.1:notaport", False),
        ("localhost:11434", False),
    ],
)
def test_loopback_addresses(url: str, local: bool) -> None:
    assert is_loopback_url(url) is local


@pytest.mark.parametrize(
    ("url", "docker"),
    [
        ("http://ollama:11434", True),
        ("http://OLLAMA:11434", True),
        ("https://host.docker.internal:11434", True),
        ("http://ollama.example.com:11434", False),
        ("http://127.0.0.1:11434", False),
        ("ftp://ollama:11434", False),
        ("ollama:11434", False),
    ],
)
def test_dockers_names(url: str, docker: bool) -> None:
    assert is_docker_url(url) is docker


class TestTheHostFromOutside:
    """``FOL_OLLAMA_HOST``, which Docker Compose sets (decision 0019)."""

    @pytest.mark.parametrize(
        "host",
        ["http://ollama:11434", "http://host.docker.internal:11434", "http://127.0.0.1:11500"],
    )
    def test_takes_the_place_of_the_files(
        self, project: Path, monkeypatch: pytest.MonkeyPatch, host: str
    ) -> None:
        monkeypatch.setenv(OLLAMA_HOST_VARIABLE, host)
        settings = load_assistant_settings(project / "configs")
        assert settings.ollama.host == host
        assert settings.ollama.timeout_seconds == 180  # the rest is the file's

    @pytest.mark.parametrize(
        "host", ["http://192.168.1.20:11434", "https://ollama.com", "http://my-ollama:11434"]
    )
    def test_is_held_to_the_same_rule(
        self, project: Path, monkeypatch: pytest.MonkeyPatch, host: str
    ) -> None:
        monkeypatch.setenv(OLLAMA_HOST_VARIABLE, host)
        with pytest.raises(ConfigError, match=OLLAMA_HOST_VARIABLE):
            load_assistant_settings(project / "configs")

    def test_left_empty_is_the_files(self, project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(OLLAMA_HOST_VARIABLE, " ")
        assert load_assistant_settings(project / "configs").ollama.host == "http://127.0.0.1:11434"


@pytest.mark.parametrize(
    ("name", "cloud"),
    [
        ("qwen3:8b", False),
        ("qwen3:4b-instruct", False),
        ("gemma4:cloud", True),
        ("gpt-oss:120b-cloud", True),
        ("deepseek-v3-cloud", True),
        ("Kimi-K2:Cloud", True),
    ],
)
def test_cloud_model_names(name: str, cloud: bool) -> None:
    assert is_cloud_model(name) is cloud
