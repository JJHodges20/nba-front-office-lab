"""The ``fol`` command (Front Office Lab)."""

from __future__ import annotations

import sys
from datetime import date
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from front_office import __version__
from front_office.config import ConfigError, load_all_season_rules, load_settings
from front_office.domain import PayrollLine, Season
from front_office.domain.dictionary import render_data_dictionary
from front_office.domain.tables import ALL_TABLES, PLANNED_TABLES
from front_office.pipelines.check import CheckSeverity, check_raw_data
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
console = Console()


def _fail(error: Exception) -> typer.Exit:
    console.print(f"[bold red]Error:[/bold red] {error}")
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
    table.add_row("Project root", str(settings.project_root))
    table.add_row("Data directory", str(settings.data_dir))
    table.add_row("Database", str(settings.database_path))
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
        console.print(f"No season rules found in {settings.season_rules_dir}")
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
    console.print(f"Wrote {target} ({len(ALL_TABLES)} tables)")


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
            f"[{style}]{outcome.status.value:>9}[/{style}]  {outcome.request.describe()}  "
            f"[dim]{detail}[/dim]",
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
    console.print(f"\n{len(outcomes)} requests: {summary}", highlight=False)
    if counts[FetchStatus.FAILED]:
        console.print("[bold red]Some requests failed; run the command again to retry them.[/]")
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
        console.print(f"The raw store at {settings.raw_dir} is empty. Run: fol ingest")
        return

    table = Table(title=f"Raw store: {settings.raw_dir}")
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
        console.print(f"[bold red]not built[/]  {issue.table} [{issue.scope}]: {issue.message}")
    for issue in report.tables.notes:
        console.print(
            f"[cyan]note[/]  {issue.table} [{issue.scope}]: {issue.message}", highlight=False
        )

    for result in report.failed_checks:
        style = "bold red" if result.severity is CheckSeverity.ERROR else "yellow"
        console.print(
            f"[{style}]{result.severity.value}[/]  {result.check}: {result.failures:,} of "
            f"{result.examined:,} failed. {result.description}",
            highlight=False,
        )
        for example in result.examples:
            console.print(f"         [dim]{example}[/dim]", highlight=False)

    passed = len(report.checks) - len(report.failed_checks)
    console.print(
        f"\n{len(report.checks)} checks: {passed} passed, "
        f"{len(report.check_warnings)} with warnings, {len(report.check_errors)} with errors; "
        f"{len(report.tables.errors)} table parts not built.",
        highlight=False,
    )
    if not report.ok:
        raise typer.Exit(code=1)


def main() -> None:
    # Player names include characters the legacy Windows code page cannot encode. When
    # output is piped or redirected, write UTF-8 instead of failing on them.
    for stream in (sys.stdout, sys.stderr):
        if not stream.isatty() and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    app()


if __name__ == "__main__":
    main()
