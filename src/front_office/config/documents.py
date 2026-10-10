"""The lab's own documents, read from ``docs/`` for the assistant's search (decision 0018, A4).

Every Markdown file under the folder, cut into sections at its headings, but three. The
assistant's own recorded answers (``docs/research/ASSISTANT_ANSWERS.md``) would have it
cite itself. The metric glossary and the data dictionary are the catalogs themselves,
generated from code: ``metric_definition`` reads the metrics from where they are defined,
and as text both are long tables whose every row holds the words of almost any question,
crowding out the prose that explains.
"""

from __future__ import annotations

from pathlib import Path

from front_office.domain.documents import Section, split_sections

DOCUMENTS_FOLDER = "docs"
LEFT_OUT = frozenset(
    {
        "docs/research/ASSISTANT_ANSWERS.md",
        "docs/METRICS.md",
        "docs/DATA_DICTIONARY.md",
    }
)


def documents_path(project_root: Path) -> Path:
    return project_root / DOCUMENTS_FOLDER


def load_sections(project_root: Path) -> tuple[Section, ...]:
    """Every section of every document, file by file in path order; nothing when the
    folder is not there."""
    folder = documents_path(project_root)
    if not folder.is_dir():
        return ()
    found = {path.relative_to(project_root).as_posix(): path for path in folder.rglob("*.md")}
    sections: list[Section] = []
    for relative in sorted(found):
        if relative not in LEFT_OUT:
            text = found[relative].read_text(encoding="utf-8")
            sections.extend(split_sections(relative, text))
    return tuple(sections)
