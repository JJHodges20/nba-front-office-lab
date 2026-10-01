# Architecture

NBA Front Office Lab is built in layers so that data ingestion, analytics, optimisation,
modeling and the user interface can each change without disturbing the others.

```
NBA + contract + cap data
  -> providers      retrieve, unchanged
  -> rawstore       keep an immutable snapshot
  -> processing     clean + normalise into contract-conforming frames
  -> storage        database + repositories
  -> analytics      every calculation
  -> services       read-side API
  -> apps/workbench Streamlit front office UI
```

Later roadmap stages (player value, roster fit, optimisation, prediction, simulation)
slot in between `analytics` and `services` as their own layers.

This document describes the intended structure. A layer's package and its import rule
exist from milestone 1; its code arrives with the milestone that builds it. See
`docs/ROADMAP.md` for what is implemented today.

## Layers and what each may import

All layers live in `src/front_office/`. A layer may import itself, the layers listed for
it, and nothing else in the project.

| Layer | Responsibility | May import |
| --- | --- | --- |
| `domain` | Shared vocabulary: seasons, cap-rule models, data contracts. Pure, no I/O. | nothing |
| `config` | Settings and season rules read from `configs/`. The only place YAML is parsed. | `domain` |
| `providers` | Adapters that retrieve data from external sources and return it unchanged. The only layer that touches the network. | `domain` |
| `rawstore` | Immutable, timestamped snapshots of what providers returned. | `domain` |
| `processing` | Pure functions that turn raw payloads into frames satisfying a data contract. | `domain` |
| `storage` | Database schema (built from the data contracts) and repositories. The only layer that writes SQL. | `domain` |
| `quality` | Data-quality checks. They report problems; they never repair data. | `domain` |
| `analytics` | Every formula. Pure functions over frames. | `domain` |
| `pipelines` | Orchestrates provider -> rawstore -> processing -> storage. | `domain`, `config`, `providers`, `rawstore`, `processing`, `storage`, `quality` |
| `services` | What the UI and CLI call: repositories + analytics, returned display-ready. | `domain`, `config`, `storage`, `analytics`, `quality` |
| `interfaces` | The `fol` command line. Thin. | `domain`, `config`, `pipelines`, `services` |
| `apps/` (UI) | Streamlit workbench. Displays what services return. | `domain`, `services` |

The lower layers (`providers` through `analytics`) take plain values as arguments rather
than reading configuration themselves. Only `pipelines`, `services` and `interfaces` load
settings, which keeps everything beneath them trivially testable.

Third-party libraries are confined the same way: `nba_api` and `requests` only in
`providers`; `sqlalchemy` only in `storage`; `yaml` only in `config`; `typer` and `rich`
only in `interfaces`; `streamlit` and `plotly` only in `apps/`.

These rules are enforced by `tests/architecture/test_layer_boundaries.py`. A forbidden
import fails the test suite. To change a rule, change this document and that test in the
same commit and record why in `docs/decisions/`.

## The roadmap's engineering rules, and how each is enforced

| Rule | Enforcement |
| --- | --- |
| Provider adapters retrieve data; processing modules clean and normalise it. | Separate layers; `processing` cannot import `providers`, and vice versa. |
| Raw source data stays immutable. | `rawstore` only ever adds snapshots; the database is rebuilt from them. |
| Analytics own calculations; the UI does not recalculate metrics. | `apps/` may import only `services` and `domain`. |
| Optimisation consumes tested analytics rather than duplicating formulas. | Later layers import `analytics`; formulas exist in one module each. |
| Predictive models are evaluated out of sample before influencing recommendations. | A gate for the modeling milestone; no predictive claim appears before then. |
| Season-specific cap and roster rules are configurable. | `configs/seasons/*.yaml`; a test fails if a cap-sized dollar literal appears in Python source. |
| Every major module has automated tests before the next milestone depends on it. | Milestone completion gate (see `docs/ROADMAP.md`). |

## Data contracts

A *data contract* (`front_office.domain.schema.TableContract`) declares one canonical
table: its columns, logical types, nullability, units, allowed values, primary key, and
the **provenance** of each column.

