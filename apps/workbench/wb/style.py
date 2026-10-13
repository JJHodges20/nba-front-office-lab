"""The workbench's style rules, applied once per run by the frame (UI polish P2).

Everything about the look comes from Streamlit's theme in ``.streamlit/config.toml`` and
the tokens in ``wb/theme.py``. What the theme cannot set lives in ``style.css`` beside this
module - one file, applied here, never from a page - so that a Streamlit upgrade that
renames a hook costs one rule, not a hunt through the views.
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

STYLESHEET = Path(__file__).with_name("style.css")


def apply() -> None:
    """Add the workbench's style rules to the page. ``st.html`` with nothing but a style
    takes no room on the page."""
    st.html(f"<style>{STYLESHEET.read_text(encoding='utf-8')}</style>")
