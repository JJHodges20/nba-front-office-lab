# NBA Front Office Lab - working notes for Claude Code

Read `docs/ROADMAP.md` for milestone status and `docs/ARCHITECTURE.md` for the layer
rules before changing anything. The source plan is
`docs/roadmap/NBA_Front_Office_Lab_Roadmap.pdf`.

## Commands (Windows)

```powershell
.\.venv\Scripts\python.exe -m pytest              # all tests except live-network ones
.\.venv\Scripts\python.exe -m pytest -m network   # live-network tests only
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format .
.\.venv\Scripts\fol.exe --help
.\.venv\Scripts\fol.exe dictionary --write        # regenerate docs/DATA_DICTIONARY.md
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
  The UI and later stages call it; they never re-derive it.
- **Measured vs modeled vs assumed.** Tag every column's provenance, and keep the three
  visibly apart on screen.
- **No predictive claims early.** Nothing may present a championship probability or
  "contender" verdict before the benchmark and modeling milestones are done and
  validated out of sample.
- **Warnings are errors** in the test suite.

## Conventions

- Seasons: `2025-26` (`Season.parse`). Money: whole USD integers. Shares: fractions 0-1.
  Datetimes: UTC, naive. Missing text: null, never `""`.
- The league year rolls over on July 1; the season with playable stats is found from the
  data, not from the calendar.
- Tests never touch the real `data/` directory: use the `project` / `settings` fixtures.
