"""Current information as the assistant's tools: completed games, transactions, injuries.

Each tool first asks for what is due of its source - ``pipelines.current`` fetches nothing
more often than ``configs/assistant.yaml`` allows - then reads the cache through the
current-data service. When a source cannot be reached, the last copy is used and the result
says how old it is; with no copy, the source is unavailable. A source read and found
holding nothing - no game played yet, no report published, no move in the window - is an
answer, with its date and a limit the answer must state (decision 0018). Every row carries
its date, and the injury report its time: a player who is not on a report is "not on the
report", never "healthy".
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from front_office.assistant import tools as t
from front_office.assistant.lab_tools import DASH, Found, Handler, grid, lab_evidence, phase
from front_office.domain.assistant import Evidence, EvidenceKind, ResultStatus
from front_office.services import Lab
from front_office.services.current import ABSENT, FAILING, STALE, CurrentSource

Refresh = Callable[[Sequence[str]], object]
"""Fetches what is due of the named sources: ``pipelines.current.refresh_current``."""
EASTERN = ZoneInfo("America/New_York")
"""The league's own clock: the injury report is issued and named in Eastern time."""
RECENT_DAYS = 14
"""How far back the moves go when a question names no date, team or player."""
NOT_ON_THE_REPORT = (
    "Not being on the report is not the same as healthy or playing: a team lists the "
    "players it has a status to declare for its next game, as of the report's time."
)
GAMES = "NBA.com game logs (stats.nba.com), as last fetched"
MOVES = "NBA.com transactions (the league's player-movement file)"
REPORTS = "NBA official injury reports (the league's published files)"


