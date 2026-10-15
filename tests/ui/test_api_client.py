"""The workbench's one way to the network: the lab's own API, at the address it is given."""

from __future__ import annotations

import pytest

from wb import api_client
from wb.api_client import connect as real_connect


class Recorded:
    """A way out that answers from a script and records where each request went."""

    def __init__(self, status: int = 200, body: object = None) -> None:
        self.status = status
        self.body = {} if body is None else body
        self.sent: list[tuple[str, str, dict]] = []

    def __call__(self, method: str, url: str, **kwargs: object) -> tuple[int, object]:
        self.sent.append((method, url, kwargs))
        return self.status, self.body


def test_the_address_is_the_environments_or_this_machines(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(api_client.API_URL, raising=False)
    assert real_connect().base_url == "http://127.0.0.1:8000"
    monkeypatch.setenv(api_client.API_URL, "http://api:8000")
    assert real_connect().base_url == "http://api:8000"


@pytest.mark.parametrize("address", ["file:///etc/passwd", "ftp://api", "api:8000", "http://"])
def test_only_an_http_address_is_taken(monkeypatch: pytest.MonkeyPatch, address: str) -> None:
    monkeypatch.setenv(api_client.API_URL, address)
    with pytest.raises(ValueError, match="http address"):
        real_connect()


def test_a_request_goes_to_the_api_with_the_token() -> None:
    sent = Recorded(body={"questions": []})
    api = api_client.LabApi("http://api:8000/", send=sent)
    assert api.questions("tok", limit=5) == {"questions": []}
    method, url, kwargs = sent.sent[0]
    assert (method, url) == ("GET", "http://api:8000/rag/questions")
    assert kwargs["headers"] == {"Authorization": "Bearer tok"}
    assert kwargs["params"] == {"limit": 5}
    assert kwargs["timeout"] == api_client.TIMEOUT_SECONDS


def test_signing_in_sends_a_form_and_no_token() -> None:
    sent = Recorded(body={"access_token": "t", "token_type": "bearer", "expires_in": 3600})
    api_client.LabApi("http://api:8000", send=sent).sign_in("analyst", "secret words")
    _, url, kwargs = sent.sent[0]
    assert url.endswith("/auth/token")
    assert kwargs["data"] == {"username": "analyst", "password": "secret words"}
    assert kwargs["headers"] == {}


def test_a_refusal_carries_the_apis_words() -> None:
    api = api_client.LabApi(
        "http://api:8000", send=Recorded(409, {"detail": "The name x is taken."})
    )
    with pytest.raises(api_client.ApiError, match="The name x is taken.") as raised:
        api.register("x", "y")
    assert raised.value.status == 409


def test_a_validation_error_names_its_field() -> None:
    body = {
        "detail": [
            {
                "loc": ["body", "password"],
                "msg": "Value error, a password needs at least 8 characters",
            }
        ]
    }
    api = api_client.LabApi("http://api:8000", send=Recorded(422, body))
    with pytest.raises(api_client.ApiError) as raised:
        api.register("analyst", "short")
    assert raised.value.detail == "password: a password needs at least 8 characters"


def test_a_token_refused_means_signed_out() -> None:
    api = api_client.LabApi(
        "http://api:8000", send=Recorded(401, {"detail": "The sign-in has expired. Sign in again."})
    )
    with pytest.raises(api_client.SignedOut, match="expired"):
        api.me("old token")


def test_nothing_answering() -> None:
    def refused(method: str, url: str, **kwargs: object) -> tuple[int, object]:
        raise api_client.ApiUnreachable(f"Nothing answered at {url}")

    with pytest.raises(api_client.ApiUnreachable):
        api_client.LabApi("http://api:8000", send=refused).health()
