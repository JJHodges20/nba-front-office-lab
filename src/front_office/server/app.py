"""The lab's HTTP API (decision 0019): ``create_app`` builds it.

Run it with ``fol api``, or as uvicorn's factory - ``uvicorn
front_office.server.app:create_app --factory`` - which is what Docker Compose does. Its
pages: ``/docs`` (every endpoint, tried in the browser) and ``/redoc``.
"""

from __future__ import annotations

from fastapi import APIRouter, FastAPI

from front_office import __version__
from front_office.config.api import load_api_settings
from front_office.config.settings import Settings, load_settings
from front_office.domain.api_settings import ApiSettings
from front_office.server import auth, rag
from front_office.server.schemas import Health
from front_office.server.security import Tokens, signing_secret
from front_office.server.state import ServerState
from front_office.services.accounts import AccountService

DESCRIPTION = """\
The NBA Front Office Lab's API. Register, sign in for a token, then send the token with
every request: `Authorization: Bearer <token>`. On this page, *Authorize* signs in for you.
"""

health = APIRouter(tags=["Health"])


@health.get("/health")
def check() -> Health:
    """Whether the API is up. Needs no sign-in."""
    return Health(version=__version__)


def create_app(
    settings: Settings | None = None,
    *,
    api: ApiSettings | None = None,
    secret: str | None = None,
) -> FastAPI:
    """The app for the project ``settings`` names (by default the one this process finds,
    as every command does), with the API's settings from its ``configs/api.yaml`` and the
    signing key from :func:`~front_office.server.security.signing_secret` unless given."""
    settings = settings or load_settings()
    api = api or load_api_settings(settings.config_dir)
    app = FastAPI(title="NBA Front Office Lab API", version=__version__, description=DESCRIPTION)
    app.state.lab = ServerState(
        settings=settings,
        accounts=AccountService(settings.accounts_path, rounds=api.sign_in.password_rounds),
        tokens=Tokens(secret or signing_secret(settings), minutes=api.sign_in.token_minutes),
    )
    app.include_router(health)
    app.include_router(auth.router)
    app.include_router(rag.router)
    return app
