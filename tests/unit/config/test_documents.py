from __future__ import annotations

from pathlib import Path

from front_office.config.documents import LEFT_OUT, load_sections
from front_office.storage.documents import search_sections

REPO_ROOT = Path(__file__).resolve().parents[3]


def write(root: Path, name: str, text: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_every_markdown_file_under_docs_is_read_but_those_left_out(tmp_path: Path) -> None:
    write(tmp_path, "docs/GUIDE.md", "# Guide\n\nHow the lab works, in a sentence or two.\n")
    write(tmp_path, "docs/decisions/0001-layers.md", "# 0001 - Layers\n\n## Decision\n\nLayers.\n")
    write(tmp_path, "docs/research/ASSISTANT_ANSWERS.md", "# Answers\n\nThe assistant's own.\n")
    write(tmp_path, "docs/METRICS.md", "# Metric Glossary\n\nGenerated.\n")
    write(tmp_path, "docs/images/chart.png", "not text")
    sections = load_sections(tmp_path)
    assert [(section.path, section.heading) for section in sections] == [
        ("docs/GUIDE.md", "Guide"),
        ("docs/decisions/0001-layers.md", "Decision"),
    ]


def test_no_docs_folder_is_no_sections(tmp_path: Path) -> None:
    assert load_sections(tmp_path) == ()


def test_the_labs_own_documents_answer_a_question_about_a_decision() -> None:
    """The index over the documents this repository ships: every file reads, and a question
    about the postseason model's inputs finds the decision that made them."""
    sections = load_sections(REPO_ROOT)
    paths = {section.path for section in sections}
    assert "docs/ARCHITECTURE.md" in paths and not paths & LEFT_OUT
    hits = search_sections(sections, "postseason model winning percentage left out", limit=4)
    assert "docs/decisions/0014-postseason-model.md" in {hit.section.path for hit in hits}
