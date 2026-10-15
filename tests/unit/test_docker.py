"""The Docker files (decision 0019), held to the code they run.

Nothing here starts Docker: the files are read as text and YAML, and each setting is checked
against the code that reads it - the names of the environment variables, the models the lab
uses, the version of Python the suite runs on, the rule for where the model may be.
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

import pytest
import yaml

from front_office.config import load_api_settings, load_assistant_settings
from front_office.config.assistant import OLLAMA_HOST_VARIABLE
from front_office.config.settings import ENV_HOME
from front_office.domain.assistant import is_docker_url
from front_office.providers.web import KEY_VARIABLE
from front_office.server.security import SECRET_VARIABLE
from wb import api_client

REPO = Path(__file__).resolve().parents[2]
COMPOSE = yaml.safe_load((REPO / "compose.yaml").read_text(encoding="utf-8"))
SERVICES = COMPOSE["services"]
DOCKERFILE = (REPO / "Dockerfile").read_text(encoding="utf-8")
VERSION = re.compile(r"^\d+\.\d+\.\d+$")


def _command(service: str) -> str:
    command = SERVICES[service]["command"]
    return " ".join(command) if isinstance(command, list) else str(command)


def test_one_command_runs_the_api_the_workbench_and_ollama() -> None:
    assert set(SERVICES) == {"ollama", "models", "api", "ui"}
    assert SERVICES["ui"]["depends_on"]["api"]["condition"] == "service_healthy"
    assert SERVICES["api"]["depends_on"]["models"]["condition"] == "service_completed_successfully"
    assert SERVICES["models"]["depends_on"]["ollama"]["condition"] == "service_healthy"


def test_ports_are_published_on_this_machine_only() -> None:
    published = {name: service.get("ports", []) for name, service in SERVICES.items()}
    assert published == {
        "ollama": [],
        "models": [],
        "api": ["127.0.0.1:${FOL_API_PORT:-8000}:8000"],
        "ui": ["127.0.0.1:${FOL_UI_PORT:-8501}:8501"],
    }


def test_the_workbench_listens_inside_its_container_only_for_the_published_port() -> None:
    assert "--server.address=0.0.0.0" in _command("ui")
    assert "--host 0.0.0.0 --port 8000" in _command("api")


def test_the_api_serves_the_app_factory_after_indexing_the_documents() -> None:
    command = _command("api")
    assert command.index("fol rag index") < command.index(
        "uvicorn front_office.server.app:create_app --factory"
    )


def test_every_image_is_pinned() -> None:
    for name in ("ollama", "models"):
        image, _, tag = SERVICES[name]["image"].partition(":")
        assert image == "ollama/ollama" and VERSION.match(tag), name
    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert SERVICES["api"]["image"] == f"nba-front-office-lab:{project['version']}"
    assert SERVICES["ui"]["image"] == SERVICES["api"]["image"]


def test_the_image_runs_the_python_and_the_packages_the_suite_ran() -> None:
    (base,) = re.findall(r"^FROM python:(\S+)$", DOCKERFILE, flags=re.MULTILINE)
    version = base.removesuffix("-slim")
    assert VERSION.match(version), base
    assert version.split(".")[:2] == [str(sys.version_info.major), str(sys.version_info.minor)]
    assert "RUN pip install -r requirements.txt" in DOCKERFILE
    assert "RUN pip install --no-deps ." in DOCKERFILE
    assert "USER lab" in DOCKERFILE  # not root


def test_the_models_pulled_are_the_ones_the_lab_uses() -> None:
    pulled = re.findall(r"ollama pull (\S+)", _command("models"))
    configs = REPO / "configs"
    assert pulled == [
        load_api_settings(configs).rag.embedding_model,
        load_assistant_settings(configs).default_model,
    ]


def test_the_settings_are_the_names_the_code_reads() -> None:
    api_env = SERVICES["api"]["environment"]
    ui_env = SERVICES["ui"]["environment"]
    assert {ENV_HOME, OLLAMA_HOST_VARIABLE, SECRET_VARIABLE} == set(api_env)
    assert {ENV_HOME, OLLAMA_HOST_VARIABLE, api_client.API_URL, KEY_VARIABLE} == set(ui_env)
    assert api_env[ENV_HOME] == ui_env[ENV_HOME] == "/app"
    assert ui_env[api_client.API_URL] == "http://api:8000"


@pytest.mark.parametrize("service", ["api", "ui", "models"])
def test_the_model_is_found_where_the_lab_allows(service: str) -> None:
    """The default address is the Compose file's own Ollama, one of the two Docker names the
    lab accepts besides this machine's own."""
    default = re.fullmatch(
        r"\$\{FOL_OLLAMA_HOST:-(.+)\}", SERVICES[service]["environment"][OLLAMA_HOST_VARIABLE]
    )
    assert default is not None and default.group(1) == "http://ollama:11434"
    assert is_docker_url(default.group(1))


def test_the_keys_come_from_your_env_file_and_are_never_written_here() -> None:
    assert SERVICES["api"]["environment"][SECRET_VARIABLE] == "${FOL_API_SECRET:-}"
    assert SERVICES["ui"]["environment"][KEY_VARIABLE] == "${FOL_OLLAMA_API_KEY:-}"


def test_your_data_is_mounted_and_never_built_in() -> None:
    for name in ("api", "ui"):
        assert SERVICES[name]["volumes"] == ["${FOL_DOCKER_DATA:-./data}:/app/data"], name
    ignored = (REPO / ".dockerignore").read_text(encoding="utf-8").split()
    assert {"data", ".env", ".venv", ".git", "*.sqlite", ".streamlit/secrets.toml"} <= set(ignored)
    assert not re.search(r"^COPY .*(data|\.env)", DOCKERFILE, flags=re.MULTILINE)
