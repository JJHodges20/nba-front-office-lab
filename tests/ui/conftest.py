"""Running the workbench without a browser.

Streamlit's ``AppTest`` runs a script and exposes what it drew. Each test points the
workbench at a built project through ``FOL_HOME``; the caches the workbench keeps are
cleared around every run, because they are keyed on a build id and every test project
starts at build 1.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from front_office.config.settings import ENV_HOME
from front_office.pipelines.build import BuildReport
from wb import data

APP = Path(__file__).resolve().parents[2] / "apps" / "workbench" / "app.py"
TIMEOUT = 90


def draw_page(name: str) -> None:
    """One page as the workbench draws it: the sidebar filters, then the page."""
    import importlib

    from wb import data, state

    state.sidebar(data.status())
    importlib.import_module(f"wb.views.{name}").render()


Open = Callable[..., AppTest]


@pytest.fixture
def open_at(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[Path], None]]:
    """Point the workbench at a project and forget whatever it had cached."""

    def point(home: Path) -> None:
        monkeypatch.setenv(ENV_HOME, str(home))
        data.reset()

    yield point
    data.reset()  # also closes the database, so the temporary project can be removed


@pytest.fixture
def plain_home(built_template: tuple[Path, BuildReport]) -> Path:
    """A built project without contracts. Read-only."""
    return built_template[0]


@pytest.fixture
def scratch_home(contract_template: Path, tmp_path: Path) -> Path:
    """A private copy of the project with contracts, for tests that change rosters."""
    target = tmp_path / "home"
    shutil.copytree(contract_template, target)
    return target


@pytest.fixture
def page(open_at: Callable[[Path], None]) -> Open:
    """Draw one page for a project: ``page(home, "teams", filter_team=BOS)``.

    Keyword arguments preset the session, which is how a test chooses filters.
    """

    def run(home: Path, name: str, **session: object) -> AppTest:
        open_at(home)
        app = AppTest.from_function(draw_page, kwargs={"name": name}, default_timeout=TIMEOUT)
        for key, value in session.items():
            app.session_state[key] = value
        app.run()
        assert not app.exception, [error.value for error in app.exception]
        return app

    return run


@pytest.fixture
def app(open_at: Callable[[Path], None]) -> Callable[[Path], AppTest]:
    """The whole workbench, as ``streamlit run`` starts it."""

    def run(home: Path) -> AppTest:
        open_at(home)
        opened = AppTest.from_file(str(APP), default_timeout=TIMEOUT)
        opened.run()
        assert not opened.exception, [error.value for error in opened.exception]
        return opened

    return run


def figures(app: AppTest) -> dict[str, tuple[str, str | None]]:
    """The headline figures on a page: label -> (value, context)."""
    return {metric.label: (metric.value, metric.delta or None) for metric in app.metric}


def texts(app: AppTest) -> str:
    """Everything a page says in prose, joined: captions, markdown, headings."""
    parts = [element.value for element in (*app.caption, *app.markdown, *app.subheader)]
    return "\n".join(str(part) for part in parts)
