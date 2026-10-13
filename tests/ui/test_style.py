"""The workbench's own style rules (UI polish P2): one file, applied once, by the frame.

Everything else about the look is Streamlit's theme. A rule here is a decision of the
owner's, listed in docs/ui-polish/DESIGN_SYSTEM.md; these tests keep the file, the one place
that applies it, and that list in step, so styling cannot creep into the pages.
"""

from __future__ import annotations

import re
from pathlib import Path

from wb import style

APPS = Path(__file__).resolve().parents[2] / "apps" / "workbench"
DESIGN_SYSTEM = Path(__file__).resolve().parents[2] / "docs" / "ui-polish" / "DESIGN_SYSTEM.md"
FOCUS = (
    '[data-testid="stPageLink-NavLink"]:focus-visible, '
    '[data-testid="stTopNavSection"]:focus-visible, '
    '[data-testid="stTopNavDropdownLink"]:focus-visible'
)
RULES = {
    # P2: the space above every title.
    '[data-testid="stMainBlockContainer"]': {"padding-top": "2.5rem"},
    # P3: rows of headline tiles wrap as a grid (components.figures keys them "tiles-").
    '[class*="st-key-tiles-"] [data-testid="stHorizontalBlock"]': {
        "display": "grid",
        "grid-template-columns": "repeat(auto-fit, minmax(11rem, 1fr))",
    },
    '[class*="st-key-tiles-"] [data-testid="stColumn"]': {"width": "auto", "min-width": "0"},
    '[class*="st-key-tiles-wide-"] [data-testid="stHorizontalBlock"]': {
        "grid-template-columns": "repeat(auto-fit, minmax(14rem, 1fr))",
    },
    # P8 (decision D14): a focused link or menu ringed, as buttons are.
    FOCUS: {"outline": "2px solid #2f8556", "outline-offset": "2px"},
}
"""Every rule the stylesheet may hold: its selector and its declarations."""


def parsed(css: str) -> dict[str, dict[str, str]]:
    """Each rule's selector, its spaces and line breaks made single spaces, and declarations."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    found: dict[str, dict[str, str]] = {}
    for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        declarations = (part.split(":", 1) for part in body.split(";") if part.strip())
        found[" ".join(selector.split())] = {
            name.strip(): value.strip() for name, value in declarations
        }
    return found


def test_the_stylesheet_holds_the_agreed_rules_and_nothing_else() -> None:
    assert parsed(style.STYLESHEET.read_text(encoding="utf-8")) == RULES


def test_every_rule_is_listed_in_the_design_system() -> None:
    listed = DESIGN_SYSTEM.read_text(encoding="utf-8")
    for selector in RULES:
        assert selector in listed, f"{selector} is not in DESIGN_SYSTEM.md"


def test_the_frame_applies_it_once_and_no_page_styles_itself() -> None:
    sources = {path: path.read_text(encoding="utf-8") for path in APPS.rglob("*.py")}
    assert [path.name for path, text in sources.items() if "style.apply()" in text] == ["app.py"]
    for path, text in sources.items():
        if path == APPS / "wb" / "style.py":
            continue
        for hook in ("unsafe_allow_html", "st.html(", "<style", "components.v1"):
            assert hook not in text, f"{path.relative_to(APPS)} uses {hook}"
