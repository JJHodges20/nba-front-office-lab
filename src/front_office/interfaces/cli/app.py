"""The ``fol`` command (Front Office Lab)."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table
from rich.text import Text

from front_office import __version__
from front_office.config import ConfigError, load_all_season_rules, load_settings
from front_office.domain import PayrollLine, Season
from front_office.domain.dictionary import render_data_dictionary
from front_office.domain.tables import ALL_TABLES, PLANNED_TABLES
from front_office.pipelines.check import CheckSeverity, check_raw_data
from front_office.pipelines.contracts import (
    TEMPLATE_SEASONS,
    ContractImportError,
    import_contract_file,
    write_contract_template,
)
from front_office.pipelines.ingest import (
    FetchOutcome,
    FetchStatus,
    build_ingestor,
    default_plan,
)
from front_office.pipelines.inventory import raw_inventory

DATA_DICTIONARY = "docs/DATA_DICTIONARY.md"

app = typer.Typer(
    help="NBA Front Office Lab: ingest, inspect and analyse league data.",
    no_args_is_help=True,
    add_completion=False,
)
contracts_app = typer.Typer(
    help="Bring in player contract data from a file you supply.", no_args_is_help=True
)
app.add_typer(contracts_app, name="contracts")
console = Console()


def _say(text: str, *, style: str = "") -> None:
    """Print text exactly as given.

    Data is never passed to rich as markup: a season scope such as ``[all seasons]`` or
    a name in square brackets would otherwise be swallowed as a style tag.
    """
    console.print(Text(text, style=style), highlight=False)


def _tagged(tag: str, style: str, text: str) -> None:
    """Print a coloured tag followed by text that is not read as markup."""
    console.print(Text.assemble((tag, style), "  ", text), highlight=False)


def _fail(error: Exception) -> typer.Exit:
    console.print(Text.assemble(("Error:", "bold red"), " ", str(error)), highlight=False)
    return typer.Exit(code=1)


def money(amount: int) -> str:
    return f"${amount:,.0f}"


@app.command()
def info() -> None:
    """Show the version, where data lives, and which seasons have cap rules."""
    try:
        settings = load_settings()
        rules = load_all_season_rules(settings.season_rules_dir)
    except ConfigError as error:
        raise _fail(error) from error

    table = Table(title=f"NBA Front Office Lab {__version__}", show_header=False)
    table.add_column(style="bold", no_wrap=True)
    table.add_column(overflow="fold")
    table.add_row("Project root", escape(str(settings.project_root)))
    table.add_row("Data directory", escape(str(settings.data_dir)))
    table.add_row("Database", escape(str(settings.database_path)))
    table.add_row("Team history from", settings.seasons.history_start)
    table.add_row("Player detail seasons", str(settings.seasons.player_detail_seasons))
    table.add_row("Cap rules configured", ", ".join(season.label for season in rules) or "none")
    console.print(table)


@app.command()
def seasons() -> None:
    """List the configured cap and roster rules for each season."""
    try:
        settings = load_settings()
        rules = load_all_season_rules(settings.season_rules_dir)
    except ConfigError as error:
        raise _fail(error) from error
    if not rules:
        _say(f"No season rules found in {settings.season_rules_dir}")
        raise typer.Exit(code=1)

    # One column per season: the lines of a single season read top to bottom, lowest
    # threshold first, and the table stays narrow enough for an 80-column terminal.
    table = Table(title="Season cap rules (whole US dollars)")
    table.add_column("", style="bold", no_wrap=True)
    for season in rules:
        table.add_column(season.label, justify="right", no_wrap=True)
    configured = list(rules.values())
    table.add_row("Status", *(season_rules.status.value for season_rules in configured))
    for line in PayrollLine:
        table.add_row(line.title, *(money(season_rules.line(line)) for season_rules in configured))
    table.add_row(
        "Standard contracts",
        *(
            f"{season_rules.roster.min_standard_contracts}-{season_rules.roster.max_standard_contracts}"
            for season_rules in configured
        ),
    )
    table.add_row(
        "Two-way contracts",
        *(str(season_rules.roster.max_two_way_contracts) for season_rules in configured),
    )
    console.print(table)


@app.command()
def dictionary(
    write: Annotated[
        bool, typer.Option("--write", help=f"Write {DATA_DICTIONARY} instead of printing.")
    ] = False,
) -> None:
    """Render the data dictionary from the table contracts."""
    document = render_data_dictionary(ALL_TABLES, PLANNED_TABLES)
    if not write:
        typer.echo(document, nl=False)
        return
    try:
        target = load_settings().project_root / DATA_DICTIONARY
    except ConfigError as error:
        raise _fail(error) from error
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(document, encoding="utf-8", newline="\n")
    _say(f"Wrote {target} ({len(ALL_TABLES)} tables)")


_STATUS_STYLE = {
    FetchStatus.STORED: "green",
    FetchStatus.UNCHANGED: "cyan",
    FetchStatus.SKIPPED: "dim",
    FetchStatus.FAILED: "bold red",
}


@app.command()
def ingest(
    season: Annotated[
        list[str] | None,
        typer.Option(
            "--season",
            "-s",
            help="Season to fetch, e.g. 2025-26. Repeat for several. Default: the full plan.",
        ),
    ] = None,
    teams_only: Annotated[
        bool, typer.Option("--teams-only", help="Skip player-level datasets.")
    ] = False,
    force: Annotated[
        bool,
        typer.Option("--force", help="Refetch even when the stored snapshot is still current."),
    ] = False,
) -> None:
    """Fetch raw data from stats.nba.com into the raw store.

    With no --season, fetches team history from the configured start plus player detail
    for the most recent seasons. Finished seasons already in the store are skipped.
    """
    try:
        settings = load_settings()
        plan = default_plan(settings, date.today())
        chosen = [Season.parse(label) for label in season] if season else list(plan.seasons)
    except (ConfigError, ValueError) as error:
        raise _fail(error) from error

    def report(outcome: FetchOutcome) -> None:
        if outcome.status is FetchStatus.SKIPPED:
            return
        style = _STATUS_STYLE[outcome.status]
        detail = outcome.error if outcome.error else f"{outcome.rows} rows"
        console.print(
            Text.assemble(
                (f"{outcome.status.value:>9}", style),
                f"  {outcome.request.describe()}  ",
                (detail, "dim"),
            ),
            highlight=False,
        )

    ingestor = build_ingestor(settings, force=force, on_outcome=report)
    outcomes = ingestor.ingest_globals(plan.current)
    for one_season in chosen:
        # A season named explicitly gets player detail unless --teams-only says otherwise.
        players = not teams_only and (bool(season) or one_season in plan.player_detail)
        outcomes += ingestor.ingest_season(one_season, players=players)

    counts = {status: 0 for status in FetchStatus}
    for outcome in outcomes:
        counts[outcome.status] += 1
    summary = ", ".join(f"{count} {status.value}" for status, count in counts.items() if count)
    _say(f"\n{len(outcomes)} requests: {summary}")
    if counts[FetchStatus.FAILED]:
        _say("Some requests failed; run the command again to retry them.", style="bold red")
        raise typer.Exit(code=1)


@app.command()
def raw() -> None:
    """Summarise what the raw store holds."""
    try:
        settings = load_settings()
    except ConfigError as error:
        raise _fail(error) from error
    inventory = raw_inventory(settings)
    if not inventory:
        _say(f"The raw store at {settings.raw_dir} is empty. Run: fol ingest")
        return

    table = Table(title=escape(f"Raw store: {settings.raw_dir}"))
    table.add_column("Source")
    table.add_column("Dataset", style="bold")
    table.add_column("Partitions", justify="right")
    table.add_column("Snapshots", justify="right")
    table.add_column("Seasons")
    table.add_column("Newest fetch (UTC)")
    for entry in inventory:
        seasons_held = f"{entry.first_season} to {entry.last_season}" if entry.first_season else "-"
        table.add_row(
            entry.source,
            entry.dataset,
            str(entry.partitions),
            str(entry.snapshots),
            seasons_held,
            entry.newest_fetch.strftime("%Y-%m-%d %H:%M"),
        )
    console.print(table)


@app.command()
def check() -> None:
    """Normalise the raw store and run every data-quality check. Writes nothing."""
    try:
        settings = load_settings()
    except ConfigError as error:
        raise _fail(error) from error
    report = check_raw_data(settings)

    tables = Table(title="Normalised tables")
    tables.add_column("Table", style="bold")
    tables.add_column("Rows", justify="right")
    for name, frame in report.tables.frames.items():
        tables.add_row(name, f"{len(frame):,}")
    console.print(tables)

    for issue in report.tables.errors:
        _tagged("not built", "bold red", f"{issue.table} [{issue.scope}]: {issue.message}")
    for issue in report.tables.notes:
        _tagged("note", "cyan", f"{issue.table} [{issue.scope}]: {issue.message}")

    for result in report.failed_checks:
        style = "bold red" if result.severity is CheckSeverity.ERROR else "yellow"
        _tagged(
            result.severity.value,
            style,
            f"{result.check}: {result.failures:,} of {result.examined:,} failed. "
            f"{result.description}",
        )
        for example in result.examples:
            _say(f"         {example}", style="dim")

    passed = len(report.checks) - len(report.failed_checks)
    _say(
        f"\n{len(report.checks)} checks: {passed} passed, "
        f"{len(report.check_warnings)} with warnings, {len(report.check_errors)} with errors; "
        f"{len(report.tables.errors)} table parts not built."
    )
    if not report.ok:
        raise typer.Exit(code=1)


@contracts_app.command("template")
def contracts_template(
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Where to write it. Default: data/imports."),
    ] = None,
    seasons: Annotated[
        int, typer.Option("--seasons", min=1, max=10, help="How many season columns to include.")
    ] = TEMPLATE_SEASONS,
) -> None:
    """Write a contract file listing every rostered player, with the salaries left blank."""
    try:
        settings = load_settings()
        path, players = write_contract_template(
            settings, today=date.today(), output=output, seasons=seasons
        )
    except (ConfigError, ContractImportError) as error:
        raise _fail(error) from error
    _say(f"Wrote {path}")
    _say(
        f"{players} players listed. Fill in the salaries from a source you are entitled to "
        'use, then run: fol contracts import <file> --source "<where the figures came from>"'
    )


@contracts_app.command("import")
def contracts_import(
    file: Annotated[Path, typer.Argument(help="The contract file (CSV, UTF-8).")],
    source: Annotated[
        str,
        typer.Option("--source", help="Where the figures came from. Stored with the data."),
    ],
    as_of: Annotated[
        str | None,
        typer.Option("--as-of", help="Date the figures were current (YYYY-MM-DD). Default: today."),
    ] = None,
) -> None:
    """Validate a contract file and store it. See docs/CONTRACT_DATA.md for the format."""
    try:
        settings = load_settings()
        current = date.fromisoformat(as_of) if as_of else date.today()
    except ConfigError as error:
        raise _fail(error) from error
    except ValueError:
        raise _fail(ValueError(f"--as-of must be a date like 2026-10-01, not {as_of!r}")) from None
    try:
        report = import_contract_file(settings, file, source_label=source, as_of=current)
    except ContractImportError as error:
        raise _fail(error) from error

    _say(
        f"Read {report.rows_read} rows: {report.contracts} contracts for {report.players} "
        f"players, {report.contract_years} contract seasons "
        f"({report.seasons[0]} to {report.seasons[-1]})."
    )
    if report.seasons_without_cap:
        _tagged(
            "note",
            "cyan",
            f"No salary cap is configured for {', '.join(report.seasons_without_cap)}; "
            "salaries in those seasons have no cap share until a rules file is added to "
            "configs/seasons.",
        )
    if report.unmatched:
        _tagged(
            "warning",
            "yellow",
            f"{len(report.unmatched)} row(s) could not be matched and were left out:",
        )
        for row in report.unmatched:
            team = f" ({row.team})" if row.team else ""
            _say(f"         line {row.line}: {row.player}{team} - {row.reason}")
    if not report.stored:
        _say("This file is identical to the last import; nothing new was stored.")
    _say("Run 'fol check' to validate the contract data against the rest.")


def main() -> None:
    # Player names include characters the legacy Windows code page cannot encode. When
    # output is piped or redirected, write UTF-8 instead of failing on them.
    for stream in (sys.stdout, sys.stderr):
        if not stream.isatty() and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    app()


if __name__ == "__main__":
    main()
