"""Every control on every page, put through every value it offers.

A page that draws for the state it opens in can still fail on the fortieth metric of a
select, or when a toggle is flipped. This sweep opens each page and works through its
controls one at a time - every option of every select, segmented control and pill, every
toggle and tick box, every number box up and down, every text box filled, every
multiselect filled and emptied - and after each step the page must have drawn without
an exception and without an error box. Each control is put back before the next one is
tried, so a failure names one control and one value.

Last, every button is pressed once. The sweep finds crashes; it does not judge what a
page shows or what a button did - ``test_pages.py`` does that.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest
from streamlit.testing.v1.element_tree import _format_value_for_widget

from front_office.config import load_settings
from front_office.services import Lab
from tests.helpers import BOS, BROWN, PRITCHARD, TATUM, WHITE
from wb import state

MOST_SAMPLED = 4
"""How many teams or players are tried on pages that are not about choosing one."""

# The states each page is swept from. A control that only exists once a team or a player
# is chosen is only found by starting there.
STARTS: dict[str, dict[str, dict[str, object]]] = {
    "league": {"open": {}, "team": {state.TEAM: BOS}},
    "benchmarks": {
        "open": {},
        "champions": {"bench_stage": "won_championship", "bench_era": "custom"},
    },
    # Brown played 71 games, so every trailing span has a form chart to draw.
    "players": {"open": {}, "player": {state.PLAYER: BROWN}},
    # A chosen player adds the breakdown of that player's impact under the season's table.
    "value": {"open": {}, "player": {state.PLAYER: TATUM}},
    "teams": {"open": {}, "team": {state.TEAM: BOS}},
    "contracts": {"open": {}, "team": {state.TEAM: BOS}},
    "lab": {"players": {}, "teams": {"lab_subject": "Teams"}},
    "builder": {"roster": {}},
    # The roster start needs the roster the sweep creates; the team start needs a team.
    "fit": {"team": {state.TEAM: BOS}, "roster": {"fit_subject": "Built roster"}},
    "health": {"open": {}},
}
# The one filter a page is swept through in full although it is long, from the first of
# its starts: the page is about that choice. Elsewhere a few teams and players stand for
# all of them.
OWN_SUBJECT = {"teams": state.TEAM, "players": state.PLAYER, "fit": state.TEAM}
SAMPLED = (state.TEAM, state.PLAYER, "'Add a player'", "bench_field_x", "bench_field_y")
CASES = [(name, start) for name, starts in STARTS.items() for start in starts]


class Label(str):
    """An option named by the label it is shown under, as a browser names it.

    A widget accepts an option or its label, and takes a string for a label when its
    format function cannot make sense of it. Being unhashable, this string cannot be
    mistaken for an option by a format function that looks its argument up - a
    dictionary's ``get`` would otherwise quietly answer ``None``.
    """

    __hash__ = None  # type: ignore[assignment]


def sampled(count: int) -> list[int]:
    """A few positions spread over a long list of options, ends included."""
    if count <= MOST_SAMPLED:
        return list(range(count))
    return sorted({round(step * (count - 1) / (MOST_SAMPLED - 1)) for step in range(MOST_SAMPLED)})


class Sweep:
    """One page, opened once, and everything that went wrong while trying its controls."""

    def __init__(
        self,
        opened: AppTest,
        start: Mapping[str, object],
        full_subject: str | None = None,
    ) -> None:
        self.opened = opened
        self.start = start
        """The session the page was opened with, returned to after every control."""
        self.full_subject = full_subject
        """The team or player filter to try in full; the other is sampled."""
        self.steps = 0
        self.problems: list[str] = []
        self.lost: list[str] = []
        """Controls that were there at the start and gone when their turn came."""

    @staticmethod
    def name(widget) -> str:  # type: ignore[no-untyped-def]
        return widget.key or f"'{widget.label}'"

    def find(self, kind: str, key: tuple[str, int]):  # type: ignore[no-untyped-def]
        """A control by its key - or its label, where it has none - and which of them."""
        name, position = key
        same = [widget for widget in getattr(self.opened, kind) if self.name(widget) == name]
        return same[position] if position < len(same) else None

    def keys(self, kind: str) -> list[tuple[str, int]]:
        seen: dict[str, int] = {}
        keys = []
        for widget in getattr(self.opened, kind):
            name = self.name(widget)
            position = seen.get(name, 0)
            seen[name] = position + 1
            if not widget.disabled:
                keys.append((name, position))
        return keys

    def step(self, what: str) -> None:
        """Run the page after a change and note anything that broke."""
        self.steps += 1
        self.opened.run()
        for failure in self.opened.exception:
            self.problems.append(f"{what}: {failure.value[:300]}")
        for box in self.opened.error:
            self.problems.append(f"{what}: error box: {box.value[:200]}")

    def choices(self, kind: str, key: tuple[str, int]) -> Iterator[tuple[str, Callable[[], None]]]:
        """Each way of changing one control, then the way to put it back."""
        widget = self.find(kind, key)
        several = kind == "multiselect" or isinstance(widget.value, list)
        if kind in ("selectbox", "button_group") and not several:
            original, labels = widget.value, list(widget.options)
            positions = range(len(labels))
            if key[0] in SAMPLED and self.full_subject != key[0]:
                positions = sampled(len(labels))
            for position in positions:
                label = labels[position]
                yield f"= {label}", lambda label=label: self.set(kind, key, label)
            yield "put back", lambda: self.restore(kind, key, original)
        elif several:
            # Nothing chosen, then one more at a time; and each on its own where few.
            original, labels = list(widget.value), list(widget.options)
            limit = getattr(widget, "max_selections", 0) or len(labels)
            sets = [labels[:size] for size in range(min(limit, len(labels), MOST_SAMPLED) + 1)]
            if len(labels) <= MOST_SAMPLED:
                sets += [[label] for label in labels[1:]]
            for picked in sets:
                yield f"= {picked}", lambda picked=picked: self.set_many(kind, key, picked)
            yield "put back", lambda: self.restore(kind, key, original)
        elif kind in ("toggle", "checkbox"):
            original = widget.value
            yield f"= {not original}", lambda: self.restore(kind, key, not original)
            yield "put back", lambda: self.restore(kind, key, original)
        elif kind == "number_input":
            original = widget.value
            yield "up", lambda: self.find(kind, key).increment()
            yield "down twice", lambda: self.find(kind, key).decrement().decrement()
            yield "lowest", lambda: self.restore(kind, key, widget.min)
            yield "put back", lambda: self.restore(kind, key, original)
        elif kind in ("text_input", "text_area"):
            original = widget.value
            for text in ("zz", "true shooting", "50% (a/b) [x] \\ *"):
                yield f"= {text!r}", lambda text=text: self.restore(kind, key, text)
            yield "put back", lambda: self.restore(kind, key, original)

    def set(self, kind: str, key: tuple[str, int], label: str) -> None:
        self.find(kind, key).set_value(Label(label))

    def set_many(self, kind: str, key: tuple[str, int], labels: list[str]) -> None:
        self.find(kind, key).set_value([Label(label) for label in labels])

    def restore(self, kind: str, key: tuple[str, int], value: object) -> None:
        self.find(kind, key).set_value(value)

    def run(self) -> None:
        for kind in (
            "selectbox",
            "button_group",
            "multiselect",
            "toggle",
            "checkbox",
            "number_input",
            "text_input",
            "text_area",
        ):
            for key in self.keys(kind):
                if self.find(kind, key) is None:
                    self.lost.append(f"{kind} {key[0]}")
                    continue
                for what, change in self.choices(kind, key):
                    if self.find(kind, key) is None:
                        self.lost.append(f"{kind} {key[0]} before '{what}'")
                        break
                    change()
                    self.step(f"{kind} {key[0]} {what}")
                self.return_to_start()
        self.press()

    def return_to_start(self) -> None:
        """Undo what a control changed besides itself.

        Putting a control back does not undo its side effects: a season without player
        statistics clears the chosen player, and choosing the season again does not
        choose the player again. Without this the rest of the sweep would run on a
        barer page than it set out to try.
        """
        moved = {
            key: value
            for key, value in self.start.items()
            if key not in self.opened.session_state or self.opened.session_state[key] != value
        }
        for key, value in moved.items():
            self.opened.session_state[key] = value
        if moved:
            self.step(f"return to {sorted(moved)}")

    def press(self) -> None:
        """Press every button once, with empty text boxes filled so that a form goes through.

        A button may refuse and say why in an error box; it may not raise. The last
        button goes first: one near the top of a page tends to replace what is below it.
        """
        for key in reversed(self.keys("button")):
            for box in self.opened.text_input:
                if not box.disabled and not box.value:
                    box.set_value("Swept")
            button = self.find("button", key)
            if button is None or button.disabled:
                continue
            button.click()
            self.steps += 1
            self.opened.run()
            for failure in self.opened.exception:
                self.problems.append(f"button {key[0]}: {failure.value[:300]}")


@pytest.fixture
def swept(page, scratch_home: Path) -> Callable[[str, str], Sweep]:
    """Sweep a page of a project with contracts and a roster, from a named start."""
    with Lab(load_settings(scratch_home)) as lab:
        roster = lab.builder.create("Swept roster")
        lab.builder.add_player(roster, TATUM, slot="SF")
        lab.builder.add_player(roster, BROWN, slot="SG")
        lab.builder.add_player(roster, PRITCHARD)
        lab.builder.add_player(roster, WHITE, assumed_salary=28_000_000)

    def run(name: str, start: str) -> Sweep:
        first = start == next(iter(STARTS[name]))
        session = STARTS[name][start]
        sweep = Sweep(
            page(scratch_home, name, **session),
            session,
            full_subject=OWN_SUBJECT.get(name) if first else None,
        )
        sweep.run()
        return sweep

    return run


@pytest.mark.parametrize(("name", "start"), CASES, ids=[f"{name}-{start}" for name, start in CASES])
def test_no_control_on_any_page_can_break_it(swept, name: str, start: str) -> None:
    sweep = swept(name, start)
    print(f"{name} from {start}: {sweep.steps} steps")
    assert not sweep.problems, "\n".join(sweep.problems[:12])
    assert not sweep.lost, f"controls the sweep never reached: {sweep.lost}"
    assert sweep.steps >= 20, f"only {sweep.steps} steps: the sweep found too little to try"


def test_every_page_is_swept_and_drawn() -> None:
    """A page added to the workbench cannot be left out of the sweep or the page tests."""
    import pkgutil

    from tests.ui.test_pages import PAGES
    from wb import views

    modules = {module.name for module in pkgutil.iter_modules(views.__path__)}
    assert set(STARTS) == modules
    assert set(PAGES) == modules


def test_a_long_list_is_sampled_at_both_ends_and_between() -> None:
    assert sampled(3) == [0, 1, 2]
    assert sampled(30) == [0, 10, 19, 29]
    assert sampled(41) == [0, 13, 27, 40]


def test_a_label_passes_for_itself_whatever_the_format_function() -> None:
    phases = {"regular": "Regular season", "playoffs": "Playoffs"}
    names = {7: "Seven"}
    for format_func in (phases.get, str, lambda option: names[option], lambda o: names.get(o)):
        assert _format_value_for_widget(format_func, Label("Playoffs")) == "Playoffs"
    # A plain string would be taken for an option that is not there.
    assert _format_value_for_widget(phases.get, "Playoffs") is None
