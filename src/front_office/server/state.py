"""What every request of one app shares: the lab's settings, its accounts, its tokens."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request

from front_office.config.settings import Settings
from front_office.server.security import Tokens
from front_office.services.accounts import AccountService


@dataclass(frozen=True, slots=True)
class ServerState:
    settings: Settings
    accounts: AccountService
    tokens: Tokens


def server_state(request: Request) -> ServerState:
    """The app's state, as a dependency an endpoint asks for."""
    return request.app.state.lab
