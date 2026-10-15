"""An API on a throwaway project, and a user signed in to it."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from front_office.config import Settings
from front_office.domain.api_settings import ApiSettings, SignInSettings
from front_office.server.app import create_app

SECRET = "a signing key for the tests, long enough for HS256"
PASSWORD = "a long passphrase"
# bcrypt's least work, for speed; the API's own setting is in configs/api.yaml.
FAST = ApiSettings(version=1, sign_in=SignInSettings(token_minutes=60, password_rounds=4))


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings, api=FAST, secret=SECRET)) as opened:
        yield opened


def sign_in(client: TestClient, username: str = "analyst", password: str = PASSWORD) -> dict:
    """Register (once) and sign in; the headers that carry the token."""
    client.post("/auth/register", json={"username": username, "password": password})
    response = client.post("/auth/token", data={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def signed_in(client: TestClient) -> dict:
    return sign_in(client)
