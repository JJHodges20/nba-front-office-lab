# Development Log

One entry per milestone: what was built, what was decided, and the evidence for the
completion gate. Newest first.

## Milestone 5 - Player analytics (2026-10-01)

**Built**

- `analytics/formulas.py`: every basketball formula, once. Shooting percentages,
  effective field goal and true shooting percentage, turnover percentage, per-game,
  per-36 and per-100 rates, ratings, pace, estimated possessions.
- `analytics/players.py`: a catalogue of 45 player metrics in the roadmap's six groups
  (availability, scoring, creation, rebounding, defense, impact); season metrics; metrics
  over any span of games; rolling metrics; recent availability; on/off combined across
  teams for traded players.
- `analytics/comparison.py`: qualification thresholds, percentiles oriented so higher is
  better, ranks, side-by-side comparison, pooled group averages, position groups.
- `analytics/finance.py`: cap share and a payroll's position against each threshold.
- `domain/metrics.py`: `MetricSpec`, which carries each metric's label, description,
  format, provenance and better direction.
- `services/`: `Lab` (opens the data, reports what it holds) and `PlayerService` (season
  table, profile, game log, rolling metrics, availability, comparison).

**Decisions** ([0006](decisions/0006-metrics.md))

- Derived metrics are computed by the lab; league-measured ones are passed through and
  labelled as such, never approximated.
- A rate with no denominator is missing, not zero.
- Percentiles are computed within a qualified group and always read "higher is better".

**Verification**

- The lab's effective field goal and true shooting percentages equal the league's
  published values to three decimals, and its offensive rating to one decimal, for every
  team in three seasons and every shooter in the fixture data. On the full store the
  same holds for 477 players.
- That comparison also showed where the league's definitions differ from the textbook
  ones (team rebound percentage, player turnover rate); each is recorded in the
  decision record and in the metric's description.
- On the real database: the 2025-26 player table (582 players, 45 metrics, percentiles)
  is produced in 0.3 s; a last-ten-games table in 0.7 s; a player profile in 0.2 s.

**Gate**

| Check | Result |
| --- | --- |
| Automated tests | 946 passed, 1 skipped (UI boundary test) |
| Test sensitivity | 30 planted bugs in formulas, metrics, comparison, finance and the service: 27 caught at first; the three misses were real gaps in the service tests, now closed (30 of 30) |
| Data-quality checks | Unchanged: 0 errors, 2 standing warnings |
| UI review | Not applicable |
| Architectural boundaries | `tests/architecture` passes; analytics imports only domain |
| Lint | `ruff check` and `ruff format --check` clean |

**Open items carried forward**

- Defensive indicators are limited to steals, blocks, fouls and on-court defensive
  rating. Tracking-based measures (contested shots, rim defence) need more datasets and
  belong with the value engine.

## Milestone 4 - Database and repositories (2026-10-01)

**Built**

- `storage/schema.py`: SQL tables generated from the data contracts, with a fingerprint
  of their shape.
- `storage/database.py`: the SQLite database, with transactional DDL, write-ahead
  logging and foreign keys on.
- `storage/warehouse.py`: `Warehouse.replace` rewrites every rebuilt table inside one
  transaction; `Warehouse.read` returns contract-conforming frames with simple filters.
- `storage/rosters.py`: `RosterRepository` for the user's rosters.
- `storage/operations.py`: `OperationsLog` for the history of fetches and builds.
- Contracts for seven new tables: `custom_rosters`, `roster_players`, `fetch_log`,
  `builds`, `build_issues`, `check_results`, `raw_snapshots`.
- `pipelines/build.py`: normalise, check and load in one step; record the build.
- Commands: `fol build`, `fol refresh` (ingest then build), `fol db`. `fol ingest` now
  records every fetch that reached the source.

**Decisions** ([0005](decisions/0005-database.md))

- One SQLite file through SQLAlchemy Core; tables generated from contracts.
- League tables and the last build's report are rebuilt together in one transaction;
  the user's rosters and the fetch and build history are kept across builds.
- A build with problems still loads and records them; a build that would empty a
  populated table is refused unless forced.
