"""The lab's own data as the assistant's read tools (docs/AI_ASSISTANT_SPEC.md).

Each handler calls existing service methods and nothing else: it picks the rows and
columns a question needs, writes every figure the way the workbench shows it (the metric
catalogs' own formats), and says where the figures came from. No handler computes a
metric, ranks anything or fits anything; a figure the services do not return is not
given. A season or a row the lab does not hold is said to be missing, with what it does
hold.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any

import pandas as pd

from front_office.assistant import tools as t
from front_office.domain.assistant import Chart, Evidence, EvidenceKind, ResultStatus
from front_office.domain.eras import Era
from front_office.domain.metrics import MetricCatalog
from front_office.domain.proposals import RosterProposal
from front_office.domain.schema import Provenance
from front_office.domain.seasons import SeasonType
from front_office.services import METRIC_CATALOGS, Lab, Qualification, Window
from front_office.services.entities import fold

MAX_ROWS = 12
"""Rows of a table the model reads; the page shows them all."""
FORM_GAMES = 10
"""Games a comparison of form covers when the call does not say."""
DASH = "—"
KIND_OF = {
    Provenance.MEASURED: "measured",
    Provenance.DERIVED: "derived",
    Provenance.MODELED: "modeled",
    Provenance.ASSUMPTION: "assumption",
}
PHASES = {SeasonType.REGULAR.value: "regular season", SeasonType.PLAYOFFS.value: "playoffs"}
TEAM_KEYS = (
    "wins",
    "losses",
    "win_pct",
    "net_rating",
    "off_rating",
    "def_rating",
    "rel_off_rating",
    "rel_def_rating",
    "pace",
    "pts_per_game",
    "opp_pts_per_game",
    "point_diff_per_game",
    "ts_pct",
    "efg_pct",
    "tov_pct",
    "oreb_pct",
    "ft_rate",
    "fg3a_rate",
    "fg3_pct",
)
PLAYER_KEYS = (
    "games_played",
    "games_started",
    "minutes_per_game",
    "pts_per_game",
    "reb_per_game",
    "ast_per_game",
    "stl_per_game",
    "blk_per_game",
    "tov_per_game",
    "fg_pct",
    "fg3_pct",
    "ft_pct",
    "efg_pct",
    "ts_pct",
    "usage_pct",
    "assist_pct",
    "reb_pct",
    "net_rating",
    "on_off_net",
)
COMPARE_KEYS = ("pts_per_game", "reb_per_game", "ast_per_game", "ts_pct", "usage_pct", "net_rating")
FORM_KEYS = (
    "games_played",
    "minutes_per_game",
    "pts_per_game",
    "reb_per_game",
    "ast_per_game",
    "ts_pct",
)
CAREER_KEYS = (
    "games_played",
    "minutes_per_game",
    "pts_per_game",
    "reb_per_game",
    "ast_per_game",
    "ts_pct",
)
TEAM_GAME_KEYS = ("pts", "opp_pts", "net_rating", "ts_pct")
PLAYER_GAME_KEYS = ("minutes", "pts", "reb", "ast", "ts_pct")
RANKED_TEAM_KEYS = ("net_rating", "off_rating", "def_rating", "pace")
TREND_KEYS = ("pace", "off_rating", "ts_pct", "fg3a_rate", "pts_per_game")


@dataclass(frozen=True, slots=True)
class Found:
    """What a handler returns; the executor adds the result's id and the call."""

    status: ResultStatus
    title: str
    text: str
    table: pd.DataFrame | None = None
    evidence: tuple[Evidence, ...] = ()
    warnings: tuple[str, ...] = ()
    kinds: tuple[str, ...] = ()
    limits: tuple[str, ...] = ()
    charts: tuple[Chart, ...] = ()
    proposals: tuple[RosterProposal, ...] = ()


Handler = Callable[[Lab, Any], Found]


def missing(title: str, why: str, evidence: tuple[Evidence, ...] = ()) -> Found:
    """A result that found nothing; without ``evidence`` the executor adds the build."""
    return Found(ResultStatus.EMPTY, title, why, evidence=evidence)


# --- formatting --------------------------------------------------------------------------


def ordinal(value: object) -> str:
    number = int(value)  # type: ignore[call-overload]
    suffix = (
        "th" if 10 <= number % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")
    )
    return f"{number}{suffix}"


def shown(catalog: MetricCatalog | None, key: str, value: object) -> str:
    if catalog is not None and key in catalog:
        return catalog[key].format_value(None if _missing(value) else value)  # type: ignore[arg-type]
    if _missing(value):
        return DASH
    if isinstance(value, float):
        return f"{value:.1f}"
    return str(value)


