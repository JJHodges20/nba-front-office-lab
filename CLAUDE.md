# NBA Front Office Lab - working notes for Claude Code

Read `docs/ROADMAP.md` for milestone status and `docs/ARCHITECTURE.md` for the layer
rules before changing anything. The source plan is
`docs/roadmap/NBA_Front_Office_Lab_Roadmap.pdf`.

## Commands (Windows)

```powershell
.\.venv\Scripts\python.exe -m pytest -n auto      # all tests except live-network ones, in parallel (~30 s)
.\.venv\Scripts\python.exe -m pytest tests\unit\domain   # one area, serially
.\.venv\Scripts\python.exe -m pytest -m network   # live-network tests only
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format .
.\.venv\Scripts\fol.exe --help
.\.venv\Scripts\fol.exe dictionary --write        # regenerate docs/DATA_DICTIONARY.md
.\.venv\Scripts\fol.exe metrics --write           # regenerate docs/METRICS.md
.\.venv\Scripts\fol.exe ingest                    # fetch from stats.nba.com (skips what is stored)
.\.venv\Scripts\fol.exe check                     # normalise the raw store + run quality checks
.\.venv\Scripts\fol.exe build                     # rebuild data\front_office.sqlite from the raw store
.\.venv\Scripts\fol.exe db                        # row counts and the last build's result
.\.venv\Scripts\python.exe scripts\make_fixtures.py   # rebuild tests/fixtures/raw from data/raw
```

## Work in milestones

Build one roadmap milestone at a time. A milestone is finished only when:

1. targeted automated tests pass,
2. relevant data-quality checks pass,
3. the UI workflow has been looked at if the milestone touches the interface,
4. no unrelated architectural boundary was weakened,
5. the change is documented (`docs/DEVELOPMENT_LOG.md`, milestone table in
   `docs/ROADMAP.md`) and committed.

## Rules that are easy to break

- **Layers.** Each package under `src/front_office/` is a layer with an allowed-import
  list (`docs/ARCHITECTURE.md`, enforced by `tests/architecture/`). The UI imports only
  `services` and `domain`. Lower layers take plain arguments; only `pipelines`,
  `services` and `interfaces` load settings.
- **No cap figures in Python.** Season-specific money lives in `configs/seasons/`. A test
  fails on any dollar-sized literal in source code.
- **Verify cap figures.** Every figure in `configs/seasons/` cites a source and a
  retrieval date. Never add or change one from memory.
- **Data contracts.** Every stored table has a `TableContract` in `domain/tables/`.
  Normalisers end with `conform_frame`. After changing a contract run
  `fol dictionary --write`.
- **Analytics own formulas.** A metric is computed in exactly one place, in `analytics`.
  The UI and later stages call it; they never re-derive it. Every metric has a
  `MetricSpec` in a catalog; after changing one run `fol metrics --write`.
- **Published versus estimated.** A season's team ratings and pace are the league's.
  Over a span of games they are estimates from box scores, and the service says which
  (`TeamTable.estimated`). Show them as estimates (`docs/decisions/0007-team-metrics.md`).
- **Measured vs modeled vs assumed.** Tag every column's provenance, and keep the three
  visibly apart on screen.
- **No predictive claims early.** Nothing may present a championship probability or
  "contender" verdict before the benchmark and modeling milestones are done and
  validated out of sample.
- **Source quirks get a rule, a note and a test.** Never repair data silently inside a
  normaliser (`docs/decisions/0003-source-quirks.md`).
- **Rebuilt versus kept tables.** Every build drops and rewrites the league tables. The
  user's rosters and the fetch/build history are kept and must never be put in the
  rebuilt group (`domain/tables/__init__.py`, `docs/decisions/0005-database.md`).
- **Only `storage` touches SQL.** Other layers call `Warehouse`, `RosterRepository` or
  `OperationsLog`. Always open a `Database` in a `with` block: on Windows an open
  connection keeps the file locked.
- **Never print data through rich markup.** Use `_say` / `_tagged` in the CLI; text in
  square brackets is otherwise swallowed as a style tag.
- **Warnings are errors** in the test suite.

## Conventions

- Seasons: `2025-26` (`Season.parse`). Money: whole USD integers. Shares: fractions 0-1.
  Datetimes: UTC, naive. Missing text: null, never `""`.
- The league year rolls over on July 1; the season with playable stats is found from the
  data, not from the calendar.
- Tests never touch the real `data/` directory: use the `project` / `settings` fixtures.
- `tests/fixtures/raw` is a miniature raw store of real responses. The `raw`,
  `normalized` and `tables` fixtures read it; `tables` is a private copy a test may break.
- stats.nba.com adds and drops response columns between seasons: select by name, list
  what you need in `required=`, never index by position.
- When patching files from a shell heredoc, backslashes get mangled. Use the editor
  tools for anything containing Windows paths.
