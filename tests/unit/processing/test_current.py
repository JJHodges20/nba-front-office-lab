"""The league's transactions and injury report, normalised."""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import pytest

from front_office.domain.tables.current import INJURY_REPORTS, TRANSACTIONS
from front_office.processing.current import (
    CurrentPayloadError,
    injury_frame,
    transactions_frame,
)
from tests.current_fakes import FETCHED, move, movement
from tests.helpers import BROWN, NYK
from tests.injury_pdf import SAMPLE, SAMPLE_CARRIED, Line, report_pdf

ISSUED = datetime(2026, 10, 21, 21, 30)
URL = "https://example.invalid/Injury-Report_2026-10-21_05_30PM.pdf"


class TestTransactions:
    def test_ids_are_whole_numbers_and_zero_is_no_id(self) -> None:
        frame = transactions_frame(
            movement(move(), move(PLAYER_ID=0.0, TRANSACTION_DESCRIPTION="A team-only move.")),
            FETCHED,
        )
        assert list(frame.columns) == list(TRANSACTIONS.column_names)
        signed = frame[frame["player_id"].notna()].iloc[0]
        assert (signed["team_id"], signed["player_id"]) == (NYK, BROWN)
        assert signed["transaction_date"] == pd.Timestamp(date(2026, 10, 2))
        assert frame["player_id"].isna().sum() == 1

    def test_a_repeated_line_is_kept_once_and_said_so(self) -> None:
        notes: list[str] = []
        frame = transactions_frame(movement(move(), move(), move(TRANSACTION_DATE="2026-10-03")), FETCHED, notes)  # fmt: skip
        assert len(frame) == 2
        assert notes == ["1 line(s) repeated in the file, kept once"]

    def test_the_key_is_the_line_not_the_fetch(self) -> None:
        first = transactions_frame(movement(move()), FETCHED)
        again = transactions_frame(movement(move()), datetime(2026, 10, 10))
        assert first["transaction_key"].iloc[0] == again["transaction_key"].iloc[0]

    @pytest.mark.parametrize("payload", [{}, {"NBA_Player_Movement": {}}, []])
    def test_anything_else_is_refused(self, payload: object) -> None:
        with pytest.raises(CurrentPayloadError, match="player-movement"):
            transactions_frame(payload, FETCHED)  # type: ignore[arg-type]


class TestInjuryReport:
    def frame(self, pdf: bytes) -> pd.DataFrame:
        return injury_frame(pdf, report_time=ISSUED, url=URL, retrieved_at=FETCHED)

    def test_every_line_is_read_with_what_its_group_carries(self) -> None:
        frame = self.frame(report_pdf(SAMPLE, carried_over=SAMPLE_CARRIED))
        assert list(frame.columns) == list(INJURY_REPORTS.column_names)
        assert frame["player_name"].fillna("-").tolist() == [
            "Brown, Jaylen",
            "Tatum, Jayson",
            "Hart, Josh",
            "-",
            "Doe, Jordan",
            "Roe, Riley",
        ]
        assert (
            frame["team_name"].tolist()
            == ["Boston Celtics"] * 2
            + ["New York Knicks"]
            + ["Chicago Bulls"]
            + ["Milwaukee Bucks"] * 2
        )
        assert frame["matchup"].tolist() == ["NYK@BOS"] * 3 + ["CHI@MIL"] * 3
        assert (
            frame["game_date"].tolist()
            == [pd.Timestamp(date(2026, 10, 21))] * 3 + [pd.Timestamp(date(2026, 10, 22))] * 3
        )
        assert frame["row_number"].tolist() == [1, 2, 3, 4, 5, 6]
        assert (frame["report_time"] == pd.Timestamp(ISSUED)).all()
        assert (frame["source_url"] == URL).all()

    def test_a_wrapped_reason_joins_its_line(self) -> None:
        frame = self.frame(report_pdf(SAMPLE, carried_over=SAMPLE_CARRIED))
        assert frame.at[1, "reason"] == "Injury/Illness - Right Achilles; Tendon Repair"

    def test_a_reason_carried_over_the_page_break_finishes_its_word(self) -> None:
        frame = self.frame(report_pdf(SAMPLE, carried_over=SAMPLE_CARRIED))
        assert frame.at[4, "reason"] == "G League - Two-Way"
        assert frame.at[5, "reason"] == "Rest"

    def test_a_team_not_yet_submitted_is_its_own_status(self) -> None:
        frame = self.frame(report_pdf(SAMPLE, carried_over=SAMPLE_CARRIED))
        row = frame.iloc[3]
        assert row["status"] == "Not Yet Submitted"
        assert pd.isna(row["player_name"]) and pd.isna(row["reason"])

    def test_the_footer_is_not_a_line(self) -> None:
        frame = self.frame(report_pdf(SAMPLE, carried_over=SAMPLE_CARRIED))
        assert not frame["reason"].fillna("").str.contains("Page").any()

    def test_a_status_the_report_does_not_use_is_refused(self) -> None:
        odd = [[Line("10/21/2026", "07:30 (ET)", "NYK@BOS", "Boston Celtics", "Brown, Jaylen", "Maybe", ("Rest",))]]  # fmt: skip
        with pytest.raises(CurrentPayloadError, match="status 'Maybe'"):
            self.frame(report_pdf(odd))

    def test_a_file_that_is_not_a_pdf_is_refused(self) -> None:
        with pytest.raises(CurrentPayloadError, match="could not be read"):
            self.frame(b"<html>not a report</html>")
