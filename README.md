# NBA Front Office Lab

A front-office research workbench for a practical question: how can a team assemble a
highly competitive roster - potentially a championship-level one - on a constrained
payroll?

The lab combines player and team statistics, contracts, salary-cap rules, historical
team outcomes and roster fit, and is built in stages so that trustworthy analytics come
before roster scoring, optimisation or any predictive claim. The plan is in
[docs/ROADMAP.md](docs/ROADMAP.md).

## Status

Milestone 1 of 14 (repository and architecture) is complete. See the milestone table in
the roadmap for what exists and what does not.

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
.\.venv\Scripts\fol.exe dictionary  # the data dictionary, generated from the table contracts
```

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
- [Data source register](docs/DATA_SOURCE_REGISTER.md)
- [Development log](docs/DEVELOPMENT_LOG.md)

## A note on estimates

Value scores, optimiser outputs and postseason probabilities, when they arrive in later
versions, are analytical estimates. They are validated against historical and
out-of-sample results and are never presented as guarantees.
