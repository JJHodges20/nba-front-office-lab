"""Data Health: how fresh the data is, what failed, what is missing, where it came from."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import streamlit as st

from wb import components, data, formats, state
from wb.components import EMPTY_CELL, Figure

GAP_TAGS = {
    "warning": ("Needs attention", ":material/warning:", "orange"),
    "info": ("Known limit", ":material/info:", "blue"),
}
CHECK_TAGS = {
    "passed": ("Passed", ":material/check_circle:", "green"),
    "warning": ("Warning", ":material/warning:", "orange"),
    "error": ("Error", ":material/error:", "red"),
}
FETCH_WORDS = {"stored": "Stored new data", "unchanged": "Nothing new", "failed": "Failed"}


def render() -> None:
    filters = state.current()
    build = filters.build
    now = datetime.now(UTC).replace(tzinfo=None, second=0, microsecond=0)
    components.header(
        "Data Health",
        "How fresh the data is, what failed, what is missing, and where it came from.",
    )

    builds = data.builds(build)
    latest = builds.iloc[0]
    failing = data.failed_fetches(build)
    components.figures(
        [
            Figure(
                "Last build",
                f"#{latest['build_id']}",
                formats.moment(latest["finished_at"]),
                help="Every build replaces the league tables in one step from the raw store.",
            ),
            Figure(
                "Rows loaded",
                formats.number(latest["rows_loaded"]),
                f"in {latest['seconds']:.0f} seconds",
            ),
            Figure(
                "Check errors",
                formats.number(latest["check_errors"]),
                f"{latest['check_warnings']} warnings",
                help="Quality checks that found the tables contradicting each other.",
            ),
            Figure(
                "Parts not built",
                formats.number(latest["build_errors"]),
                f"{latest['build_notes']} source notes",
                help="Tables or seasons the last build could not produce.",
            ),
            Figure(
                "Fetches failing",
                formats.number(len(failing)),
                "Slices failing now",
                help="Dataset slices whose most recent fetch failed.",
            ),
        ],
        # Three a row: five across cut the last build's date and time short at 1366px
        # (UI polish P6, audit finding F21).
        per_row=3,
    )

    st.subheader("Sources")
    for column, source in zip(st.columns(2), data.sources(build, now), strict=True):
        with column, st.container(border=True):
            with st.container(horizontal=True, vertical_alignment="center", gap="small"):
                st.markdown(f"**{source.title}**")
                components.state_badge(
                    source.state, components.source_word(source.source, source.state)
                )
            st.caption(source.detail)
            if source.newest_fetch is not None:
                fetched = formats.moment(source.newest_fetch)
                st.caption(f"Newest fetch: {fetched} · {source.slices} dataset slices held")

    st.subheader("What is missing")
    gaps = data.gaps(build, now.date())
    if not gaps:
        st.caption("Nothing the lab expects is missing.")
    for gap in gaps:
        components.tagged(GAP_TAGS[gap.severity], f"**{gap.area}.** {gap.message}")

    checks, notes, datasets, tables, fetches, history = st.tabs(
        ["Quality checks", "Build notes", "Datasets", "Tables", "Failed fetches", "Build history"]
    )
    with checks:
        _checks(build)
    with notes:
        _notes(build)
    with datasets:
        _datasets(build)
    with tables:
        _tables(build)
    with fetches:
        _failed(failing)
    with history:
        _history(builds)


def _checks(build: int | None) -> None:
    checks = data.checks(build)
    st.caption(
        "Checks compare the tables with each other after every build. An error is a "
        "contradiction; a warning is something unusual that may be true."
    )
    outcome = checks["severity"].where(~checks["passed"], "passed")
    shown = pd.DataFrame(
        {
            "Result": outcome.map(lambda value: CHECK_TAGS[value][0]),
            "Check": checks["check_name"],
            "Requires": checks["description"],
            "Examined": checks["examined"],
            "Failed": checks["failures"],
            "Examples": checks["examples"].fillna(""),
        }
    )
    st.dataframe(
        shown,
        hide_index=True,
        placeholder=EMPTY_CELL,
        height=components.table_height(min(len(shown), 14)),
        row_height=components.ROW,
        column_config={
            "Requires": st.column_config.Column(width="large"),
            "Examples": st.column_config.Column(width="large", help="A few failing items."),
        },
    )
    components.export(shown, "quality_checks", key="checks_csv")


def _notes(build: int | None) -> None:
    issues = data.issues(build)
    if issues.empty:
        st.caption("The last build had nothing to report.")
        return
    st.caption(
        "An error means data is missing. A note means the build adjusted something in the "
        "source data and says exactly what."
    )
    shown = pd.DataFrame(
        {
            "Kind": issues["severity"].str.capitalize(),
            "Table": issues["table_name"],
            "Scope": issues["scope"],
            "What happened": issues["message"],
        }
    )
    st.dataframe(
        shown,
        hide_index=True,
        placeholder=EMPTY_CELL,
        column_config={"What happened": st.column_config.Column(width="large")},
    )
    components.export(shown, "build_notes", key="notes_csv")


def _datasets(build: int | None) -> None:
    datasets = data.datasets(build)
    if datasets.empty:
        st.caption("Nothing has been fetched yet.")
        return
    st.caption(
        "What is held of each dataset. A slice is one dataset for one season, phase or team. "
        "Finished seasons are fetched once; the current season is refetched as it changes."
    )
    shown = pd.DataFrame(
        {
            "Source": datasets["source"].map(_source_title),
            "Dataset": datasets["dataset"],
            "Holds": datasets["description"],
            "Slices": datasets["slices"],
            "From": datasets["first_season"].fillna(formats.MISSING),
            "To": datasets["last_season"].fillna(formats.MISSING),
            "Newest fetch": datasets["newest_fetch"].map(formats.moment),
            "Oldest fetch": datasets["oldest_fetch"].map(formats.moment),
            "Failing": datasets["failing"],
        }
    )
    st.dataframe(
        shown,
        hide_index=True,
        placeholder=EMPTY_CELL,
        height=components.table_height(len(shown)),
        row_height=components.ROW,
        column_config={"Holds": st.column_config.Column(width="large")},
    )
    components.export(shown, "datasets", key="datasets_csv")


def _source_title(source: str) -> str:
    return {"nba_stats": "stats.nba.com", "contract_file": "Contract file"}.get(source, source)


def _tables(build: int | None) -> None:
    tables = data.tables(build)
    st.caption(
        "Every table in the database, with what it covers. Definitions are in the data dictionary."
    )
    shown = pd.DataFrame(
        {
            "Table": tables["table"],
            "Domain": tables["domain"],
            "Rows": tables["rows"],
            "From": tables["first_season"].fillna(formats.MISSING),
            "To": tables["last_season"].fillna(formats.MISSING),
            "Seasons": tables["seasons"],
            "Holds": tables["description"],
        }
    )
    st.dataframe(
        shown,
        hide_index=True,
        placeholder=EMPTY_CELL,
        height=components.table_height(len(shown)),
        row_height=components.ROW,
        column_config={
            "Rows": st.column_config.NumberColumn(format="localized"),
            "Holds": st.column_config.Column(width="large"),
        },
    )
    components.export(shown, "tables", key="tables_csv")


def _failed(failing: pd.DataFrame) -> None:
    if failing.empty:
        st.caption("No dataset slice is failing: every most-recent fetch succeeded.")
        return
    st.caption("Slices whose most recent fetch failed. Run fol refresh to try them again.")
    shown = pd.DataFrame(
        {
            "Source": failing["source"].map(_source_title),
            "Dataset": failing["dataset"],
            "Slice": failing["partition_key"],
            "Failed at": failing["finished_at"].map(formats.moment),
            "Why": failing["error"],
        }
    )
    st.dataframe(
        shown,
        hide_index=True,
        placeholder=EMPTY_CELL,
        column_config={"Why": st.column_config.Column(width="large")},
    )
    components.export(shown, "failed_fetches", key="failed_csv")


def _history(builds: pd.DataFrame) -> None:
    shown = pd.DataFrame(
        {
            "Build": builds["build_id"],
            "Finished": builds["finished_at"].map(formats.moment),
            "Took (s)": builds["seconds"].round(1),
            "Result": builds["status"].map({"ok": "Clean", "problems": "With problems"}),
            "Rows": builds["rows_loaded"],
            "Parts not built": builds["build_errors"],
            "Notes": builds["build_notes"],
            "Check errors": builds["check_errors"],
            "Check warnings": builds["check_warnings"],
            "Lab version": builds["lab_version"],
        }
    )
    st.dataframe(
        shown,
        hide_index=True,
        placeholder=EMPTY_CELL,
        column_config={"Rows": st.column_config.NumberColumn(format="localized")},
    )
    components.export(shown, "builds", key="builds_csv")