- Foreign keys are enforced only between kept tables.

**Something learned the useful way.** A probe before writing any storage code showed
that, with SQLAlchemy's defaults, a `DROP TABLE` inside a rolled-back transaction stays
dropped on SQLite. Had the rebuild been written on the assumption that transactions
cover DDL, a failed build would have destroyed the previous one. The database layer now
controls transactions explicitly and a test proves a failed rebuild restores the old
tables.

**Verification**

- `fol build` on the real store: 174,492 rows in about twenty seconds, 32 MB.
- Read back from the database, every league table equals what was written, column for
  column, with the same types.
- Reads: one season of team rows in 0.05 s; one season of player game logs (26,651
  rows) in 0.4 s; every team game since 1996 (76,046 rows) in 1.1 s.
- A reader with an open transaction sees the previous build until the new one commits.
- Rosters survive rebuilds.

**Gate**

| Check | Result |
| --- | --- |
| Automated tests | 745 passed, 1 skipped (UI boundary test) |
| Test sensitivity | 20 planted bugs in storage and the build: 18 caught; both survivors were equivalent (a redundant branch, since removed; one half of a two-part recipe, now asserted directly) |
| Data-quality checks | `fol build` on the real store: 0 errors, 2 standing warnings |
| UI review | Not applicable |
| Architectural boundaries | `tests/architecture` passes; `sqlalchemy` appears only in `storage` |
| Lint | `ruff check` and `ruff format --check` clean |

**Open items carried forward**

- Kept tables have no migration mechanism yet; one is needed before their shape changes.
- Every build reloads everything. Fine at twenty seconds; revisit if it grows.

## Milestone 3 - Contracts and salary-cap data (2026-10-01)

**Built**

- `providers/contract_file.py`: reads a contract file the user supplies and returns its
  text unchanged as a snapshot, with the user's statement of where the figures came from
  and when they were current.
- `processing/contracts.py`: parses the wide and long layouts, reads dollar amounts and
  option/guarantee markers, matches rows to known players and teams, and builds
  `contracts` and `contract_years` with each salary's share of its season's cap.
- `salary_cap_rules`, `contracts` and `contract_years` are now part of every build.
- `pipelines/contracts.py`: `fol contracts import` validates a file before storing it;
  `fol contracts template` writes a file listing every rostered player.
- Ten more quality checks: five foreign keys and five contract checks.
- `docs/CONTRACT_DATA.md`: the file format.

**The permissions check, and what it changed**

The roadmap requires checking automated-use permissions before building a contract
scraper. The check found that Basketball Reference's terms prohibit this project's use
of its data, that Spotrac refuses automated requests, and that the one API offering
contracts charges for them. No scraper was built. Contract data enters through a file
the user supplies ([0004](decisions/0004-contract-data-from-user-files.md)).

**Consequence for version 1.0.** The acceptance criterion "player contracts ... are
available in the workspace" is met by the import path, not by shipped data. Until a
contract file is imported the contract tables are empty and the build says so.

**Defects found by tests in this milestone**

- *Raw store ordering.* Snapshot file names were written to the second, so two imports
  within one second could sort in hash order and the older be taken as the newest. Names
  now carry microseconds and versions are ordered by fetch time. Names written to the
  second are still read.
- *Data read as markup.* The command line passed data through rich's markup, which
  swallowed a scope printed as `[all seasons]`. Data is now printed as plain text.