- `processing` must return frames that satisfy the contract (`conform_frame` raises
  otherwise).
- `storage` builds its tables from the same contracts.
- `docs/DATA_DICTIONARY.md` is generated from them (`fol dictionary --write`), and a
  test fails if the committed file is stale.

Validation is strict on purpose: text in a numeric column, a number in a text column, an
id that lost its leading zeros, a non-ISO date string, an empty string standing in for
"missing" - each is rejected rather than quietly repaired.

"Contract" on its own always means a data contract. Player salary agreements are the
`contracts` and `contract_years` tables.

### Provenance

Every column is tagged `identifier`, `measured`, `derived`, `modeled`, `assumption` or
`operational`. The roadmap requires a clear separation between measured statistics,
modeled estimates and user assumptions; carrying that tag on the column lets any screen
label a number correctly without knowing how it was produced.

## From source to table

```
fol ingest:  provider.fetch(dataset) -> Snapshot -> RawStore.save()
fol check:   RawStore -> normalize() -> tables + issues -> quality checks
```

- A **dataset** (`domain/datasets.py`) is one kind of provider response. A **snapshot**
  (`domain/snapshots.py`) is one response, unchanged, with its source, partition, fetch
  time and the request that produced it.
- The **raw store** files snapshots under
  `data/raw/<source>/<dataset>/<partition>/<fetched_at>_<hash>.json.gz`. Files are
  written once and never changed. Fetching what is already stored writes nothing.
- **Normalisation** (`pipelines/normalize.py`) is a pure replay of the raw store: the
  same snapshots always give the same tables, so anything built from them can be thrown
  away and rebuilt.
- A dataset that is missing, malformed or fails its contract becomes a **build issue**
  for that table and season and the build carries on. A normaliser that adjusts source
  data says so in a note. See `docs/decisions/0003-source-quirks.md`.
- **Quality checks** (`quality/checks.py`) then test the tables against each other.
  Contracts prove a table is well-formed; checks prove the tables agree.

## Season rules

Cap thresholds, salary exceptions, maximum salaries and roster limits live in
`configs/seasons/<season>.yaml`, one file per season, each citing where its figures were
verified. `front_office.domain.cap_rules.SeasonRules` validates them (thresholds must
ascend, a source is mandatory, unknown keys are rejected) and exposes a `version`
fingerprint that is stored with anything computed from the rules.

To add a season: copy the latest file, rename it, update the `season` field and every
figure, and cite the announcement. The loader refuses a file whose name and `season`
field disagree.

## Conventions

- Season labels use both years: `2025-26`. Parse with `Season.parse`.
- Money is whole US dollars, stored as integers.
- Shares and percentages are fractions (0-1) unless a column's unit says otherwise.
- Dates and times are UTC; datetimes are stored without a timezone marker.
- Missing text is null, never `""`.
- The league year (and the cap) rolls over on July 1; that says nothing about whether
  games have been played, so "the current stats season" is always determined from data.

## Testing

- `tests/unit/` - one directory per layer; pure, fast, no network.
- `tests/architecture/` - the boundary rules above.
- `tests/integration/` - several layers together against recorded fixtures.
- Tests marked `network` call live services and are deselected by default
  (`pytest -m network`).
- Warnings are errors (`filterwarnings = ["error"]`).

## How to add a table

1. Declare its `TableContract` in the matching module under `domain/tables/` and add it
   to that module's `TABLES`. Remove it from `PLANNED_TABLES`.
2. Write the normaliser in `processing/` and finish it with `conform_frame`.
3. Run `fol dictionary --write`.
4. Test the normaliser against a recorded fixture.

## How to add a stats.nba.com dataset

1. Add it to `NbaStatsDataset` and `_SPECS` in `domain/datasets.py`.
2. Map it to its endpoint in `providers/nba_stats.py`. A test confirms the parameters
   exist in the installed `nba_api`.
3. Request it in `pipelines/ingest.py` (`league_requests` or `team_requests`).
4. Normalise it in `processing/nba_stats/`, wire it into `pipelines/normalize.py`, and
   add any cross-table check to `quality/checks.py`.
5. Add it to `scripts/make_fixtures.py`, rebuild the fixtures, and test against them.
