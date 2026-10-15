"""One setting from a ``.env`` file: the user's own keys, which the repository never holds.

The assistant's web search reads its key this way (decision 0018), and the API its signing
key (decision 0019). The file is the user's; ``.env.example`` names each setting with no
value.
"""

from __future__ import annotations


def decoded(raw: bytes) -> str:
    """A ``.env`` file's text. Windows PowerShell 5 writes UTF-16 with ">"; Notepad may add
    a byte-order mark."""
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    return raw.decode("utf-8-sig")


def setting_in(raw: bytes, name: str) -> str | None:
    """The value ``name`` is given in a ``.env`` file's bytes, or ``None`` when the file does
    not give it one. Quotes around the value are dropped, and so is an ``export``."""
    for line in decoded(raw).splitlines():
        key, equals, rest = line.strip().partition("=")
        if equals and key.strip().removeprefix("export ").strip() == name:
            return rest.strip().strip("\"'").strip() or None
    return None
