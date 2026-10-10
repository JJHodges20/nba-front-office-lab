"""A web page as text: the words, not the page's machinery."""

from __future__ import annotations

from datetime import datetime

import pytest

from front_office.processing.web import page_text
from tests.web_fakes import ARTICLE


def test_an_articles_text_with_its_title_site_and_date() -> None:
    page = page_text(ARTICLE.encode())
    assert page.title == "How the Knicks won it all"
    assert page.site_name == "Example Sports"
    assert page.published_at == datetime(2026, 6, 20, 18, 30)
    assert page.text.startswith("How the Knicks won it all\nThe Knicks held opponents")
    assert "averaged 31.2 points" in page.text


def test_scripts_styles_navigation_and_footers_are_not_text() -> None:
    page = page_text(ARTICLE.encode())
    for left_out in ("Ignore this script text", "color: red", "Home", "Copyright"):
        assert left_out not in page.text


def test_a_pages_instructions_stay_its_text() -> None:
    # Nothing here acts on a page; an instruction in it is words like any other.
    assert "IMPORTANT SYSTEM NOTICE" in page_text(ARTICLE.encode()).text


def test_without_an_article_the_main_section_or_the_body() -> None:
    words = "".join(f"<p>Main words, part {part}.</p>" for part in range(30))
    main = f"<main>{words}</main><p>Outside.</p>"
    assert "Outside." not in page_text(f"<body><nav>Menu</nav>{main}</body>".encode()).text
    short = page_text(b"<body><p>Only a little.</p><div>And a div.</div></body>")
    assert short.text == "Only a little.\nAnd a div."


@pytest.mark.parametrize(
    ("head", "published"),
    [
        ('<meta name="date" content="2026-03-01">', datetime(2026, 3, 1)),
        (
            '<script type="application/ld+json">{"@type": "NewsArticle", "datePublished": "2026-04-02T10:00:00Z"}</script>',
            datetime(2026, 4, 2, 10),
        ),
        ("", None),
    ],
)
def test_the_publication_date_is_the_pages_own_claim(head: str, published: datetime | None) -> None:
    html = f"<html><head>{head}</head><body><p>Words.</p></body></html>"
    assert page_text(html.encode()).published_at == published


def test_a_time_element_is_the_last_resort() -> None:
    html = '<body><p>Posted <time datetime="2026-05-05T08:00:00+00:00">May 5</time></p></body>'
    assert page_text(html.encode()).published_at == datetime(2026, 5, 5, 8)


def test_the_character_set_from_the_header_or_the_page() -> None:
    latin = "<p>Dončić and Jokić</p>".encode("windows-1250")
    assert "Dončić" in page_text(latin, charset="windows-1250").text
    declared = b'<meta charset="windows-1250"><p>' + "Dončić".encode("windows-1250") + b"</p>"
    assert "Dončić" in page_text(declared).text
    assert page_text("<p>Dončić</p>".encode(), charset="no-such-charset").text == "Dončić"


def test_plain_text_is_kept_as_it_is() -> None:
    page = page_text(b"Line one.\n\n\nLine two.", "text/plain")
    assert (page.title, page.text) == ("", "Line one.\nLine two.")


def test_an_article_changed_since_it_was_published_says_when() -> None:
    head = (
        '<script type="application/ld+json">{"datePublished": "2002-08-17T20:11:02Z", '
        '"dateModified": "2026-10-02T04:54:43Z"}</script>'
    )
    page = page_text(f"<html><head>{head}</head><body><p>Words.</p></body></html>".encode())
    assert (page.published_at, page.updated_at) == (
        datetime(2002, 8, 17, 20, 11, 2),
        datetime(2026, 10, 2, 4, 54, 43),
    )
    meta = '<meta property="article:modified_time" content="2026-06-21T08:00:00Z">'
    assert page_text(meta.encode()).updated_at == datetime(2026, 6, 21, 8)


def test_the_title_is_the_documents_not_an_icons() -> None:
    # Found reading RotoWire live at A2: an SVG icon's <title> joined the page's.
    html = (
        "<html><head><title>NBA Injury Report | RotoWire</title></head><body>"
        '<svg><title>RotoWire Facebook</title><path d="M0"/></svg><p>Words.</p></body></html>'
    )
    page = page_text(html.encode())
    assert page.title == "NBA Injury Report | RotoWire"
    assert "Facebook" not in page.text
