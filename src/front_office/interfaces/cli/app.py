"""The ``fol`` command (Front Office Lab)."""

from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table

from front_office import __version__
from front_office.config import ConfigError, load_all_season_rules, load_settings
from front_office.domain import PayrollLine
from front_office.domain.dictionary import render_data_dictionary
from front_office.domain.tables import ALL_TABLES, PLANNED_TABLES

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
    write: bool = typer.Option(
        False, "--write", help=f"Write {DATA_DICTIONARY} instead of printing."
    ),
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


def main() -> None:
    app()


if __name__ == "__main__":
    main()
