"""The suite stays on this machine (A9 network audit): ``tests/conftest.py`` fails any test,
outside the ``network`` and ``ollama`` markers, that connects anywhere else or looks a name
up - so a test that forgets to hand over a fake is caught, not quietly online."""

from __future__ import annotations

import socket

import pytest

from tests.conftest import NetworkReached

PUBLIC = ("93.184.216.34", 80)
"""An address on the public internet; nothing is sent to it - the guard refuses first."""


def test_a_connection_elsewhere_or_a_name_looked_up_is_refused(_no_network: list[str]) -> None:
    with pytest.raises(NetworkReached):
        socket.create_connection(PUBLIC, timeout=1)
    with pytest.raises(NetworkReached):
        socket.getaddrinfo("example.org", 443)
    assert len(_no_network) == 2
    _no_network.clear()  # what this test set out to do; any other test fails on it


def test_this_machine_is_allowed() -> None:
    listener = socket.create_server(("127.0.0.1", 0))
    try:
        with socket.create_connection(listener.getsockname(), timeout=5):
            pass
    finally:
        listener.close()
    assert socket.getaddrinfo("localhost", 80)
