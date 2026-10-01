# NBA Front Office Lab

A front-office research workbench for a practical question: how can a team assemble a
highly competitive roster - potentially a championship-level one - on a constrained
payroll?

The lab combines player and team statistics, contracts, salary-cap rules, historical
team outcomes and roster fit, and is built in stages so that trustworthy analytics come
before roster scoring, optimisation or any predictive claim. The plan is in
[docs/ROADMAP.md](docs/ROADMAP.md).

## Status

Milestones 1-3 of 14 are complete: the architecture, ingestion of league data from
stats.nba.com into a validated set of tables, and import of contract data with
cap-normalised salaries. There is no database or user interface yet. See the milestone
table in the roadmap for what exists and what does not.

**Contract data is not included.** No free source permits collecting NBA contracts
automatically for this kind of project, so salaries come from a file you supply. See
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
.\.venv\Scripts\fol.exe info        # version, data locations, configured seasons
.\.venv\Scripts\fol.exe seasons     # cap, tax, apron and roster rules by season
.\.venv\Scripts\fol.exe ingest      # fetch league data from stats.nba.com into the raw store
.\.venv\Scripts\fol.exe raw         # what the raw store holds
.\.venv\Scripts\fol.exe check       # normalise the raw store and run the data-quality checks
.\.venv\Scripts\fol.exe contracts template            # a contract file to fill in
.\.venv\Scripts\fol.exe contracts import FILE --source "where the figures came from"
.\.venv\Scripts\fol.exe dictionary  # the data dictionary, generated from the table contracts
```

The first `fol ingest` makes about 440 requests and takes roughly ten minutes: team
data for every season since 1996-97, and player detail for the current league year and
the three seasons before it. Later runs fetch only what is new. `fol ingest --season
2025-26` fetches one season.

## Development

```powershell
.\.venv\Scripts\python.exe -m pytest          # tests (live-network tests are deselected)
.\.venv\Scripts\python.exe -m ruff check .    # lint
.\.venv\Scripts\python.exe -m ruff format .   # format
```

## Layout

```
configs/            base settings and one cap-rules file per season
data/               local data: raw snapshots, database, imports, exports (not committed)
docs/               roadmap, architecture, data dictionary, source register, dev log
scripts/            setup helpers
src/front_office/   the package, one sub-package per architectural layer
tests/              unit, architecture and integration tests
```

## Documentation

- [Roadmap and milestone status](docs/ROADMAP.md)
- [Architecture](docs/ARCHITECTURE.md) - the layers and the rules between them
- [Data dictionary](docs/DATA_DICTIONARY.md) - generated from the table contracts
- [Contract data](docs/CONTRACT_DATA.md) - how to supply salaries, and the file format
- [Data source register](docs/DATA_SOURCE_REGISTER.md)
- [Development log](docs/DEVELOPMENT_LOG.md)

## A note on estimates

Value scores, optimiser outputs and postseason probabilities, when they arrive in later
versions, are analytical estimates. They are validated against historical and
out-of-sample results and are never presented as guarantees.
