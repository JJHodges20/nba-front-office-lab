"""What may have changed since the user's contract file (decision 0018, A7).

The assistant's side of the contract-update review: the moves on the league's transactions
file and those the news feeds reported since the file's date, beside what the file holds for
each player that season. A report is never a figure to import, and nothing here changes the
file: the result says how to check a newer copy - Contract Explorer's *Check a new file*, or
``fol contracts preview`` - and the import stays the user's own command.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, time

import pandas as pd

from front_office.assistant import tools as t
from front_office.assistant.current_tools import MOVES, Refresh
from front_office.assistant.lab_tools import Found, Handler, contract_evidence
from front_office.assistant.web_tools import NewsRefresh, SourceBook
from front_office.domain.assistant import Evidence, EvidenceKind, ResultStatus
from front_office.domain.seasons import Season
from front_office.services import Lab
from front_office.services.entities import fold

SHOWN = 12
"""Moves of each kind the model reads, newest first."""
HOW_TO_UPDATE = (
    "Reported figures are the site's, never imported. To bring the file up to date, get a newer "
    "copy from a source you may use, check it against the file in use - Contract Explorer's "
    "'Check a new file', or fol contracts preview - then import it yourself."
)


def contract_handlers(
    refresh: Refresh | None,
    news_refresh: NewsRefresh | None,
    book: SourceBook,
    *,
    now: Callable[[], datetime] = lambda: datetime.now(UTC).replace(tzinfo=None, microsecond=0),
) -> dict[str, Handler]:
    """``contract_updates`` for one question: the transactions and the feeds are fetched
    when due; the news items it names join the question's sources, to be read by id."""

    def contract_updates(lab: Lab, args: t.ContractUpdates) -> Found:
        title = "What may have changed since your contract file"
        as_of = lab.status().contract_as_of
        if as_of is None:
            return Found(
                ResultStatus.UNAVAILABLE,
                title,
                "No contract file has been imported, so there is no file to compare the moves "
                "with. A contract file is the user's to supply: fol contracts template, then "
                "fol contracts import.",
            )
        labels = lab.team_labels()
        team = args.team_id if args.team_id in labels.index else None
        abbreviation = None if team is None else str(labels.at[team, "abbreviation"])
        notes = []
        if refresh is not None:
            try:
                refresh(["transactions"])
            except Exception as error:  # a source that fails must not fail the question
                notes.append(f"The league's transactions could not be refreshed ({error}); the last copy is used.")  # fmt: skip
        if news_refresh is not None:
            try:
                news_refresh([abbreviation] if abbreviation else [])
            except Exception as error:
                notes.append(f"The news feeds could not be refreshed ({error}); the last copies are used.")  # fmt: skip
        moves = lab.current.transactions(team_id=team, player_id=args.player_id, since=as_of)
        reports = lab.current.news(
            team, args.player_id, since=datetime.combine(as_of, time()), moves_only=True
        )
        season = Season.league_year_on(now().date()).label
        salaries = lab.contracts.salaries(season)
        players = lab.entities.players()
        named = _names(players)

        def in_file(player_id: object) -> str:
            if player_id is None or pd.isna(player_id):  # type: ignore[arg-type]
                return "no player named"
            player = int(player_id)  # type: ignore[arg-type]
            name = (
                players.at[player, "full_name"] if player in players.index else f"player {player}"
            )
            if player in salaries.index and not pd.isna(salaries.at[player, "salary"]):
                return f"{name}: ${int(salaries.at[player, 'salary']):,} for {season} in your file"
            return f"{name}: no {season} salary in your file"

        about = ""
        if args.player_id is not None and args.player_id in players.index:
            about = f" about {players.at[args.player_id, 'full_name']}"
        elif team is not None:
            about = f" about the {labels.at[team, 'full_name']}"
        lines = [
            f"Your contract file is as of {as_of:%Y-%m-%d}. Since then{about}: {len(moves)} "
            f"move(s) on the league's transactions file and {len(reports)} reported in the "
            f"news feeds, newest first, each beside what your file holds for {season}. "
            + HOW_TO_UPDATE
        ]
        rows = []
        for _, move in moves.head(SHOWN).iterrows():
            when = pd.Timestamp(move["transaction_date"])
            lines.append(
                f"{when:%Y-%m-%d} league file, {move['transaction_type']}: {move['description']} "
                f"- {in_file(move['player_id'])}"
            )
            rows.append((when.date(), "League file", move["description"], in_file(move["player_id"]), None))  # fmt: skip
        evidence = [contract_evidence(lab)]
        for _, item in reports.head(SHOWN).iterrows():
            source = book.add(str(item["link"]), str(item["title"]))
            when = pd.Timestamp(item["published_at"])
            ids = [named[fold(tag)] for tag in _tags(item["categories"]) if fold(tag) in named]
            held = "; ".join(in_file(player) for player in ids) or "no player tagged"
            lines.append(f"{source.id}: {item['title']} - {item['site']}, {when:%Y-%m-%d}; {held}")
            rows.append((when.date(), item["site"], item["title"], held, source.id))
            evidence.append(
                Evidence(
                    EvidenceKind.WEB,
                    f"{item['title']} ({item['site']}), a news item",
                    location=str(item["link"]),
                    published_at=when.to_pydatetime(),
                )
            )
        for kind, frame in (("league file", moves), ("news feeds", reports)):
            if len(frame) > SHOWN:
                lines.append(f"({len(frame) - SHOWN} older moves on the {kind} are not shown.)")
        if not moves.empty:
            evidence.append(Evidence(EvidenceKind.CURRENT, MOVES, effective_at=as_of))
        table = pd.DataFrame(rows, columns=["date", "source", "move", "your_file", "source_id"])
        limits = (
            ()
            if rows
            else (
                f"No move on the league's file or in the news feeds since {as_of:%Y-%m-%d}"
                f"{about}: nothing is known to have changed, which is not proof that nothing "
                "did.",
            )
        )
        return Found(
            ResultStatus.OK,
            title,
            "\n".join(lines),
            table if rows else None,
            tuple(evidence),
            tuple(notes),
            ("reported",),
            limits,
        )

    return {"contract_updates": contract_updates}


def _names(players: pd.DataFrame) -> dict[str, int]:
    """Folded full names that belong to exactly one player."""
    counts = players["full"].value_counts()
    return {
        str(name): int(player)
        for player, name in players["full"].items()
        if name and counts.get(name) == 1
    }


def _tags(categories: object) -> list[str]:
    if not isinstance(categories, str):
        return []
    return [tag.removesuffix(" (Player)") for tag in categories.split("; ") if tag]