def _missing(value: object) -> bool:
    try:
        return value is None or bool(pd.isna(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False


def metric_key(catalog: MetricCatalog, text: str) -> str | None:
    """The catalog key ``text`` means: the key itself, or a metric's name or label written
    any way - ``points_per_game`` is "Points per game", ``ts%`` is "TS%"."""
    if text in catalog:
        return text
    wanted = fold(text.replace("%", " pct"))
    for spec in catalog:
        if wanted in (fold(spec.key), fold(spec.name), fold(spec.label.replace("%", " pct"))):
            return spec.key
    return None


def _folded(text: str) -> str:
    return fold(text.replace("%", " pct"))


def label(catalog: MetricCatalog, key: str) -> str:
    return catalog[key].name if key in catalog else key.replace("_", " ")


def grid(header: Sequence[str], rows: Iterable[Sequence[str]], *, limit: int = MAX_ROWS) -> str:
    """A small table as the model reads it, with a note when rows were left out."""
    rows = list(rows)
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows[:limit]]
    if len(rows) > limit:
        lines.append(f"(and {len(rows) - limit} more rows on the page)")
    return "\n".join(lines)


def kinds_of(
    catalog: MetricCatalog, keys: Iterable[str], estimated: Iterable[str] = ()
) -> tuple[str, ...]:
    found = {KIND_OF.get(catalog[key].provenance) for key in keys if key in catalog} - {None}
    if set(estimated) & set(keys):
        found.add("estimate")
    return tuple(sorted(found))  # type: ignore[arg-type]


def seasons_held(labels: Sequence[str]) -> str:
    ordered = sorted(labels)
    if not ordered:
        return "no seasons"
    if len(ordered) <= 4:
        return ", ".join(ordered)
    return f"{ordered[0]} to {ordered[-1]} ({len(ordered)} seasons)"


def phase(season_type: str) -> str:
    return PHASES.get(season_type, season_type)


# --- charts ------------------------------------------------------------------------------


def over_seasons(
    frame: pd.DataFrame,
    key: str,
    catalog: MetricCatalog,
    title: str,
    *,
    reference: float | None = None,
    reference_label: str = "",
) -> tuple[Chart, ...]:
    """A metric season by season, where there are two seasons or more, each once."""
    if key not in frame.columns:
        return ()
    plotted = frame[["season", key]].dropna(subset=[key])
    if len(plotted) < 2 or plotted["season"].duplicated().any():
        return ()
    plotted = plotted.sort_values("season").reset_index(drop=True)
    plotted = plotted.assign(text=[shown(catalog, key, value) for value in plotted[key]])
    chart = Chart(
        "line",
        title,
        plotted,
        x="season",
        y=key,
        text="text",
        y_title=label(catalog, key),
        metric=key,
        reference=reference,
        reference_label=reference_label,
    )
    return (chart,)


# --- evidence ----------------------------------------------------------------------------


def lab_evidence(lab: Lab, tables: str) -> Evidence:
    status = lab.status()
    built = status.built_at
    when = "" if built is None else f" of {built:%Y-%m-%d}"
    return Evidence(
        EvidenceKind.LAB,
        f"NBA.com statistics as the lab holds them, data build {status.build_id}{when}",
        location=tables,
        retrieved_at=built,
        build_id=status.build_id,
    )


def contract_evidence(lab: Lab) -> Evidence:
    sources = lab.contracts.sources()
    if sources.empty:
        return Evidence(
            EvidenceKind.CONTRACTS, "Contract file: none imported", location="contracts"
        )
    latest = sources.sort_values("as_of_date").iloc[-1]
    as_of = pd.Timestamp(latest["as_of_date"]).date()
    return Evidence(
        EvidenceKind.CONTRACTS,
        f"Contract file supplied by the user ({latest['source_label']}), as of {as_of:%Y-%m-%d}",
        location="contracts",
        effective_at=as_of,
    )


# --- handlers ----------------------------------------------------------------------------


def resolve_entities(lab: Lab, args: t.ResolveEntities) -> Found:
    candidates = lab.entities.resolve(args.text, kind=args.kind)
    title = f'Readings of "{args.text}"'
    if not candidates:
        return missing(title, f'The lab holds no player or team called "{args.text}".')
    table = pd.DataFrame(
        [(c.kind, c.id, c.name, c.detail, c.match) for c in candidates],
        columns=["kind", "id", "name", "detail", "match"],
    )
    text = grid(
        ["Kind", "Id", "Name", "Detail", "Matched on"],
        ([c.kind, str(c.id), c.name, c.detail or DASH, c.match] for c in candidates),
    )
    if len(candidates) > 1:
        text += "\nSeveral readings: ask the user which is meant."
    return Found(ResultStatus.OK, title, text, table, (lab_evidence(lab, "players, teams"),))


def data_status(lab: Lab, args: t.DataStatus) -> Found:
    status = lab.status()
    rows = [
        ("Data build", f"{status.build_id}, finished {status.built_at:%Y-%m-%d %H:%M} UTC"),
        ("Team statistics", seasons_held(status.team_seasons)),
        ("Player statistics", seasons_held(status.player_seasons)),
        ("Cap rules", seasons_held(status.cap_seasons)),
        (
            "Contract file",
            f"{seasons_held(status.contract_seasons)}, as of {status.contract_as_of:%Y-%m-%d}"
            if status.has_contracts
            else "none imported",
        ),
    ]
    rows += [(source.title, f"{source.state}: {source.detail}") for source in lab.health.sources()]
    value = lab.value.status()
    if value.is_fitted:
        rows.append(
            (
                "Player value model",
                f"revision {value.revision}, fitted on seasons to {value.fitted_through}",
            )
        )
    postseason = lab.postseason.status()
    if postseason.is_fitted:
        rows.append(("Postseason model", f"revision {postseason.revision}"))
    simulator = lab.simulator.status()
    if simulator.is_fitted:
        rows.append(("Simulator", f"revision {simulator.revision}"))
    for source in lab.current.status():
        if source.stored_at is None:
            state = "never fetched" if source.checked_at is None else f"failing: {source.detail}"
        else:
            state = (
                f"{source.state}, {source.rows} rows as of {source.stored_at:%Y-%m-%d %H:%M} UTC"
            )
        rows.append((f"Current {source.source} (since the build)", state))
    table = pd.DataFrame(rows, columns=["item", "state"])
    text = grid(["What", "State"], rows, limit=len(rows))
    return Found(
        ResultStatus.OK,
        "What the lab holds",
        text,
        table,
        (lab_evidence(lab, "builds, raw_snapshots"),),
    )


def team_stats(lab: Lab, args: t.TeamStats) -> Found:
    names = lab.team_labels()
    if args.view == "history":
        return _team_history(lab, args, names)
    held = lab.status().team_seasons
    team = names.at[args.team_id, "full_name"]
    title = f"{team}, {args.season} {phase(args.season_type)}"
    if args.season not in held:
        return missing(
            title,
            f"The lab holds team statistics for {seasons_held(held)}; nothing for {args.season}.",
        )
    window = Window(last_games=args.last_games) if args.last_games else Window()
    if args.view == "games":
        return _team_games(lab, args, title)
    if args.view == "rotation":
        return _rotation(lab, args, title)
    if args.view == "form":
        return _team_form(lab, args, title)
    table = lab.teams.table(args.season, args.season_type, window=window)
    if args.team_id not in table.teams.index:
        return missing(
            title, f"{team} has no {args.season} {phase(args.season_type)} games in the lab."
        )
    row, catalog = table.teams.loc[args.team_id], table.metrics
    ranks, count = table.ranks.loc[args.team_id], len(table.teams)
    estimated = set(table.estimated)
    lines = []
    keys = [key for key in TEAM_KEYS if key in table.teams.columns]
    for key in keys:
        approx = "≈ " if key in estimated else ""
        rank = (
            f"{ordinal(ranks[key])} of {count}"
            if key in ranks and not _missing(ranks[key])
            else DASH
        )
        average = shown(catalog, key, table.league.get(key))
        lines.append(
            [approx + label(catalog, key), approx + shown(catalog, key, row[key]), rank, average]
        )
    head = (
        f"{row['team_name']}, {args.season} {phase(args.season_type)}, {window.describe().lower()}."
    )
    if not _missing(row.get("conference_rank")):
        head += f" {ordinal(row['conference_rank'])} in the {row['conference']}."
    if isinstance(row.get("postseason_result"), str):
        head += f" Postseason: {row['postseason_result']}."
    text = (
        head
        + "\n"
        + grid(["Metric", "Value", "League rank", "League average"], lines, limit=len(lines))
    )
    warnings = ()
    if estimated:
        warnings = (
            "Ratings over a span of games are the lab's estimates from box scores (marked ≈).",
        )
    frame = pd.DataFrame(lines, columns=["metric", "value", "rank", "league_average"])
    return Found(
        ResultStatus.OK,
        title,
        text,
        frame,
        (lab_evidence(lab, "team_seasons, team_games"),),
        warnings,
        kinds_of(catalog, keys, estimated),
    )


def _team_history(lab: Lab, args: t.TeamStats, names: pd.DataFrame) -> Found:
    profile = lab.teams.profile(args.team_id)
    seasons = profile.seasons.sort_values("season", ascending=False)
    title = f"{names.at[args.team_id, 'full_name']}, every season on record"
    keys = ("wins", "losses", "net_rating", "rel_off_rating", "rel_def_rating")
    rows = [
        [s["season"], s["team_name"]]
        + [shown(profile.metrics, k, s[k]) for k in keys]
        + [s.get("postseason_result") or DASH]
        for _, s in seasons.iterrows()
    ]
    header = ["Season", "Team", *(label(profile.metrics, k) for k in keys), "Postseason"]
    team = names.at[args.team_id, "full_name"]
    return Found(
        ResultStatus.OK,
        title,
        grid(header, rows),
        seasons,
        (lab_evidence(lab, "team_seasons"),),
        kinds=kinds_of(profile.metrics, keys),
        charts=over_seasons(
            seasons,
            "net_rating",
            profile.metrics,
            f"{team}: net rating by season",
            reference=0.0,
            reference_label="League average",
        ),
    )


def _team_games(lab: Lab, args: t.TeamStats, title: str) -> Found:
    games = lab.teams.game_log(args.team_id, args.season, args.season_type)
    if games.empty:
        return missing(title, "No finished games in the lab for this team and season.")
    catalog = lab.teams.metrics
    rows = [
        [str(pd.Timestamp(g["game_date"]).date()), f"{g['venue']} {g['opponent']}", g["result"]]
        + [shown(catalog, k, g[k]) for k in TEAM_GAME_KEYS]
        for _, g in games.iterrows()
    ]
    header = ["Date", "Opponent", "Result", *(label(catalog, k) for k in TEAM_GAME_KEYS)]
    return Found(
        ResultStatus.OK,
        f"{title}: games, newest first",
        grid(header, rows),
        games,
        (lab_evidence(lab, "team_games"),),
        ("A game's ratings are the lab's estimates from its box score.",),
        ("measured", "estimate"),
    )


def _team_form(lab: Lab, args: t.TeamStats, title: str) -> Found:
    games = args.last_games or 10
    form = lab.teams.rolling(
        args.team_id, args.season, args.season_type, games=games, full_spans=True
    )
    if form.empty:
        return missing(title, f"Fewer than {games} games: no full span to average.")
    latest = form.iloc[-1]
    catalog = lab.teams.metrics
    keys = [
        k
        for k in ("net_rating", "off_rating", "def_rating", "pts_per_game", "ts_pct")
        if k in form.columns
    ]
    rows = [[label(catalog, k), "≈ " + shown(catalog, k, latest[k])] for k in keys]
    head = f"Over the {games} games to {pd.Timestamp(latest['game_date']).date()}."
    return Found(
        ResultStatus.OK,
        f"{title}: form",
        head + "\n" + grid(["Metric", "Value"], rows),
        form,
        (lab_evidence(lab, "team_games"),),
        ("Ratings over a span of games are the lab's estimates from box scores (marked ≈).",),
        ("estimate",),
    )


def _rotation(lab: Lab, args: t.TeamStats, title: str) -> Found:
    rotation = lab.teams.rotation(args.team_id, args.season, args.season_type)
    if rotation.empty:
        return missing(title, "No player statistics in the lab for this team and season.")
    catalog = lab.players.metrics
    keys = ("games_played", "minutes_per_game", "pts_per_game", "ts_pct")
    rows = [
        [r["player_name"], *(shown(catalog, k, r[k]) for k in keys)] for _, r in rotation.iterrows()
    ]
    return Found(
        ResultStatus.OK,
        f"{title}: who played, most minutes first",
        grid(["Player", *(label(catalog, k) for k in keys)], rows),
        rotation,
        (lab_evidence(lab, "player_game_logs"),),
        kinds=kinds_of(catalog, keys),
    )


def player_stats(lab: Lab, args: t.PlayerStats) -> Found:
    profile = lab.players.profile(args.player_id)
    name = profile.player["full_name"]
    title = f"{name}, {args.season} {phase(args.season_type)}"
    if args.view == "career":
        return _career(lab, args, profile, name)
    held = lab.status().player_seasons
    if args.season not in held:
        return missing(
            title,
            f"The lab holds player statistics for {seasons_held(held)}; nothing for {args.season}.",
        )
    if args.view == "games":
        return _player_games(lab, args, title)
    if args.view == "form":
        return _player_form(lab, args, title)
    window = Window(last_games=args.last_games) if args.last_games else Window()
    table = lab.players.table(
        args.season, args.season_type, window=window, qualification=Qualification()
    )
    if args.player_id not in table.players.index:
        return missing(
            title, f"{name} has no {args.season} {phase(args.season_type)} statistics in the lab."
        )
    row, catalog = table.players.loc[args.player_id], table.metrics
    percentiles = table.percentiles
    lines, ranked = [], []
    keys = [key for key in PLAYER_KEYS if key in table.players.columns]
    for key in keys:
        rank = DASH
        if key in percentiles.columns and args.player_id in percentiles.index:
            value = percentiles.at[args.player_id, key]
            if not _missing(value):
                rank = f"{ordinal(round(float(value)))} percentile"
                ranked.append((label(catalog, key), float(value), shown(catalog, key, row[key])))
        lines.append([label(catalog, key), shown(catalog, key, row[key]), rank])
    head = f"{name} ({row['team']}), {args.season} {phase(args.season_type)}, {window.describe().lower()}."
    text = (
        head
        + "\n"
        + grid(["Metric", "Value", "Among the season's players"], lines, limit=len(lines))
    )
    charts = ()
    if ranked:
        charts = (
            Chart(
                "percentiles",
                f"{name}: percentiles among the season's players, {args.season}",
                pd.DataFrame(ranked, columns=["metric", "percentile", "value"]),
                x="metric",
                y="percentile",
                text="value",
            ),
        )
    return Found(
        ResultStatus.OK,
        title,
        text,
        pd.DataFrame(lines, columns=["metric", "value", "percentile"]),
        (lab_evidence(lab, "player_seasons, player_game_logs"),),
        kinds=kinds_of(catalog, keys),
        charts=charts,
    )


def _career(lab: Lab, args: t.PlayerStats, profile: Any, name: str) -> Found:
    seasons = profile.seasons[profile.seasons["season_type"] == args.season_type]
    title = f"{name}, every {phase(args.season_type)} on record"
    if seasons.empty:
        return missing(title, f"No {phase(args.season_type)} statistics for {name} in the lab.")
    seasons = seasons.sort_values("season", ascending=False)
    catalog = profile.metrics
    rows = [
        [s["season"], s["team"]] + [shown(catalog, k, s[k]) for k in CAREER_KEYS]
        for _, s in seasons.iterrows()
    ]
    return Found(
        ResultStatus.OK,
        title,
        grid(["Season", "Team", *(label(catalog, k) for k in CAREER_KEYS)], rows),
        seasons,
        (lab_evidence(lab, "player_seasons"),),
        kinds=kinds_of(catalog, CAREER_KEYS),
        charts=over_seasons(seasons, "pts_per_game", catalog, f"{name}: points per game by season"),
    )


def _player_games(lab: Lab, args: t.PlayerStats, title: str) -> Found:
    games = lab.players.game_log(args.player_id, args.season, args.season_type)
    if games.empty:
        return missing(title, "No games in the lab for this player and season.")
    catalog = lab.players.metrics
    rows = [
        [str(pd.Timestamp(g["game_date"]).date()), f"{g['venue']} {g['opponent']}", g["result"]]
        + [shown(catalog, k, g[k]) for k in PLAYER_GAME_KEYS]
        for _, g in games.iterrows()
    ]
    head = f"{len(games)} games, newest first."
    return Found(
        ResultStatus.OK,
        f"{title}: games",
        head + "\n" + grid(["Date", "Opponent", "Result", *PLAYER_GAME_KEYS], rows),
        games,
        (lab_evidence(lab, "player_game_logs"),),
        kinds=("measured", "derived"),
    )


def _player_form(lab: Lab, args: t.PlayerStats, title: str) -> Found:
    games = args.last_games or 10
    form = lab.players.rolling(
        args.player_id, args.season, args.season_type, games=games, full_spans=True
    )
    if form.empty:
        return missing(title, f"Fewer than {games} games: no full span to average.")
    latest = form.iloc[-1]
    catalog = lab.players.metrics
    rows = [
        [label(catalog, k), shown(catalog, k, latest[k])] for k in FORM_KEYS if k in form.columns
    ]
    head = f"Over the {games} games to {pd.Timestamp(latest['game_date']).date()}."
    return Found(
        ResultStatus.OK,
        f"{title}: form",
        head + "\n" + grid(["Metric", "Value"], rows),
        form,
        (lab_evidence(lab, "player_game_logs"),),
        kinds=kinds_of(catalog, FORM_KEYS),
    )


def compare_players(lab: Lab, args: t.ComparePlayers) -> Found:
    held = lab.status().player_seasons
    title = f"Players compared, {args.season} {phase(args.season_type)}"
    if args.season not in held:
        return missing(
            title,
            f"The lab holds player statistics for {seasons_held(held)}; nothing for {args.season}.",
        )
    games = args.last_games or (FORM_GAMES if args.view == "form" else None)
    window = Window(last_games=games) if games else Window()
    table = lab.players.table(
        args.season, args.season_type, window=window, qualification=Qualification()
    )
    title = f"{title}, {window.describe().lower()}"
    catalog = table.metrics
    matched = {text: metric_key(catalog, text) for text in args.metrics}
    keys = list(dict.fromkeys(key for key in matched.values() if key)) or list(COMPARE_KEYS)
    unknown = [text for text, key in matched.items() if key is None]
    present = [p for p in args.player_ids if p in table.players.index]
    absent = [p for p in args.player_ids if p not in table.players.index]
    if len(present) < 2:
        return missing(
            title, "Fewer than two of these players have statistics for this season in the lab."
        )
    compared = lab.players.compare(table, present, keys)
    names = {p: table.players.at[p, "player_name"] for p in present}
    rows = []
    for key in keys:
        cells = []
        for player in present:
            match = compared[(compared["metric"] == key) & (compared["player_id"] == player)]
            if match.empty:
                cells.append(DASH)
                continue
            percentile = match.iloc[0]["percentile"]
            note = "" if _missing(percentile) else f" ({ordinal(round(float(percentile)))} pct.)"
            cells.append(f"{match.iloc[0]['shown']}{note}")
        rows.append([label(catalog, key), *cells])
    warnings = []
    if unknown:
        warnings.append(f"Not metrics the lab has: {', '.join(unknown)}.")
    if absent:
        warnings.append(f"No statistics this season for player ids {absent}.")
    ranked = compared[compared["percentile"].notna()]
    charts = ()
    if not ranked.empty:
        charts = (
            Chart(
                "comparison",
                f"{title}: percentiles among the season's players",
                ranked[["label", "player_name", "percentile", "shown"]].reset_index(drop=True),
                x="label",
                y="percentile",
                text="shown",
                who="player_name",
            ),
        )
    return Found(
        ResultStatus.OK,
        title,
        grid(["Metric", *(names[p] for p in present)], rows),
        compared,
        (lab_evidence(lab, "player_seasons"),),
        tuple(warnings),
        kinds_of(catalog, keys),
        charts=charts,
    )


def league_context(lab: Lab, args: t.LeagueContext) -> Found:
    season = args.season or lab.status().latest_stats_season
    view = args.view
    if view == "champions":
        champions = lab.league.champions()
        rows = [
            [
                c["season"],
                c["champion"],
                c["runner_up"],
                c["series"],
                f"{c['wins']}-{c['losses']}",
                f"{c['net_rating']:+.1f}",
                f"{ordinal(c['net_rating_rank'])} of {c['league_teams']}",
            ]  # fmt: skip
            for _, c in champions.iterrows()
        ]
        header = ["Season", "Champion", "Beat", "Finals", "Record", "Net rating", "Net rating rank"]
        return Found(
            ResultStatus.OK,
            "Every decided NBA Finals on record, newest first",
            grid(header, rows, limit=30),
            champions,
            (lab_evidence(lab, "playoff_results, team_seasons"),),
            kinds=("measured",),
        )
    held = lab.status().team_seasons
    if view in ("standings", "team_ranks", "playoffs") and season not in held:
        return missing(
            f"The league in {season}",
            f"The lab holds team statistics for {seasons_held(held)}; nothing for {season}.",
        )
    if view == "standings":
        standings = lab.league.standings(season)
        rows = [
            [
                s["conference"],
                ordinal(s["conference_rank"]),
                s["team_name"],
                f"{s['wins']}-{s['losses']}",
                f"{s['net_rating']:+.1f}",
                s.get("postseason_result") or DASH,
            ]  # fmt: skip
            for _, s in standings.iterrows()
        ]
        header = ["Conference", "Rank", "Team", "Record", "Net rating", "Postseason"]
        return Found(
            ResultStatus.OK,
            f"Standings, {season}",
            grid(header, rows, limit=30),
            standings,
            (lab_evidence(lab, "team_seasons"),),
            kinds=("measured",),
        )
    if view == "team_ranks":
        table = lab.teams.table(season)
        catalog = table.metrics
        ordered = table.teams.sort_values("net_rating", ascending=False)
        rows = [
            [r["team_name"], f"{r['wins']}-{r['losses']}"]
            + [
                f"{shown(catalog, k, r[k])} ({ordinal(table.ranks.at[team_id, k])})"
                for k in RANKED_TEAM_KEYS
            ]
            for team_id, r in ordered.iterrows()
        ]
        header = ["Team", "Record", *(label(catalog, k) for k in RANKED_TEAM_KEYS)]
        bars = pd.DataFrame(
            {
                "team": ordered["team_name"].to_numpy(),
                "net_rating": ordered["net_rating"].to_numpy(),
                "text": [shown(catalog, "net_rating", v) for v in ordered["net_rating"]],
            }
        )
        return Found(
            ResultStatus.OK,
            f"Every team, {season}, by net rating",
            grid(header, rows, limit=30),
            ordered,
            (lab_evidence(lab, "team_seasons"),),
            kinds=kinds_of(catalog, RANKED_TEAM_KEYS),
            charts=(
                Chart(
                    "bars",
                    f"Net rating, {season}",
                    bars,
                    x="team",
                    y="net_rating",
                    text="text",
                    y_title=label(catalog, "net_rating"),
                    metric="net_rating",
                ),
            ),
        )
    if view == "playoffs":
        series = lab.league.playoffs(season)
        if series.empty:
            return missing(f"The {season} playoffs", f"No playoff series in the lab for {season}.")
        rows = [
            [
                s["round_name"],
                f"{s['team_a']} v {s['team_b']}",
                f"{s['team_a_wins']}-{s['team_b_wins']}",
                s.get("winner") or DASH,
            ]
            for _, s in series.iterrows()
        ]
        return Found(
            ResultStatus.OK,
            f"The {season} playoffs, in bracket order",
            grid(["Round", "Series", "Games", "Winner"], rows, limit=20),
            series,
            (lab_evidence(lab, "playoff_results"),),
            kinds=("measured",),
        )
    averages = lab.league.averages()
    catalog = lab.teams.metrics
    recent = averages.tail(MAX_ROWS)
    rows = [
        [str(index), *(shown(catalog, k, row[k]) for k in TREND_KEYS)]
        for index, row in recent.iloc[::-1].iterrows()
    ]
    return Found(
        ResultStatus.OK,
        "League averages by season, newest first",
        grid(["Season", *(label(catalog, k) for k in TREND_KEYS)], rows),
        averages,
        (lab_evidence(lab, "team_seasons"),),
        kinds=kinds_of(catalog, TREND_KEYS),
    )


def historical_benchmarks(lab: Lab, args: t.HistoricalBenchmarks) -> Found:
    benchmarks = lab.benchmarks
    if args.first_season and args.last_season:
        era = Era.between(args.first_season, args.last_season)
    else:
        try:
            era = benchmarks.era(args.era)
        except KeyError:
            keys = ", ".join(e.key for e in benchmarks.eras.eras)
            return Found(
                ResultStatus.ERROR,
                "Benchmarks",
                f"No era called {args.era!r}; the eras are {keys}.",
            )
    stage = next(s for s in benchmarks.stages if s.key == args.stage)
    view = benchmarks.view(era)
    rates = benchmarks.rates(era, args.measure)
    rates = rates[rates["stage"] == args.stage]
    catalog = benchmarks.metrics
    measure = label(catalog, args.measure)
    rows = [
        [
            r["band"],
            str(r["teams"]),
            str(r["reached"]),
            f"{r['rate']:.1%}",
            f"{r['low']:.1%} to {r['high']:.1%}",
        ]
        for _, r in rates.iterrows()
        if r["teams"] > 0
    ]
    summary = benchmarks.summary(era, args.stage)
    head = (
        f"{stage.label}: how often past teams in each band of {measure} got there, "
        f"{view.span} ({summary.teams} of {summary.field} team-seasons over {summary.seasons} seasons). "
        "A frequency among past teams with its 95% interval - not any team's chance."
    )
    held = rates[rates["teams"] > 0]
    intervals = pd.DataFrame(
        {
            "band": held["band"].to_numpy(),
            "rate": held["rate"].to_numpy(),
            "low": held["low"].to_numpy(),
            "high": held["high"].to_numpy(),
            "text": [
                f"{r['reached']} of {r['teams']} ({r['rate']:.1%})" for _, r in held.iterrows()
            ],
        }
    )
    return Found(
        ResultStatus.OK,
        f"{stage.label}, by {measure}, {view.span}",
        head
        + "\n"
        + grid([measure, "Teams", "Got there", "Share", "95% interval"], rows, limit=20),
        rates,
        (lab_evidence(lab, "team_seasons"),),
        ("Benchmarks are history: frequencies among past teams, not a forecast.",),
        ("derived",),
        charts=(
            Chart(
                "intervals",
                f"{stage.label}: how often past teams got there, by {measure.lower()}",
                intervals,
                x="band",
                y="rate",
                text="text",
                low="low",
                high="high",
                y_title="Share of past teams that got there, with its 95% interval",
                tickformat=".0%",
                y_range=(0.0, 1.0),
            ),
        )
        if not intervals.empty
        else (),
    )


def metric_definition(lab: Lab, args: t.MetricDefinition) -> Found:
    # Compared folded, so that a key written as words or a name written as a key matches:
    # at A4 a model asked for "winning_percentage", which is "Winning percentage".
    wanted = _folded(args.metric)
    found = []
    for group, catalog in METRIC_CATALOGS.items():
        for spec in catalog:
            if wanted in (_folded(spec.key), _folded(spec.label), _folded(spec.name)):
                found.append((group, spec))
    if not found:
        for group, catalog in METRIC_CATALOGS.items():
            found += [
                (group, s)
                for s in catalog
                if wanted and (wanted in _folded(s.name) or wanted in _folded(s.key))
            ]
    title = f'Metric "{args.metric}"'
    if not found:
        return missing(title, f'The lab has no metric called "{args.metric}".')
    rows = [
        [
            s.name,
            s.key,
            group,
            s.description,
            KIND_OF.get(s.provenance, str(s.provenance.value)),
            {True: "higher", False: "lower", None: DASH}[s.higher_is_better],
        ]  # fmt: skip
        for group, s in found[:6]
    ]
    return Found(
        ResultStatus.OK,
        title,
        grid(["Metric", "Key", "Catalog", "Meaning", "Kind", "Better"], rows),
        pd.DataFrame(rows, columns=["name", "key", "catalog", "description", "kind", "better"]),
        (
            Evidence(
                EvidenceKind.LAB,
                "The lab's metric glossary (docs/METRICS.md)",
                location="docs/METRICS.md",
            ),
        ),
    )


def contract_info(lab: Lab, args: t.ContractInfo) -> Found:
    contracts = lab.contracts
    title = "Contracts"
    if not contracts.available:
        return Found(
            ResultStatus.UNAVAILABLE,
            title,
            "No contract file has been imported, so the lab has no salaries. They come from a "
            "file the user supplies (docs/CONTRACT_DATA.md).",
        )
    evidence = (contract_evidence(lab),)
    if args.view == "cap_rules":
        rules = contracts.cap_rules()
        return Found(
            ResultStatus.OK,
            "Cap rules by season",
            _plain_grid(rules, MAX_ROWS),
            rules,
            evidence,
            kinds=("measured",),
        )
    status = lab.status()
    season = args.season or status.default_payroll_season
    held = contracts.seasons()
    if season not in held:
        return missing(
            f"Contracts, {season}",
            f"The contract file lists salaries for {seasons_held(held)}; nothing for {season}.",
            evidence,
        )
    if args.view == "player":
        if args.player_id is None:
            return Found(ResultStatus.ERROR, title, "A player's contract needs player_id.")
        name = lab.players.profile(args.player_id).player["full_name"]
        rows = []
        for each in held:
            salaries = contracts.salaries(each)
            if args.player_id in salaries.index:
                s = salaries.loc[args.player_id]
                share = DASH if _missing(s["salary_cap_pct"]) else f"{s['salary_cap_pct']:.1%}"
                rows.append(
                    [
                        each,
                        f"${int(s['salary']):,}",
                        share,
                        s["option"] if isinstance(s["option"], str) else DASH,
                    ]
                )
        if not rows:
            return missing(
                f"{name}: contract", f"The contract file lists no salary for {name}.", evidence
            )
        return Found(
            ResultStatus.OK,
            f"{name}: salary by season",
            grid(["Season", "Salary", "Share of the cap", "Option"], rows),
            pd.DataFrame(rows, columns=["season", "salary", "cap_share", "option"]),
            evidence,
            kinds=("measured",),
        )
    payrolls = contracts.team_payrolls(season)
    if args.view == "team":
        if args.team_id is None or args.team_id not in payrolls.index:
            return missing(
                f"Payroll, {season}",
                "The contract file lists no salaries for this team that season.",
                evidence,
            )
        p = payrolls.loc[args.team_id]
        rows = [
            ["Team salary", f"${int(p['team_salary']):,}"],
            ["Active contracts", f"${int(p['active_salary']):,}"],
            ["Dead money", f"${int(p['dead_money']):,}"],
            ["Share of the cap", DASH if _missing(p["cap_share"]) else f"{p['cap_share']:.1%}"],
            [
                "Highest line exceeded",
                p["highest_line_exceeded"]
                if isinstance(p["highest_line_exceeded"], str)
                else "none",
            ],
        ]
        for line in ("salary_cap", "luxury_tax", "first_apron", "second_apron"):
            room = p.get(f"room_{line}")
            if _missing(room):
                continue
            named = line.replace("_", " ")
            if int(room) < 0:  # the service's room is negative above a line
                rows.append([f"Over the {named} by", f"${-int(room):,}"])
            else:
                rows.append([f"Room under the {named}", f"${int(room):,}"])
        return Found(
            ResultStatus.OK,
            f"{p['team_name']}: payroll, {season}",
            grid(["Item", "Amount"], rows, limit=len(rows)),
            payrolls.loc[[args.team_id]],
            evidence,
            kinds=("measured", "derived"),
        )
    rows = [
        [
            p["team_name"],
            f"${int(p['team_salary']):,}",
            p["highest_line_exceeded"] if isinstance(p["highest_line_exceeded"], str) else "none",
        ]
        for _, p in payrolls.iterrows()
    ]
    return Found(
        ResultStatus.OK,
        f"Team payrolls, {season}, largest first",
        grid(["Team", "Team salary", "Highest line exceeded"], rows, limit=30),
        payrolls,
        evidence,
        kinds=("measured", "derived"),
    )


def _plain_grid(frame: pd.DataFrame, limit: int) -> str:
    columns = list(frame.columns)[:8]
    return grid(
        columns,
        ([shown(None, c, row[c]) for c in columns] for _, row in frame.iterrows()),
        limit=limit,
    )


HANDLERS: dict[str, Handler] = {
    "resolve_entities": resolve_entities,
    "data_status": data_status,
    "player_stats": player_stats,
    "compare_players": compare_players,
    "team_stats": team_stats,
    "league_context": league_context,
    "historical_benchmarks": historical_benchmarks,
    "metric_definition": metric_definition,
    "contract_info": contract_info,
}
