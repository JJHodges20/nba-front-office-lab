"""``/auth``: register, sign in for a token, and use it (decision 0019)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient

from front_office.config import Settings
from front_office.server.app import create_app
from front_office.server.security import ALGORITHM, ISSUER, Tokens
from tests.unit.server.conftest import FAST, PASSWORD, SECRET, sign_in


class TestRegister:
    def test_a_new_user_is_returned_without_the_password(self, client: TestClient) -> None:
        response = client.post("/auth/register", json={"username": "Analyst", "password": PASSWORD})
        assert response.status_code == 201
        body = response.json()
        assert body["user_id"] == 1
        assert body["username"] == "analyst"
        assert set(body) == {"user_id", "username", "created_at"}
        assert PASSWORD not in response.text

    def test_a_name_taken_in_any_case_is_a_conflict(self, client: TestClient) -> None:
        client.post("/auth/register", json={"username": "analyst", "password": PASSWORD})
        response = client.post(
            "/auth/register", json={"username": "ANALYST", "password": "another passphrase"}
        )
        assert response.status_code == 409
        assert response.json() == {"detail": "The name analyst is taken."}

    @pytest.mark.parametrize(
        "body",
        [
            {"username": "ab", "password": PASSWORD},
            {"username": "two words", "password": PASSWORD},
            {"username": "analyst", "password": "short"},
            {"username": "analyst", "password": "é" * 40},  # 80 bytes: bcrypt reads 72
            {"username": "analyst"},
            {"username": "analyst", "password": PASSWORD, "admin": True},
            {"username": 7, "password": PASSWORD},
        ],
    )
    def test_pydantic_refuses_what_the_rules_do_not_allow(
        self, client: TestClient, body: dict
    ) -> None:
        response = client.post("/auth/register", json=body)
        assert response.status_code == 422
        assert response.json()["detail"]  # FastAPI says which field and why
        assert (
            client.post(
                "/auth/token", data={"username": "analyst", "password": PASSWORD}
            ).status_code
            == 401
        )


class TestSignIn:
    def test_a_token_names_its_user_and_expires(self, client: TestClient) -> None:
        client.post("/auth/register", json={"username": "analyst", "password": PASSWORD})
        response = client.post("/auth/token", data={"username": "analyst", "password": PASSWORD})
        assert response.status_code == 200
        body = response.json()
        assert body["token_type"] == "bearer"
        assert body["expires_in"] == 60 * 60
        claims = jwt.decode(body["access_token"], SECRET, algorithms=[ALGORITHM], issuer=ISSUER)
        assert claims["sub"] == "1"
        assert claims["exp"] - claims["iat"] == 60 * 60

    def test_the_docs_pages_authorize_form_is_accepted(self, client: TestClient) -> None:
        client.post("/auth/register", json={"username": "analyst", "password": PASSWORD})
        form = {
            "grant_type": "password",
            "username": "analyst",
            "password": PASSWORD,
            "scope": "",
            "client_id": "",
        }
        assert client.post("/auth/token", data=form).status_code == 200

    @pytest.mark.parametrize(
        ("username", "password"),
        [("analyst", "wrong passphrase"), ("nobody", PASSWORD), ("analyst", "x" * 100)],
    )
    def test_wrong_credentials_are_refused_alike(
        self, client: TestClient, username: str, password: str
    ) -> None:
        client.post("/auth/register", json={"username": "analyst", "password": PASSWORD})
        response = client.post("/auth/token", data={"username": username, "password": password})
        assert response.status_code == 401
        assert response.json() == {"detail": "Wrong name or password."}
        assert response.headers["WWW-Authenticate"] == "Bearer"

    def test_the_credentials_go_as_a_form_not_json(self, client: TestClient) -> None:
        response = client.post("/auth/token", json={"username": "analyst", "password": PASSWORD})
        assert response.status_code == 422


class TestTheToken:
    def test_me(self, client: TestClient, signed_in: dict) -> None:
        response = client.get("/auth/me", headers=signed_in)
        assert response.status_code == 200
        assert response.json()["username"] == "analyst"

    def test_no_token(self, client: TestClient) -> None:
        response = client.get("/auth/me")
        assert response.status_code == 401
        assert response.headers["WWW-Authenticate"] == "Bearer"

    def test_an_altered_token(self, client: TestClient, signed_in: dict) -> None:
        token = signed_in["Authorization"].removeprefix("Bearer ")
        header, payload, signature = token.split(".")
        forged = jwt.encode(
            {"sub": "2", "iss": ISSUER, "iat": 0, "exp": 2**31}, "another key " * 4, ALGORITHM
        )
        for altered in (
            f"{header}.{forged.split('.')[1]}.{signature}",  # someone else's claims
            forged,  # signed with another key
            # The signature's first character carries six bits of it, none of them padding.
            f"{header}.{payload}.{'B' if signature[0] == 'A' else 'A'}{signature[1:]}",
            "not a token",
        ):
            response = client.get("/auth/me", headers={"Authorization": f"Bearer {altered}"})
            assert response.status_code == 401, altered
            assert response.json() == {"detail": "The token is not valid. Sign in again."}

    def test_an_unsigned_token_is_refused(self, client: TestClient, signed_in: dict) -> None:
        unsigned = jwt.encode(
            {"sub": "1", "iss": ISSUER, "iat": 0, "exp": 2**31}, None, algorithm="none"
        )
        response = client.get("/auth/me", headers={"Authorization": f"Bearer {unsigned}"})
        assert response.status_code == 401

    def test_an_expired_token(self, client: TestClient) -> None:
        sign_in(client)
        two_hours_ago = datetime.now(UTC) - timedelta(hours=2)
        old = Tokens(SECRET, minutes=60, now=lambda: two_hours_ago).issue(1)
        response = client.get("/auth/me", headers={"Authorization": f"Bearer {old.token}"})
        assert response.status_code == 401
        assert response.json() == {"detail": "The sign-in has expired. Sign in again."}

    def test_a_token_from_another_issuer(self, client: TestClient) -> None:
        sign_in(client)
        moment = datetime.now(UTC)
        token = jwt.encode(
            {"sub": "1", "iss": "someone else", "iat": moment, "exp": moment + timedelta(hours=1)},
            SECRET,
            ALGORITHM,
        )
        response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401

    def test_a_token_lasts_as_long_as_the_setting_says(self, settings: Settings) -> None:
        brief = FAST.model_copy(
            update={"sign_in": FAST.sign_in.model_copy(update={"token_minutes": 5})}
        )
        with TestClient(create_app(settings, api=brief, secret=SECRET)) as client:
            client.post("/auth/register", json={"username": "analyst", "password": PASSWORD})
            body = client.post(
                "/auth/token", data={"username": "analyst", "password": PASSWORD}
            ).json()
        assert body["expires_in"] == 5 * 60

    def test_each_user_sees_only_themselves(self, client: TestClient) -> None:
        first = sign_in(client, "first")
        second = sign_in(client, "second")
        assert client.get("/auth/me", headers=first).json()["username"] == "first"
        assert client.get("/auth/me", headers=second).json()["username"] == "second"


class TestRemoveAccount:
    def test_the_account_goes_and_its_token_stops_working(
        self, client: TestClient, signed_in: dict
    ) -> None:
        response = client.delete("/auth/me", headers=signed_in)
        assert response.status_code == 200
        assert response.json() == {"username": "analyst", "questions_removed": 0}
        after = client.get("/auth/me", headers=signed_in)
        assert after.status_code == 401
        assert after.json() == {"detail": "The token's user no longer exists. Register again."}
        refused = client.post("/auth/token", data={"username": "analyst", "password": PASSWORD})
        assert refused.status_code == 401

    def test_a_new_user_with_the_old_name_is_not_signed_in_by_the_old_token(
        self, client: TestClient, signed_in: dict
    ) -> None:
        client.delete("/auth/me", headers=signed_in)
        sign_in(client)  # the same name again: a new user, with a new id
        assert client.get("/auth/me", headers=signed_in).status_code == 401

    def test_needs_a_token(self, client: TestClient) -> None:
        assert client.delete("/auth/me").status_code == 401
