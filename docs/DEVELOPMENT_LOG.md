# Development Log

One entry per milestone: what was built, what was decided, and the evidence for the
completion gate. Newest first.

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
