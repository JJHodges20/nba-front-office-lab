from __future__ import annotations

from front_office.domain.documents import TRAIL, anchor, passages, split_sections

DOCUMENT = """\
# 0014 - The postseason model

Date: 2026-10-05.

## Decision

The model reads a team by two inputs.

### What else was tried

| Alternative | Kept? |
| --- | --- |
| Winning percentage | left out |

```powershell
# not a heading: a comment in code
fol playoffs fit --write
```

## Consequences

## Notes

First notes.

## Notes

Second notes.
"""


def test_a_document_is_cut_at_its_headings() -> None:
    sections = split_sections("docs/decisions/0014.md", DOCUMENT)
    assert [section.heading for section in sections] == [
        "0014 - The postseason model",
        "Decision",
        f"Decision{TRAIL}What else was tried",
        "Notes",
        "Notes",
    ]
    assert {section.document for section in sections} == {"0014 - The postseason model"}
    assert {section.path for section in sections} == {"docs/decisions/0014.md"}


def test_a_heading_inside_fenced_code_is_code() -> None:
    tried = split_sections("doc.md", DOCUMENT)[2]
    assert "# not a heading: a comment in code" in tried.text
    assert "| Winning percentage | left out |" in tried.text


def test_a_heading_with_nothing_under_it_gives_no_section() -> None:
    headings = [section.heading for section in split_sections("doc.md", DOCUMENT)]
    assert "Consequences" not in headings


def test_anchors_are_githubs_and_numbered_when_repeated() -> None:
    sections = split_sections("doc.md", DOCUMENT)
    assert [section.anchor for section in sections] == [
        "0014---the-postseason-model",
        "decision",
        "what-else-was-tried",
        "notes",
        "notes-1",
    ]
    assert sections[2].location == "doc.md#what-else-was-tried"
    assert anchor("The roster's `fit`: a rule?") == "the-rosters-fit-a-rule"


def test_text_before_any_heading_is_the_documents_own() -> None:
    (section,) = split_sections("docs/notes.md", "Just text, no heading at all.")
    assert (section.document, section.heading, section.anchor) == ("notes.md", "notes.md", "")
    assert section.location == "docs/notes.md"


def test_passages_grow_by_whole_paragraphs() -> None:
    text = "\n\n".join(["a" * 300, "b" * 300, "c" * 300, "d" * 300])
    found = passages(text, size=700)
    assert found == ("a" * 300 + "\n\n" + "b" * 300, "c" * 300 + "\n\n" + "d" * 300)


def test_a_long_paragraph_is_cut_between_its_lines() -> None:
    table = "\n".join(f"| row {number} | {'x' * 40} |" for number in range(40))
    found = passages(table, size=500)
    assert len(found) > 1 and all(len(item) <= 500 for item in found)
    assert "\n".join(found) == table
