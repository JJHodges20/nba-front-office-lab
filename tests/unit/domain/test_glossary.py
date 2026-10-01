from __future__ import annotations

from front_office.domain.glossary import _BETTER, _ORIGIN, _SHOWN_AS, render_metric_glossary
from front_office.domain.metrics import MetricCatalog, MetricFormat, MetricSpec
from front_office.domain.schema import Provenance

CATALOG = MetricCatalog(
    (
        MetricSpec("ts_pct", "TS%", "True shooting", "Points per attempt.", "Scoring",
                   MetricFormat.PERCENT),
        MetricSpec("tov", "TOV", "Turnovers", "Possessions lost.", "Creation",
                   MetricFormat.COUNT, Provenance.MEASURED, higher_is_better=False),
        MetricSpec("pace", "Pace", "Pace", "Possessions per game.", "Scoring",
                   higher_is_better=None),
    )
)  # fmt: skip


def test_one_section_per_catalog_and_one_table_per_category() -> None:
    document = render_metric_glossary({"Players": CATALOG, "Teams": CATALOG})
    assert document.startswith("# Metric Glossary\n")
    assert document.count("## Players") == 1 and document.count("## Teams") == 1
    assert document.count("### Scoring") == 2 and document.count("### Creation") == 2
    assert document.index("### Scoring") < document.index("### Creation")
    assert document.endswith("|\n")


def test_each_metric_is_one_row_with_its_definition() -> None:
    document = render_metric_glossary({"Players": CATALOG})
    assert (
        "| TS% | True shooting | `ts_pct` | derived | percentage | higher | Points per attempt. |"
        in document
    )
    assert "| TOV | Turnovers | `tov` | measured | whole number | lower | Possessions lost. |" in (
        document
    )
    assert "| Pace | Pace | `pace` | derived | number | neither | Possessions per game. |" in (
        document
    )


def test_only_the_origins_in_use_are_explained() -> None:
    document = render_metric_glossary({"Players": CATALOG})
    assert "`measured`:" in document and "`derived`:" in document
    assert "`modeled`:" not in document and "`assumption`:" not in document


def test_every_format_and_direction_has_wording() -> None:
    assert set(_SHOWN_AS) == set(MetricFormat)
    assert set(_BETTER) == {True, False, None}
    # Identifiers and pipeline bookkeeping are not metrics.
    assert set(_ORIGIN) == set(Provenance) - {Provenance.IDENTIFIER, Provenance.OPERATIONAL}


def test_says_it_is_generated() -> None:
    assert "Do not edit by hand" in render_metric_glossary({"Players": CATALOG})
