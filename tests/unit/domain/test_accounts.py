"""The rules for an API user's name and password, and the sources an answer keeps."""

from __future__ import annotations

from datetime import datetime

import pytest

from front_office.domain.accounts import (
    PASSWORD_BYTES,
    PASSWORD_MIN,
    AccountRuleError,
    CitedSource,
    check_password,
    check_username,
    normal_username,
    sign_in_ends,
    sources_from_json,
    sources_to_json,
)


class TestNames:
    @pytest.mark.parametrize("name", ["abc", "analyst", "a.b-c_d", "9lives", "x" * 32])
    def test_allowed(self, name: str) -> None:
        assert check_username(name) == name

    def test_kept_trimmed_and_in_lower_case(self) -> None:
        assert check_username("  Analyst ") == "analyst"
        assert normal_username("ANALYST") == normal_username("analyst")

    @pytest.mark.parametrize(
        "name", ["", "ab", "x" * 33, "_lead", ".lead", "two words", "naïve", "semi;colon", "a/b"]
    )
    def test_refused(self, name: str) -> None:
        with pytest.raises(AccountRuleError, match="a name must be 3 to 32"):
            check_username(name)


class TestPasswords:
    def test_long_enough_is_kept_exactly_as_given(self) -> None:
        assert check_password("  spaces count  ") == "  spaces count  "

    def test_too_short(self) -> None:
        with pytest.raises(AccountRuleError, match=f"at least {PASSWORD_MIN} characters"):
            check_password("x" * (PASSWORD_MIN - 1))

    def test_limited_in_bytes_not_characters(self) -> None:
        # bcrypt reads 72 bytes: a longer password would be cut without a word.
        assert check_password("x" * PASSWORD_BYTES)
        with pytest.raises(AccountRuleError, match=f"at most {PASSWORD_BYTES} bytes"):
            check_password("x" * (PASSWORD_BYTES + 1))
        two_bytes_each = "é" * (PASSWORD_BYTES // 2 + 1)
        assert len(two_bytes_each) < PASSWORD_BYTES
        with pytest.raises(AccountRuleError):
            check_password(two_bytes_each)


def test_sources_go_to_json_and_back() -> None:
    sources = (
        CitedSource(1, "docs/ROADMAP.md", "Roadmap > Capstone", "docs/ROADMAP.md#capstone", 0.21),
        CitedSource(2, "docs/decisions/0019-capstone-api.md", "Décision", "x#y", 0.5),
    )
    assert sources_from_json(sources_to_json(sources)) == sources
    assert sources_from_json(sources_to_json(())) == ()


def test_a_sign_in_ends_its_minutes_after_it_was_made() -> None:
    made = datetime(2026, 10, 29, 9, 30)
    assert sign_in_ends(made, 60) == datetime(2026, 10, 29, 10, 30)
    assert sign_in_ends(made, 1) == datetime(2026, 10, 29, 9, 31)
