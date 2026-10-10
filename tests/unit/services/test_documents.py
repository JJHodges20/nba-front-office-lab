"""The lab's documents as the assistant searches them: read afresh, from the project."""

from __future__ import annotations

from pathlib import Path

from front_office.config import Settings
from front_office.services import Lab


def write(project: Path, name: str, text: str) -> None:
    path = project / "docs" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_a_search_finds_sections_and_says_what_it_searched(
    settings: Settings, project: Path
) -> None:
    write(
        project,
        "decisions/0013-optimizer.md",
        "# 0013 - The optimizer\n\n## Decision\n\nThe optimizer returns several distinct "
        "rosters under two budgets, each cut off before the next search.\n",
    )
    write(
        project, "GUIDE.md", "# Guide\n\nThe workbench's pages, one by one, and what they show.\n"
    )
    with Lab(settings) as lab:
        assert lab.documents.available
        found = lab.documents.search("How does the optimizer choose rosters?")
    assert (found.documents, found.sections) == (2, 2)
    assert found.words == ("optimizer", "choose", "rosters")
    assert [hit.section.location for hit in found.hits] == [
        "docs/decisions/0013-optimizer.md#decision"
    ]


def test_an_edited_document_is_found_as_it_now_reads(settings: Settings, project: Path) -> None:
    write(project, "NOTES.md", "# Notes\n\n" + "Nothing about the subject asked for. " * 3)
    with Lab(settings) as lab:
        assert lab.documents.search("simulator").is_empty
        write(
            project,
            "NOTES.md",
            "# Notes\n\n" + "The simulator draws seasons from tested parts. " * 2,
        )
        assert not lab.documents.search("simulator").is_empty


def test_without_the_folder_there_is_nothing_to_search(settings: Settings) -> None:
    with Lab(settings) as lab:
        assert not lab.documents.available
        assert lab.documents.search("anything").is_empty