def current_handlers(
    refresh: Refresh | None,
    *,
    now: Callable[[], datetime] = lambda: datetime.now(UTC).replace(tzinfo=None, microsecond=0),
) -> dict[str, Handler]:
    """The three handlers, fetching what is due through ``refresh`` (``None``: never).
    ``now`` (naive UTC) dates the default window of moves and judges what is stale."""

    def fetch(lab: Lab, source: str) -> tuple[CurrentSource | None, tuple[str, ...]]:
        """Ask for the source, then say where it stands; trouble is a note, not a failure."""
        trouble = None
        if refresh is not None:
            try:
                refresh([source])
            except Exception as error:  # a source that fails must not fail the question
                trouble = f"The {source} could not be refreshed ({error}); the last copy is used."
        state = next((s for s in lab.current.status(now=now()) if s.source == source), None)
        if trouble is None and state is not None and state.stored_at is not None:
            if state.state == FAILING:
                trouble = (
                    f"The last attempt to fetch the {source} failed ({state.detail}); "
                    f"the copy of {_utc(state.stored_at)} is used."
                )
            elif state.state == STALE:
                trouble = f"The {source} were last fetched {_utc(state.stored_at)}."
        return state, () if trouble is None else (trouble,)

    def current_games(lab: Lab, args: t.CurrentGames) -> Found:
        source, notes = fetch(lab, "games")
        games = lab.current.games(team_id=args.team_id, since=args.since, until=args.until)
        title = "Completed games of the season in progress"
        if games.empty:
            if not _checked(source):
                return _unreached(title, "games", source, notes)
            why = "none of the games fetched is in that window" if source.rows else source.detail
            limit = f"No completed game to report ({why}). Preseason games are not part of the lab's data."  # fmt: skip
            return Found(
                ResultStatus.OK,
                title,
                f"{limit} Checked{_as_of(source)}.",
                games,
                (_evidence(source, GAMES),),
                notes,
                ("measured",),
                (limit,),
            )
        season = str(games["season"].iloc[0])
        newer = games.loc[~games["in_build"], "game_id"].nunique()
        if args.team_id is not None:
            header = ["Date", "Phase", "Opponent", "Result", "Score", "In the build"]
            rows = [
                [
                    _day(g["game_date"]),
                    phase(g["season_type"]),
                    f"{'v' if g['is_home'] else '@'} {g['opponent']}",
                    _result(g["won"]),
                    f"{int(g['pts'])}-{int(g['opp_pts'])}",
                    "yes" if g["in_build"] else "no",
                ]
                for _, g in games.iterrows()
            ]
        else:
            one = games.sort_values("is_home", ascending=False, kind="stable")
            one = one.drop_duplicates("game_id").sort_values(
                ["game_date", "game_id"], ascending=False
            )
            header = ["Date", "Phase", "Game", "Score", "In the build"]
            rows = [
                [
                    _day(g["game_date"]),
                    phase(g["season_type"]),
                    f"{g['opponent']} at {g['team']}"
                    if g["is_home"]
                    else f"{g['team']} v {g['opponent']}",
                    _score(g),
                    "yes" if g["in_build"] else "no",
                ]
                for _, g in one.iterrows()
            ]
        head = (
            f"{season}: {games['game_id'].nunique()} games{_as_of(source)}, newest first; "
            f"{newer} of them newer than the lab's data build."
        )
        evidence = _evidence(source, GAMES)
        return Found(
            ResultStatus.OK,
            f"{title}, {season}",
            head + "\n" + grid(header, rows),
            games,
            (replace(evidence, effective_at=pd.Timestamp(games["game_date"].max()).date()),),
            notes,
            ("measured",),
        )

    def transactions(lab: Lab, args: t.Transactions) -> Found:
        source, notes = fetch(lab, "transactions")
        since = args.since
        if since is None and args.team_id is None and args.player_id is None:
            since = now().date() - timedelta(days=RECENT_DAYS)
        moves = lab.current.transactions(
            team_id=args.team_id, player_id=args.player_id, since=since
        )
        title = "Transactions"
        built = lab.status().built_at
        # Whether a move came after the build is said of the build, which is evidence too.
        build = lab_evidence(lab, "builds")
        on_build = "" if built is None else f" The lab's data build is of {built:%Y-%m-%d}."
        window = "" if since is None else f" since {since:%Y-%m-%d}"
        if moves.empty:
            if not _checked(source):
                return _unreached(title, "transactions", source, notes)
            limit = (
                f"The league's file lists no move for this{window}{_as_of(source)}; a move it "
                "has not listed yet is not known here."
            )
            return Found(
                ResultStatus.OK,
                title,
                limit + on_build,
                moves,
                (_evidence(source, MOVES), build),
                notes,
                ("reported",),
                (limit,),
            )
        after = (
            moves["transaction_date"] > pd.Timestamp(built.date())
            if built is not None
            else pd.Series(False, index=moves.index)
        )
        moves = moves.assign(after_build=after)
        rows = [
            [
                _day(m["transaction_date"]),
                m["transaction_type"],
                m["team"] if isinstance(m["team"], str) else DASH,
                m["description"],
                "yes" if m["after_build"] else "no",
            ]
            for _, m in moves.iterrows()
        ]
        head = f"{len(moves)} moves{window}{_as_of(source)}, newest first, dated by the league."
        if built is not None:
            head += (
                f" {int(after.sum())} of them dated after the lab's data build of "
                f"{built:%Y-%m-%d}; the lab's rosters do not show those."
            )
        newest = pd.Timestamp(moves["transaction_date"].max()).date()
        return Found(
            ResultStatus.OK,
            title,
            head + "\n" + grid(["Date", "Type", "Team", "Description", "After the build"], rows),
            moves,
            (replace(_evidence(source, MOVES), effective_at=newest), build),
            notes,
            ("reported",),
        )

    def injury_report(lab: Lab, args: t.InjuryReport) -> Found:
        source, notes = fetch(lab, "injuries")
        whole = lab.current.injuries()
        title = "The league's injury report"
        if whole.empty:
            if not _checked(source):
                return _unreached(title, "injury report", source, notes)
            limit = (
                f"There is no injury report to read ({source.detail}). The league publishes "
                "one for game days, so no player's status is known here - which is not the "
                "same as healthy."
            )
            return Found(
                ResultStatus.OK,
                title,
                f"{limit} Checked{_as_of(source)}.",
                whole,
                (_evidence(source, REPORTS),),
                notes,
                ("reported",),
                (limit,),
            )
        issued = pd.Timestamp(whole["report_time"].iloc[0]).to_pydatetime()
        when = f"the report of {_eastern(issued)}"
        evidence = Evidence(
            EvidenceKind.CURRENT,
            f"NBA official injury report, {_eastern(issued)}",
            location=str(whole["source_url"].iloc[0]),
            retrieved_at=pd.Timestamp(whole["retrieved_at"].iloc[0]).to_pydatetime(),
            published_at=issued,
            effective_at=pd.Timestamp(whole["game_date"].min()).date(),
        )
        report = whole
        if args.team_id is not None:
            report = report[report["team_id"] == args.team_id]
        if args.player_id is not None:
            report = report[report["player_id"] == args.player_id]
        if report.empty:
            who = "This player is" if args.player_id is not None else "This team has no line"
            return Found(
                ResultStatus.OK,
                title,
                f"{who} not on {when}. {NOT_ON_THE_REPORT}",
                report,
                (evidence,),
                notes,
                ("reported",),
            )
        rows = [
            [
                _day(r["game_date"]),
                r["matchup"] if isinstance(r["matchup"], str) else DASH,
                r["team_name"],
                r["player_name"] if isinstance(r["player_name"], str) else DASH,
                r["status"],
                r["reason"] if isinstance(r["reason"], str) else DASH,
            ]
            for _, r in report.iterrows()
        ]
        head = (
            f"From {when} ({len(report)} lines). Statuses change through the day; these are "
            f"that report's. {NOT_ON_THE_REPORT}"
        )
        return Found(
            ResultStatus.OK,
            title,
            head + "\n" + grid(["Game day", "Game", "Team", "Player", "Status", "Reason"], rows),
            report,
            (evidence,),
            notes,
            ("reported",),
        )

    return {
        "current_games": current_games,
        "transactions": transactions,
        "injury_report": injury_report,
    }


