# NBA Front Office Lab

A front-office research workbench for a practical question: how can a team assemble a
highly competitive roster - potentially a championship-level one - on a constrained
payroll?

The lab combines player and team statistics, contracts, salary-cap rules, historical
team outcomes and roster fit, and is built in stages so that trustworthy analytics come
before roster scoring, optimisation or any predictive claim. The plan is in
[docs/ROADMAP.md](docs/ROADMAP.md).

![League Overview: every team's offense against its defense](docs/images/league-overview.png)

## Status

Milestones 1-8 of 14 are complete. The first seven are the roadmap's version 1.0,
*League and Roster Analytics*: league data from stats.nba.com, a database built from it,
tested player and team analytics, import of contract data with cap-normalised salaries,
and a workbench to explore all of it and to build rosters by hand. The eighth adds the
benchmark research of version 2: what the teams that reached each stage of the
postseason have looked like over thirty seasons, as historical frequencies with their
uncertainty rather than thresholds - on a page of the workbench and as a generated
document, [docs/research/BENCHMARKS.md](docs/research/BENCHMARKS.md).

Nothing yet scores players, judges fit, optimises a roster or predicts an outcome.
Those are the later stages, and the workbench describes; it does not recommend.

**Contract data is not included.** No free source permits collecting NBA contracts
automatically for this kind of project, so salaries come from a file you supply. Until
you import one, the salary, payroll and cap views are empty and say so. See
[docs/CONTRACT_DATA.md](docs/CONTRACT_DATA.md).

## Setup

Requires Python 3.11 or newer.

```powershell
.\scripts\bootstrap.ps1
```

or by hand:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

## Using it

```powershell
.\.venv\Scripts\fol.exe refresh     # fetch what is new from stats.nba.com, then rebuild the database
.\.venv\Scripts\fol.exe ui          # open the workbench in your browser
```

The first `fol refresh` makes about 440 requests and takes roughly ten minutes: team
data for every season since 1996-97, and player detail for the current league year and
the three seasons before it. Later runs fetch only what is new. Rebuilding the database
takes about twenty seconds and never touches rosters you have built.

### The workbench

`fol ui` serves the workbench on this machine only (http://localhost:8501) and opens it.
Stop it with Ctrl+C. [docs/WORKBENCH.md](docs/WORKBENCH.md) is the guide.

| Page | What it is for |
| --- | --- |
| League Overview | League averages and how they changed, standings, team efficiency, thirty seasons of trends, the playoff bracket and every champion. |
| Winning Benchmarks | How often past teams of each record, rating or seed reached each stage of the postseason, what the teams that got there looked like, and what separated them - for any era. |
| Player Explorer | Every player of a season; one player's profile, form, seasons, games and contract; up to three players side by side. |
| Team Explorer | One team: record, ratings and ranks, the four factors, form, games, rotation, history, payroll. |
| Contract Explorer | Salaries, team payrolls against the cap, tax and aprons, and the cap rules with their sources. |
| Analytics Lab | Any two metrics against each other, how one is spread, and the metric glossary. |
| Team Builder | Rosters you assemble by hand: payroll, cap share, room under each line, roster rules, pooled indicators. |
| Data Health | Freshness, failed fetches, missing data, quality checks and source status. |

Season, phase, team, player and comparison window are chosen once in the sidebar and
hold on every page. Each page says which of its numbers the league measured, which the
lab derived or estimated, and which you assumed.

![Player Explorer: a player's percentile profile and form](docs/images/player-explorer.png)

![Team Explorer: ratings with league ranks, the four factors and form](docs/images/team-explorer.png)

![Winning Benchmarks: how often teams of each record won the championship, with intervals](docs/images/winning-benchmarks.png)

### Other commands

```powershell
.\.venv\Scripts\fol.exe db          # what the database holds and how the last build went
.\.venv\Scripts\fol.exe info        # version, data locations, configured seasons
.\.venv\Scripts\fol.exe seasons     # cap, tax, apron and roster rules by season
.\.venv\Scripts\fol.exe ingest      # only fetch: league data into the raw store
.\.venv\Scripts\fol.exe build       # only rebuild: the database from the raw store
.\.venv\Scripts\fol.exe raw         # what the raw store holds
.\.venv\Scripts\fol.exe check       # validate the raw store without writing anything
.\.venv\Scripts\fol.exe contracts template            # a contract file to fill in
.\.venv\Scripts\fol.exe contracts import FILE --source "where the figures came from"
.\.venv\Scripts\fol.exe dictionary  # the data dictionary, generated from the table contracts
.\.venv\Scripts\fol.exe metrics     # the metric glossary, generated from the metric catalogs
.\.venv\Scripts\fol.exe benchmarks  # the benchmark research, generated from the database
.\.venv\Scripts\fol.exe ui --port 8600 --no-browser   # the workbench on another port
```

`fol ingest --season 2025-26` fetches one season.

## Development

```powershell
.\.venv\Scripts\python.exe -m pytest -n auto  # tests, in parallel (live-network tests are deselected)
.\.venv\Scripts\python.exe -m ruff check .    # lint
.\.venv\Scripts\python.exe -m ruff format .   # format
```

## Layout

```
apps/workbench/     the Streamlit workbench: pages, filters, charts
configs/            base settings and one cap-rules file per season
data/               local data: raw snapshots, database, imports, exports (not committed)
docs/               roadmap, architecture, guides, decisions, dev log
scripts/            setup helpers
src/front_office/   the package, one sub-package per architectural layer
tests/              unit, architecture, integration and interface tests
```

## Documentation

- [Roadmap and milestone status](docs/ROADMAP.md)
- [The workbench](docs/WORKBENCH.md) - how to read and use the pages
- [Benchmark research](docs/research/BENCHMARKS.md) - what contenders have looked like, generated from the database
- [Architecture](docs/ARCHITECTURE.md) - the layers and the rules between them
- [Data dictionary](docs/DATA_DICTIONARY.md) - generated from the table contracts
- [Metric glossary](docs/METRICS.md) - every player, team and roster metric, generated from the catalogs
- [Contract data](docs/CONTRACT_DATA.md) - how to supply salaries, and the file format
- [Data source register](docs/DATA_SOURCE_REGISTER.md)
- [Decisions](docs/decisions/) - why things are the way they are
- [Development log](docs/DEVELOPMENT_LOG.md)

## A note on estimates

Value scores, optimiser outputs and postseason probabilities, when they arrive in later
versions, are analytical estimates. They are validated against historical and
out-of-sample results and are never presented as guarantees.
