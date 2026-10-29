"""NBA Front Office Lab: the workbench.

Run it with ``fol ui``, or ``streamlit run apps/workbench/app.py`` from the project root.

This file is the frame every page sits in: the navigation in the top bar, the global
filters and the data status in the sidebar (UI polish P2, so the filters are always in
view). A page draws itself for whatever the filters say. Nothing of it is drawn until
someone has signed in (decision 0020, ``wb/signin.py``): until then the sign-in page is the
only page there is.
"""

from __future__ import annotations

from datetime import UTC, datetime

import streamlit as st

from wb import ask, components, data, formats, signin, state, style
from wb.views import (
    benchmarks,
    builder,
    contracts,
    docs,
    fit,
    health,
    lab,
    league,
    optimizer,
    players,
    postseason,
    research,
    simulator,
    teams,
    value,
)

st.set_page_config(
    page_title="NBA Front Office Lab",
    page_icon=":material/sports_basketball:",
    layout="wide",
    # Open on a desktop, closed on a phone, where it would cover the page (UI polish P2).
    initial_sidebar_state="auto",
)
style.apply()

RESEARCH_PAGE = st.Page(
    research.render,
    title="AI Research",
    icon=":material/smart_toy:",
    url_path="research",
)
# Ask AI about this, on the other pages, opens the answer here (A6).
ask.RESEARCH = RESEARCH_PAGE
HEALTH_PAGE = st.Page(
    health.render,
    title="Data Health",
    icon=":material/monitor_heart:",
    url_path="health",
)

PAGES = {
    "League": [
        st.Page(
            league.render,
            title="League Overview",
            icon=":material/leaderboard:",
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
        st.Page(
            optimizer.render,
            title="Roster Optimizer",
            icon=":material/tune:",
            url_path="optimizer",
        ),
    ],
    "Forecast": [
        st.Page(
            postseason.render,
            title="Postseason Outlook",
            icon=":material/query_stats:",
            url_path="postseason",
        ),
        st.Page(
            simulator.render,
            title="Scenario Simulator",
            icon=":material/casino:",
            url_path="simulator",
        ),
    ],
    "Ask": [
        RESEARCH_PAGE,
        # The capstone's page (decision 0019): the documents asked through the lab's own API.
        st.Page(
            docs.render,
            title="Ask the Docs",
            icon=":material/menu_book:",
            url_path="docs",
        ),
    ],
    "System": [HEALTH_PAGE],
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
    """Where the data stands, at the foot of the sidebar on every page: each source's state
    in a word, what lies behind it on hover, and a line under it only when something needs
    doing - the whole story is on Data Health, one click away (UI polish P2)."""
    now = datetime.now(UTC).replace(tzinfo=None, second=0, microsecond=0)
    with st.sidebar:
        st.divider()
        st.markdown("**Data**")
        for source in data.sources(build, now):
            word = components.source_word(source.source, source.state).lower()
            components.state_badge(source.state, f"{source.title}: {word}", help=source.detail)
            if source.state != "ok":
                st.caption(source.detail)
        st.caption(f"Build {build}, {formats.moment(built_at)}")
        st.page_link(HEALTH_PAGE, label="Data Health", icon=":material/monitor_heart:")


def all_pages() -> None:
    """Every page in its group, folded at the foot of the sidebar (UI polish P8, the owner's
    decision D13). Streamlit draws an open top-bar menu after everything on the page, so its
    pages came last in the keyboard's order; from here a keyboard reaches any page in a few
    steps. Closed, the fold is one stop, and the top bar is as it was."""
    with st.sidebar:
        with st.expander("All pages", icon=":material/menu:", key="all_pages"):
            for group, pages in PAGES.items():
                st.caption(group)
                for each in pages:
                    st.page_link(each, label=each.title, icon=each.icon)


def signed_out_pages() -> list[st.Page]:
    """The sign-in page at every page's address (decision 0020): a typed or bookmarked
    address opens it, rather than Streamlit's "Page not found", and once signed in the
    address opens the page it names."""
    return [
        st.Page(
            signin.page,
            title="Sign in",
            icon=":material/login:",
            url_path=each.url_path or None,
            default=not each.url_path,
        )
        for pages in PAGES.values()
        for each in pages
    ]


# Signed out, the sign-in page is all there is: nothing of the lab is drawn or read.
user = signin.current()
if user is None:
    st.navigation(signed_out_pages(), position="hidden").run()
    st.stop()

status = data.status()
if not status.is_built:
    not_built()
    signin.sidebar(user)
    st.stop()

page = st.navigation(PAGES, position="top")
state.sidebar(status)
components.new_page()
page.run()
# Who is signed in sits above the data status; All pages stays the sidebar's foot (D13).
signin.sidebar(user)
data_status(status.build_id, status.built_at)
all_pages()
