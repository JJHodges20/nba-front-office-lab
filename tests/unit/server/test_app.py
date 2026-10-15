"""The API as a whole: its health check, its pages, and a model on every endpoint."""

from __future__ import annotations

from fastapi.testclient import TestClient

from front_office import __version__
from front_office.config import Settings
from front_office.server.app import create_app
from tests.unit.server.conftest import FAST, SECRET

# Reached without a token; every other endpoint asks for one.
PUBLIC = {("GET", "/health"), ("POST", "/auth/register"), ("POST", "/auth/token")}


def operations(client: TestClient) -> dict[tuple[str, str], dict]:
    """Every endpoint, as the API publishes it at ``/openapi.json``."""
    schema = client.get("/openapi.json").json()
    return {
        (method.upper(), path): operation
        for path, item in schema["paths"].items()
        for method, operation in item.items()
    }


def test_health_needs_no_sign_in(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_the_docs_pages_are_served(client: TestClient) -> None:
    assert client.get("/docs").status_code == 200
    assert client.get("/redoc").status_code == 200
    schema = client.get("/openapi.json").json()
    assert schema["info"]["title"] == "NBA Front Office Lab API"
    assert "OAuth2PasswordBearer" in schema["components"]["securitySchemes"]


def test_every_endpoint_takes_and_answers_with_pydantic_models(client: TestClient) -> None:
    found = operations(client)
    assert len(found) >= 3
    for key, operation in found.items():
        success = next(code for code in operation["responses"] if code.startswith("2"))
        answer = operation["responses"][success]["content"]["application/json"]["schema"]
        assert answer["$ref"].startswith("#/components/schemas/"), key
        for kind, body in operation.get("requestBody", {}).get("content", {}).items():
            assert body["schema"]["$ref"].startswith("#/components/schemas/"), (key, kind)


def test_every_endpoint_but_the_public_ones_needs_a_token(client: TestClient) -> None:
    for key, operation in operations(client).items():
        guarded = {"OAuth2PasswordBearer": []} in operation.get("security", [])
        assert guarded is (key not in PUBLIC), key


def test_the_app_keeps_its_accounts_in_the_projects_data_folder(settings: Settings) -> None:
    with TestClient(create_app(settings, api=FAST, secret=SECRET)) as client:
        client.post("/auth/register", json={"username": "analyst", "password": "a passphrase"})
    assert settings.accounts_path.is_file()
    assert settings.accounts_path.parent == settings.data_dir / "api"