def _day(value: object) -> str:
    return f"{pd.Timestamp(value):%Y-%m-%d}"  # type: ignore[arg-type]


def _utc(moment: datetime) -> str:
    return f"{moment:%Y-%m-%d %H:%M} UTC"


def _eastern(moment: datetime) -> str:
    """A UTC time as the league writes its own: ``2026-10-09 05:30 PM Eastern``."""
    local = moment.replace(tzinfo=UTC).astimezone(EASTERN)
    return f"{local:%Y-%m-%d %I:%M %p} Eastern"


def _as_of(source: CurrentSource | None) -> str:
    if source is None or source.stored_at is None:
        return ""
    return f", as fetched {_utc(source.stored_at)}"


def _result(won: object) -> str:
    if won is None or pd.isna(won):  # type: ignore[arg-type]
        return DASH
    return "W" if won else "L"


def _score(game: pd.Series) -> str:
    """A game's score with the winner first: ``NYK 110, BOS 102``."""
    first, second = (game["team"], int(game["pts"])), (game["opponent"], int(game["opp_pts"]))
    if not pd.isna(game["won"]) and not game["won"]:
        first, second = second, first
    return f"{first[0]} {first[1]}, {second[0]} {second[1]}"


def _checked(source: CurrentSource | None) -> bool:
    """Whether the source has been read at least once: what it holds - or that it holds
    nothing - is then a dated fact."""
    return source is not None and source.stored_at is not None


def _unreached(title: str, what: str, source: CurrentSource | None, notes: tuple[str, ...]) -> Found:  # fmt: skip
    never = source is None or source.state == ABSENT or not source.detail
    why = "it has never been fetched" if never else source.detail
    return Found(
        ResultStatus.UNAVAILABLE,
        title,
        f"The {what} could not be read ({why}), and nothing is held from before.",
        warnings=notes,
    )


def _evidence(source: CurrentSource | None, label: str) -> Evidence:
    return Evidence(
        EvidenceKind.CURRENT,
        label,
        location=None if source is None else source.url,
        retrieved_at=None if source is None else source.stored_at,
    )
