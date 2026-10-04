"""The ``fol`` command (Front Office Lab)."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from datetime import date
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table
from rich.text import Text

from front_office import __version__
from front_office.config import (
    ConfigError,
    Settings,
    load_all_season_rules,
    load_settings,
    load_value_model,
    value_model_path,
)
from front_office.config.settings import ENV_HOME
from front_office.domain import PayrollLine, Season
from front_office.domain.dictionary import render_data_dictionary
from front_office.domain.tables import ALL_TABLES, PLANNED_TABLES
from front_office.domain.value_model import Comparison, ValueModel
from front_office.pipelines.build import build_database, database_status, log_fetches
from front_office.pipelines.check import CheckSeverity, DataReport, check_raw_data
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
from front_office.pipelines.value import FIT_COMMAND, ValueFitError, fit_value, write_value_model
from front_office.services import Lab, LabNotBuilt
from front_office.services.benchmark_report import benchmark_report
from front_office.services.glossary import METRIC_CATALOGS, metric_glossary
from front_office.services.value_report import NoValueModel, value_report

DATA_DICTIONARY = "docs/DATA_DICTIONARY.md"
METRIC_GLOSSARY = "docs/METRICS.md"
BENCHMARK_REPORT = "docs/research/BENCHMARKS.md"
VALUE_REPORT = "docs/research/PLAYER_VALUE.md"
WORKBENCH = "apps/workbench/app.py"
DEFAULT_PORT = 8501
STARTUP_SECONDS = 30

app = typer.Typer(
    help="NBA Front Office Lab: ingest, inspect and analyse league data.",
    no_args_is_help=True,
    add_completion=False,
)
contracts_app = typer.Typer(
    help="Bring in player contract data from a file you supply.", no_args_is_help=True
)
app.add_typer(contracts_app, name="contracts")
value_app = typer.Typer(
    help="The player value model: fit it, test it, see what it rests on.", no_args_is_help=True
)
app.add_typer(value_app, name="value")
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
    table.add_row("Player statistics from", settings.player_history_start.label)
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


@app.command()
def metrics(
    write: Annotated[
        bool, typer.Option("--write", help=f"Write {METRIC_GLOSSARY} instead of printing.")
    ] = False,
) -> None:
    """Render the metric glossary from the metric catalogs."""
    document = metric_glossary()
    if not write:
        typer.echo(document, nl=False)
        return
    try:
        target = load_settings().project_root / METRIC_GLOSSARY
    except ConfigError as error:
        raise _fail(error) from error
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(document, encoding="utf-8", newline="\n")
    count = sum(len(catalog) for catalog in METRIC_CATALOGS.values())
    _say(f"Wrote {target} ({count} metrics)")


@app.command()
def benchmarks(
    write: Annotated[
        bool, typer.Option("--write", help=f"Write {BENCHMARK_REPORT} instead of printing.")
    ] = False,
) -> None:
    """Write up the benchmark research: what past contenders looked like, from the database."""
    try:
        settings = load_settings()
        # Opening the lab creates the database; asking a question should not.
        if not database_status(settings).exists:
            raise LabNotBuilt
        with Lab(settings) as lab:
            lab.require_built()
            document = benchmark_report(lab)
            seasons = len(lab.benchmarks.seasons())
    except (ConfigError, LabNotBuilt) as error:
        raise _fail(error) from error
    if not write:
        typer.echo(document, nl=False)
        return
    target = settings.project_root / BENCHMARK_REPORT
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(document, encoding="utf-8", newline="\n")
    _say(f"Wrote {target} ({seasons} completed seasons)")


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
    except ConfigError as error:
        raise _fail(error) from error
    if _ingest(settings, season, teams_only=teams_only, force=force):
        _say("Some requests failed; run the command again to retry them.", style="bold red")
        raise typer.Exit(code=1)


def _ingest(settings: Settings, season: list[str] | None, *, teams_only: bool, force: bool) -> int:
    """Run an ingest, print its progress, log it, and return how many requests failed."""
    try:
        plan = default_plan(settings, date.today())
        chosen = [Season.parse(label) for label in season] if season else list(plan.seasons)
    except ValueError as error:
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
        # A season named explicitly gets everything unless --teams-only says otherwise.
        players = not teams_only and (bool(season) or one_season in plan.player_stats)
        detail = not teams_only and (bool(season) or one_season in plan.player_detail)
        outcomes += ingestor.ingest_season(one_season, players=players, detail=detail)

    counts = {status: 0 for status in FetchStatus}
    for outcome in outcomes:
        counts[outcome.status] += 1
    summary = ", ".join(f"{count} {status.value}" for status, count in counts.items() if count)
    _say(f"\n{len(outcomes)} requests: {summary}")
    log_fetches(settings, outcomes)
    return counts[FetchStatus.FAILED]


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
    try:
        report = check_raw_data(settings)
    except ConfigError as error:
        raise _fail(error) from error
    _print_data_report(report)
    if not report.ok:
        raise typer.Exit(code=1)


def _print_data_report(report: DataReport) -> None:
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


@app.command()
def build(
    force: Annotated[
        bool,
        typer.Option("--force", help="Load even if that empties a table that now holds data."),
    ] = False,
) -> None:
    """Rebuild the database from the raw store, replacing the league tables in one step."""
    try:
        settings = load_settings()
    except ConfigError as error:
        raise _fail(error) from error
    _build(settings, force=force)


def _build(settings: Settings, *, force: bool) -> None:
    try:
        report = build_database(settings, force=force)
    except ConfigError as error:
        raise _fail(error) from error
    _print_data_report(report.data)
    if not report.loaded:
        raise _fail(RuntimeError(report.refused_because))
    _say(
        f"Loaded {report.rows_loaded:,} rows into {settings.database_path} "
        f"(build {report.build_id})."
    )
    if not report.ok:
        _say("The build loaded with problems; see above.", style="bold red")
        raise typer.Exit(code=1)


@app.command()
def refresh(
    teams_only: Annotated[
        bool, typer.Option("--teams-only", help="Skip player-level datasets.")
    ] = False,
) -> None:
    """Fetch whatever is new from stats.nba.com, then rebuild the database."""
    try:
        settings = load_settings()
    except ConfigError as error:
        raise _fail(error) from error
    failed = _ingest(settings, None, teams_only=teams_only, force=False)
    if failed:
        _say(
            f"{failed} request(s) failed; building from what is stored. Run the command "
            "again to retry them.",
            style="yellow",
        )
    _build(settings, force=False)
    if failed:
        raise typer.Exit(code=1)


@app.command()
def db() -> None:
    """Show what the database holds and how the last build went."""
    try:
        settings = load_settings()
    except ConfigError as error:
        raise _fail(error) from error
    status = database_status(settings)
    if not status.exists:
        _say(f"There is no database at {settings.database_path} yet. Run: fol build")
        return

    # The path goes on its own line: as a title it would be squeezed to the table's width.
    _say(f"Database: {settings.database_path}")
    if not status.row_counts:
        _say("No build has completed yet. Run: fol build")
        return
    table = Table()
    table.add_column("Table", style="bold")
    table.add_column("Rows", justify="right")
    for name, rows in status.row_counts.items():
        table.add_row(name, f"{rows:,}")
    console.print(table)

    if status.latest_build is None:
        _say("No build has completed yet. Run: fol build")
        return
    latest = status.latest_build
    _say(
        f"Build {latest['build_id']} finished {latest['finished_at']:%Y-%m-%d %H:%M} UTC "
        f"({latest['status']}): {latest['rows_loaded']:,} rows, "
        f"{latest['build_errors']} table parts not built, {latest['build_notes']} notes, "
        f"{latest['check_errors']} check errors, {latest['check_warnings']} check warnings."
    )
    if not status.is_current:
        _tagged(
            "warning",
            "yellow",
            "the tables were built by a different version of the lab; run: fol build",
        )


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


@value_app.command("fit")
def value_fit(
    write: Annotated[
        bool,
        typer.Option("--write", help="Save the fitted model so that builds apply it."),
    ] = False,
) -> None:
    """Fit the player value model on the built database and test it out of sample.

    Without --write nothing changes: the fit is shown and thrown away.
    """
    try:
        settings = load_settings()
        report = fit_value(settings)
    except (ConfigError, ValueFitError) as error:
        raise _fail(error) from error
    _print_value_model(report.model)
    if report.previous is not None and not report.changed:
        _say(
            f"\nThe same as revision {report.previous.revision}, already on file. Nothing to write."
        )
        return
    if not write:
        _say(f"\nNot saved. To save it as revision {report.model.revision}: {FIT_COMMAND}")
        return
    target = write_value_model(settings, report.model)
    _say(f"\nWrote {target} (revision {report.model.revision}). To apply it: fol build")


@value_app.command("show")
def value_show() -> None:
    """Show the fitted player value model that builds apply, and the evidence for it."""
    try:
        settings = load_settings()
        model = load_value_model(settings.config_dir)
    except ConfigError as error:
        raise _fail(error) from error
    if model is None:
        _say(f"No value model has been fitted ({value_model_path(settings.config_dir)}).")
        _say(f"Run: {FIT_COMMAND}")
        raise typer.Exit(code=1)
    _say(f"Revision {model.revision}, fitted {model.fitted_at:%Y-%m-%d %H:%M} UTC.")
    _print_value_model(model)


@value_app.command("report")
def value_report_command(
    write: Annotated[
        bool, typer.Option("--write", help=f"Write {VALUE_REPORT} instead of printing.")
    ] = False,
) -> None:
    """Write up the value model: what it estimates, how it was tested, what it found."""
    try:
        settings = load_settings()
        # Opening the lab creates the database; asking a question should not.
        if not database_status(settings).exists:
            raise LabNotBuilt
        with Lab(settings) as lab:
            lab.require_built()
            document = value_report(lab)
            revision = lab.value.status().revision
    except (ConfigError, LabNotBuilt, NoValueModel) as error:
        raise _fail(error) from error
    if not write:
        typer.echo(document, nl=False)
        return
    target = settings.project_root / VALUE_REPORT
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(document, encoding="utf-8", newline="\n")
    _say(f"Wrote {target} (revision {revision} of the value model)")


def _print_value_model(model: ValueModel) -> None:
    on, tested = model.fitted_on, model.validation
    _say(
        f"Fitted on {on.team_seasons:,} team-seasons and {on.player_seasons:,} player-seasons, "
        f"{on.first_season} to {on.last_season}."
    )
    _say(
        f"Tested on {tested.team_seasons:,} team-seasons, {tested.first_test_season} to "
        f"{tested.last_test_season}, each predicted from the seasons before it."
    )
    confidence = f"{model.spec.confidence:.0%}"

    def rows(table: Table, items: tuple[Comparison, ...]) -> None:
        for item in items:
            apart = "" if item.is_distinguishable else "  (not distinguishable)"
            table.add_row(
                item.label,
                f"{item.rmse:.2f}",
                f"{item.mae:.2f}",
                f"{item.difference:+.2f} ({item.low:+.2f} to {item.high:+.2f}){apart}",
            )

    against = Table(title="Predicting a team's net rating, out of sample")
    against.add_column("Method", style="bold")
    against.add_column("RMSE", justify="right")
    against.add_column("MAE", justify="right")
    against.add_column(f"Value model's RMSE less this ({confidence} interval)")
    against.add_row("Value model", f"{tested.net.rmse:.2f}", f"{tested.net.mae:.2f}", "")
    rows(against, tested.baselines)
    console.print(against)

    without = Table(title="The value model with one part left out")
    without.add_column("Left out", style="bold")
    without.add_column("RMSE", justify="right")
    without.add_column("MAE", justify="right")
    without.add_column(f"RMSE less the full model's ({confidence} interval)")
    rows(without, tested.ablations)
    console.print(without)

    weights = Table(title=f"Weights, with {confidence} intervals from resampling seasons")
    weights.add_column("Term", style="bold")
    for side in ("Offense", "Defense", "Both"):
        weights.add_column(side, justify="right")
    for term in model.terms:
        weights.add_row(
            term.key,
            f"{term.offense:+.3f} ({term.offense_low:+.2f} to {term.offense_high:+.2f})",
            f"{term.defense:+.3f} ({term.defense_low:+.2f} to {term.defense_high:+.2f})",
            f"{term.net:+.3f} ({term.net_low:+.2f} to {term.net_high:+.2f})",
        )
    console.print(weights)

    minutes = model.availability
    _say(
        f"Offense RMSE {tested.offense.rmse:.2f}, defense {tested.defense.rmse:.2f}. "
        f"Replacement level {model.replacement_level:+.2f} per 100 possessions. A team's "
        f"net rating is {tested.same_season.slope:.2f} times the sum of its players' "
        f"impacts (correlation {tested.same_season.correlation:.2f})."
    )
    _say(
        f"Next season's share of team minutes: RMSE {minutes.rmse:.3f} against "
        f"{minutes.baseline_rmse:.3f} for assuming last season's share "
        f"({minutes.difference:+.3f}, {minutes.low:+.3f} to {minutes.high:+.3f}; "
        f"{minutes.players:,} player-seasons)."
    )


@app.command()
def ui(
    port: Annotated[
        int, typer.Option("--port", min=1024, max=65535, help="Port to serve the workbench on.")
    ] = DEFAULT_PORT,
    no_browser: Annotated[
        bool, typer.Option("--no-browser", help="Start the workbench without opening a browser.")
    ] = False,
) -> None:
    """Open the workbench: the lab's pages in your browser. Stop it with Ctrl+C."""
    try:
        settings = load_settings()
    except ConfigError as error:
        raise _fail(error) from error
    script = settings.project_root / WORKBENCH
    if not script.is_file():
        raise _fail(FileNotFoundError(f"the workbench is missing: {script}"))

    url = f"http://localhost:{port}"
    _say(f"Starting the workbench at {url} (Ctrl+C to stop).")
    command = [sys.executable, "-m", "streamlit", "run", str(script), "--server.port", str(port)]
    # The workbench finds its data the way every command does; pin it to this project.
    environment = {**os.environ, ENV_HOME: str(settings.project_root)}
    if not no_browser:
        threading.Thread(target=_open_when_ready, args=(url,), daemon=True).start()
    try:
        finished = subprocess.run(command, cwd=settings.project_root, env=environment, check=False)
    except KeyboardInterrupt:
        return
    if finished.returncode:
        raise typer.Exit(code=finished.returncode)


def _open_when_ready(url: str, *, patience: float = STARTUP_SECONDS) -> bool:
    """Open the browser once the workbench answers; give up quietly if it never does."""
    deadline = time.monotonic() + patience
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{url}/_stcore/health", timeout=2):
                webbrowser.open(url)
                return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.5)
    return False


def main() -> None:
    # Player names include characters the legacy Windows code page cannot encode. When
    # output is piped or redirected, write UTF-8 instead of failing on them.
    for stream in (sys.stdout, sys.stderr):
        if not stream.isatty() and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    app()


if __name__ == "__main__":
    main()
