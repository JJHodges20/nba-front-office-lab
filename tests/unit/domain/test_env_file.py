"""Reading one setting from a ``.env`` file, as Notepad and PowerShell write them."""

from __future__ import annotations

import pytest

from front_office.domain.env_file import setting_in

NAME = "FOL_EXAMPLE"


@pytest.mark.parametrize(
    "text",
    [
        "FOL_EXAMPLE=value",
        "FOL_EXAMPLE = value ",
        'FOL_EXAMPLE="value"',
        "FOL_EXAMPLE='value'",
        "export FOL_EXAMPLE=value",
        "# a comment\nOTHER=x\nFOL_EXAMPLE=value\n",
    ],
)
def test_finds_the_value(text: str) -> None:
    assert setting_in(text.encode("utf-8"), NAME) == "value"


@pytest.mark.parametrize("text", ["", "FOL_EXAMPLE=", "FOL_EXAMPLE=''", "FOL_EXAMPLE_2=x", "x"])
def test_nothing_given_is_none(text: str) -> None:
    assert setting_in(text.encode("utf-8"), NAME) is None


@pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-16"])
def test_reads_a_byte_order_mark_and_utf_16(encoding: str) -> None:
    assert setting_in("FOL_EXAMPLE=value\r\n".encode(encoding), NAME) == "value"
