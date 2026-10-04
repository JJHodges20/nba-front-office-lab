"""NBA Front Office Lab: the workbench.

Run it with ``fol ui``, or ``streamlit run apps/workbench/app.py`` from the project root.

This file is the frame every page sits in: the navigation, the global filters and the
data status in the sidebar. A page draws itself for whatever the filters say.
"""

from __future__ import annotations

from datetime import UTC, datetime

import streamlit as st

from wb import components, data, formats, state
from wb.views import (
    benchmarks,
    builder,
    contracts,
    fit,
    health,
    lab,
    league,
    players,
    teams,
    value,
)

st.set_page_config(
    page_title="NBA Front Office Lab",
    page_icon=":material/sports_basketball:",
    layout="wide",
    initial_sidebar_state="expanded",
)

PAGES = {
    "League": [
        st.Page(
            league.render,
            title="League Overview",
            icon=":material/leaderboard:",
            url_path="league",
            default=True,
        ),
        st.Page(
            benchmarks.render,
            title="Winning Benchmarks",
            icon=":material/emoji_events:",
            url_path="benchmarks",
        ),
    ],
    "Explore": [
        st.Page(
            players.render,
            title="Player Explorer",
            icon=":material/person_search:",
            url_path="players",
        ),
        st.Page(
            value.render,
            title="Player Value",
            icon=":material/trending_up:",
            url_path="value",
        ),
        st.Page(teams.render, title="Team Explorer", icon=":material/groups:", url_path="teams"),
        st.Page(
            contracts.render,
            title="Contract Explorer",
            icon=":material/request_quote:",
            url_path="contracts",
        ),
        st.Page(lab.render, title="Analytics Lab", icon=":material/science:", url_path="lab"),
    ],
    "Build": [
        st.Page(
            builder.render,
            title="Team Builder",
            icon=":material/construction:",
            url_path="builder",
        ),
        st.Page(
            fit.render,
            title="Roster Fit",
            icon=":material/diversity_3:",
            url_path="fit",
        ),
    ],
    "System": [
        st.Page(
            health.render,
            title="Data Health",
            icon=":material/monitor_heart:",
            url_path="health",
        ),
    ],
}


def not_built() -> None:
    """What the workbench shows before any data exists."""
    st.title("NBA Front Office Lab")
    components.empty(
        "No data has been built yet",
        "Fetch league data and build the database, then reload this page.",
        icon=":material/database:",
    )
    st.code("fol refresh", language="powershell")
    st.caption(
        "The first refresh makes about 650 requests to stats.nba.com and takes roughly "
        "fifteen minutes. Later ones fetch only what is new."
    )


def data_status(build: int | None, built_at: datetime | None) -> None:
    """Where the data stands, at the foot of the sidebar on every page."""
    now = datetime.now(UTC).replace(tzinfo=None, second=0, microsecond=0)
    with st.sidebar:
        st.divider()
        st.markdown("**Data**")
        for source in data.sources(build, now):
            word = components.source_word(source.source, source.state).lower()
            components.state_badge(source.state, f"{source.title}: {word}")
            st.caption(source.detail)
        st.caption(f"Build {build}, {formats.moment(built_at)}")


status = data.status()
if not status.is_built:
    not_built()
    st.stop()

page = st.navigation(PAGES, position="sidebar", expanded=True)
state.sidebar(status)
page.run()
data_status(status.build_id, status.built_at)