- *An unpaired game crashed its own check.* `games_are_paired` failed with a type error
  on exactly the input it exists to report. (Found and fixed in milestone 2's tests.)

**Decisions**

- A file-level problem rejects the whole contract file; a row that cannot be matched to
  a player is left out and reported. The first means the file is not what the user
  thinks it is; the second is an ordinary spelling difference.
- A contract file is validated before it is stored, so a bad file never becomes the
  newest snapshot and cannot break the next build.
- Cap share is null for seasons with no configured cap. It is never extrapolated.

**Verification**

- `fol contracts template` on the real store lists 622 rostered players.
- `fol check` on the real store: 44 checks, 42 passed, 0 errors, the same 2 standing
  warnings, and a note that no contract file has been imported.
- Contract logic is tested with an invented cast and invented salaries only. No real
  salary figure appears anywhere in the repository.

**Gate**

| Check | Result |
| --- | --- |
| Automated tests | 636 passed, 1 skipped (UI boundary test) |
| Test sensitivity | 15 planted bugs in the contract import, checks and raw store: 14 caught; the survivor was a redundant filter, since removed |
| Data-quality checks | `fol check` on the real store: 0 errors, 2 standing warnings |
| UI review | Not applicable |
| Architectural boundaries | `tests/architecture` passes; no rule changed |
| Lint | `ruff check` and `ruff format --check` clean |

**Open items carried forward**

- A contract file has to be supplied before salaries, payroll and cap share can be used.
- Cap rules exist for 2024-25 to 2026-27 only; later contract seasons have no cap share.

## Milestone 2 - NBA data ingestion (2026-10-01)

**Built**

- `providers/nba_stats.py`: a stats.nba.com adapter over `nba_api` covering thirteen
  datasets. It spaces requests out, retries transient failures with a growing pause, and
  returns each response unchanged.
- `rawstore/`: an append-only store of gzip snapshots, one file per response, each with
  its provenance and a content hash. A fetch that returns what is already stored writes
  nothing.
- `pipelines/ingest.py`: what to fetch and whether it is due. A finished season is
  fetched once; a season in progress is refetched after twelve hours; a failed request
  costs one dataset, not the run.
- `processing/nba_stats/`: normalisers for nine tables - `teams`, `team_seasons`,
  `team_games`, `playoff_results`, `players`, `player_seasons`, `player_game_logs`,
  `team_rosters`, `player_on_off` - each ending in its data contract.
- `quality/checks.py`: 34 checks - one per declared foreign key plus 17 cross-table
  checks.
- `pipelines/normalize.py` and `pipelines/check.py`: rebuild every table from the raw
  store and run the checks, recording anything that could not be built.
- Commands: `fol ingest`, `fol raw`, `fol check`.
- `scripts/make_fixtures.py`: cuts a 428 KB fixture raw store from real responses.

**What the real data taught us**

Each of these was found by running the normalisers over thirty seasons, and each is now
handled explicitly and covered by a test ([0003](decisions/0003-source-quirks.md)).

- *A game that was never played.* Boston-Indiana, 16 April 2013, was cancelled; the
  source still lists it, with no result and no minutes. It is left out and noted.
- *Fractional season totals.* Sacramento's 1996-97 opponent totals are published as
  1253.8, 1255.4 and 426.8. They are rounded and noted. A column that is mostly
  fractional is rejected instead, since that would mean averages, not totals.
- *Neutral-site games.* From 2024-25 the source lists both teams as visitors for
  international games and the in-season tournament's final rounds. `team_games` gained
  an `is_neutral_site` column; `is_home` is false for both teams in those games.
- *Rostered players who never played* appear in on/off data with no on-court line, and
  are absent from the player index. They are left out of `player_on_off`.
- *Old playoff game ids are sequential* and the league's own series ids are unreliable
  before 2001-02, so series are reconstructed from the games themselves.
- *Response columns change between seasons* (2026-27 rosters gained a column), so every
  normaliser selects columns by name and names any it cannot find.
- *Season totals and summed game logs differ slightly* (never by more than 1.2%) because
  the league corrects them separately. The published totals are stored; the difference
  is watched by a check.

**Decisions**

- The league's published season totals and ratings are canonical. Game logs are a
  second, independent measurement used to cross-check them.
- Postseason outcomes on `team_seasons` stay null until the Finals are decided, so a
  "did not reach the conference finals" can never be recorded and later become wrong.
- A build problem is recorded as an issue and the rest of the build continues; `fol
  check` exits non-zero when anything is missing or contradictory.

**Verification**

- Full ingest: 438 requests, 438 stored, none failed. 31 seasons of team data
  (1996-97 to 2026-27), player detail for 2023-24 to 2026-27. Raw store: 8.2 MB.
- Normalised: 892 team-seasons, 76,046 team-game rows, 450 playoff series, 5,242
  players, 2,386 player-seasons, 84,768 player-game rows, 2,218 roster rows, 1,972
  on/off rows. Zero build errors; two notes (the two quirks above).
- Playoffs: every season has exactly 15 series in an 8/4/2/1 bracket. The derived Finals
  result matches the record for every season from 1996-97 to 2024-25. The derived round
  agrees with the round encoded in the league's game ids in all 2,085 playoff games
  since 2001-02. Best-of-five first rounds appear in exactly the six seasons that had
  them.
- Consistency: every team's wins, losses and games equal its game results; league-wide
  wins equal losses and points scored equal points allowed in every season; every
  player's games and points equal his game log; in all 7,882 team-games with player
  logs, the players' points sum to the team's score.

**Gate**

| Check | Result |
| --- | --- |
| Automated tests | 492 passed, 1 skipped (UI boundary test), plus 1 live-network test passed |
| Test sensitivity | 28 planted bugs across normalisers, checks, ingest policy, raw store and provider: 28 caught |
| Data-quality checks | `fol check` on the real store: 34 checks, 32 passed, 0 errors, 2 warnings |
| UI review | Not applicable |
| Architectural boundaries | `tests/architecture` passes; no rule changed |
| Lint | `ruff check` and `ruff format --check` clean |

The two standing warnings are source glitches from 1996-97, kept visible on purpose: one
game whose published points do not follow from its shot totals, and the Sacramento
team-season whose published offensive rating disagrees with its own points and
possessions.

**Open items carried forward**

- Player contract source: permissions check due in milestone 3.
- Birth dates are known only for players on an ingested roster (857 of 5,242).
- Lineup data is deferred to the roster-fit milestone.

## Milestone 1 - Repository and architecture (2026-10-01)

**Built**

- Package skeleton `src/front_office/` with one sub-package per architectural layer, each
  documenting its responsibility and allowed imports.
- Domain layer: `Season` identifiers, cap-rule models (`SeasonRules` and friends), and
  the data-contract framework (`TableContract`, `conform_frame`, `validate_frame`) with
  column-level provenance.
- Config layer: `configs/base.yaml` settings and one cap-rules file per season
  (2024-25, 2025-26, 2026-27).
- The first contract and normaliser, `salary_cap_rules`, as the worked example of the
  contract -> processing -> validated frame pattern.
- `fol` command line: `info`, `seasons`, `dictionary`.
- Generated data dictionary, architecture guide, source register, this log.

**Decisions**

- Layer boundaries are enforced by tests rather than convention
  ([0001](decisions/0001-layered-architecture.md)).
- Data contracts are the single definition of each table; storage and documentation are
  derived from them ([0002](decisions/0002-data-contracts.md)).
- Team history starts at 1996-97, the first season for which stats.nba.com publishes
  possessions and offensive/defensive ratings.
- "Current season" is never inferred from the calendar. On 2026-10-01 the league year is
  2026-27 (its cap is in force) but no 2026-27 games exist; the stats season is
  whichever season has data.

**Verification**

- Cap figures for all three seasons were checked against the league announcements on
  2026-10-01; sources are cited in each file. The 2026-27 cap, tax line and aprons match
  the roadmap's reference values exactly.
- Roster limits checked against the NBA's CBA 101 document.
- stats.nba.com was probed for the 1996-97, 2002-03, 2019-20, 2025-26 and 2026-27
  seasons to confirm what is available before designing the ingestion milestone.

**Gate**

| Check | Result |
| --- | --- |
| Automated tests | 165 passed, 1 skipped (the UI boundary test, no UI yet) |
| Data-quality checks | Cap-rule consistency tests pass (floor = 90% of cap; maximum salaries = 25/30/35% of cap) |
| UI review | Not applicable |
| Architectural boundaries | `tests/architecture` passes; boundaries introduced in this milestone |
| Lint | `ruff check` and `ruff format --check` clean |

**Open items carried forward**

- Player contract source: permissions check due in milestone 3.
