# NBA Front Office Lab - working notes for Claude Code

Read `docs/ROADMAP.md` for milestone status and `docs/ARCHITECTURE.md` for the layer
rules before changing anything. The source plan is
`docs/roadmap/NBA_Front_Office_Lab_Roadmap.pdf`.

## Commands (Windows)

```powershell
.\.venv\Scripts\python.exe -m pytest -n auto      # all tests except live-network ones, in parallel (~3 min)
.\.venv\Scripts\python.exe -m pytest tests\unit -n auto  # everything but the workbench pages (~40 s)
.\.venv\Scripts\python.exe -m pytest tests\unit\domain   # one area, serially
.\.venv\Scripts\python.exe -m pytest -m network   # live-network tests only
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format .
.\.venv\Scripts\fol.exe --help
.\.venv\Scripts\fol.exe dictionary --write        # regenerate docs/DATA_DICTIONARY.md
.\.venv\Scripts\fol.exe metrics --write           # regenerate docs/METRICS.md
.\.venv\Scripts\fol.exe benchmarks --write        # regenerate docs/research/BENCHMARKS.md from the database
.\.venv\Scripts\fol.exe ingest                    # fetch from stats.nba.com (skips what is stored)
.\.venv\Scripts\fol.exe check                     # normalise the raw store + run quality checks
.\.venv\Scripts\fol.exe build                     # rebuild data\front_office.sqlite from the raw store
.\.venv\Scripts\fol.exe db                        # row counts and the last build's result
.\.venv\Scripts\fol.exe value show                # the fitted player value model and its evidence
.\.venv\Scripts\fol.exe value fit --write         # fit it again on the built database (then: fol build)
.\.venv\Scripts\fol.exe value report --write      # regenerate docs/research/PLAYER_VALUE.md
.\.venv\Scripts\fol.exe fit test --write          # gather the roster fit evidence again (configs/models/roster_fit.json)
.\.venv\Scripts\fol.exe fit show                  # the roster fit evidence on file
.\.venv\Scripts\fol.exe fit report --write        # regenerate docs/research/ROSTER_FIT.md
.\.venv\Scripts\fol.exe playoffs show             # the fitted postseason model and how it did out of sample
.\.venv\Scripts\fol.exe playoffs fit --write      # fit it again on the built database (configs/models/postseason.json)
.\.venv\Scripts\fol.exe playoffs report --write   # regenerate docs/research/POSTSEASON.md
.\.venv\Scripts\fol.exe ui --no-browser           # the workbench at http://localhost:8501 (Ctrl+C stops it)
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
  "contender" verdict before the modeling milestone is done and validated out of
  sample. Benchmarks are history: a frequency among past teams, with its count and its
  interval, never a current team's chance (`docs/decisions/0009-benchmarks.md`).
- **No thresholds.** Report how often, for how many, with what uncertainty. A band is a
  way of grouping; nothing "needs" a figure. Compare teams within their own season.
- **Generated documents are not edited.** `docs/DATA_DICTIONARY.md`, `docs/METRICS.md`,
  `docs/research/BENCHMARKS.md`, `docs/research/PLAYER_VALUE.md`,
  `docs/research/ROSTER_FIT.md` and `docs/research/POSTSEASON.md` come from
  `fol dictionary|metrics|benchmarks --write`, `fol value report --write`,
  `fol fit report --write` and `fol playoffs report --write`. The first two are checked by
  tests; the research documents depend on the database, so regenerate them at a milestone
  gate after the data, a model, the evidence or the research code changes.
- **A model is fitted on request and applied by every build.** `fol value fit --write`
  writes `configs/models/player_value.json`; `fol build` applies it and never fits. Do
  not edit that file, and do not fit inside a build, a service or a page. Changing
  `configs/models/player_value.yaml`, a feature or a term changes nothing until the
  model is fitted again - and a test fails until it is
  (`docs/decisions/0010-player-value.md`).
- **A model earns its place out of sample.** Anything added to the value model is run
  through the expanding-window test against the model without it, and stays only if
  the difference is clear of zero. Record what was tried and left out in the decision.
- **Modeled values are estimates on screen too**: impact, projections and wins carry
  the modeled tag, and a weight is shown with its interval or not at all.
- **Fit is description unless the evidence says otherwise.** The fit measures are defined
  once in `domain/fit.py`; the table, the catalog and the computation read off that list.
  `fol fit test --write` gathers `configs/models/roster_fit.json`, the test of whether the
  measures explain what the value model's predictions missed; a correction is added to a
  roster's sum of parts only when `combined.is_usable`, and on the evidence the lab ships
  it is not. No page, and no later optimiser, may score fit with chosen weights; role
  counts may constrain a roster, never rate it (`docs/decisions/0012-roster-fit.md`).
- **The optimizer maximises the sum of the parts and nothing else.** A roster's
  projected rating is five slots of replacement level plus each player's projected impact
  above it for the projected share of minutes; fit is a requirement the user sets (role
  and group counts), never a term, and contract value is what the budget buys. Two budgets
  bind: the payroll line and a season's minutes. It returns several distinct rosters, each
  cut off before the next search, and names why nothing was found. It needs salaries from
  the user's contract file; tests and the demo use invented ones
  (`docs/decisions/0013-roster-optimizer.md`). SciPy's `milp` (HiGHS) is the solver.
- **A postseason chance is read off a file, with its interval, never fitted on a page.**
  `fol playoffs fit --write` writes `configs/models/postseason.json` (a game model carried
  through the series format and the bracket, and a season model of conditional steps);
  no build applies it, and `services/postseason.py` computes every chance on request from
  the file's parameters and kept draws. The stages are the one list in `domain/stages.py`.
  The model's inputs are the regular season's net rating and top-player quality because
  those are what the lab can say about a roster before a season; winning percentage
  out-predicts net rating on seasons already played and is left out on purpose, and the
  decision says why. Any change to the model or its inputs goes through the expanding-window
  test and is recorded (`docs/decisions/0014-postseason-model.md`). A chance is shown with
  its 95% interval and beside what happened where the season is decided; the page's "The
  model" tab is the evidence, and nothing calls a chance a verdict.
- **Archetypes are rules, not findings.** They live in `configs/archetypes.yaml`; a
  player's score for a role is the weakest of their percentiles on its measures, among
  the group the role is open to, within the season. To change one: edit the file, raise
  `version`, `fol build`. Nothing about a role is fitted; what is measured is how often
  it carries over to the next season, and that is shown beside every role. The
  defensive roles need the fitted value model (`docs/decisions/0011-archetypes.md`).
- **Source quirks get a rule, a note and a test.** Never repair data silently inside a
  normaliser (`docs/decisions/0003-source-quirks.md`).
- **Rebuilt versus kept tables.** Every build drops and rewrites the league tables and
  the modeled tables computed from them. The user's rosters and the fetch/build history
  are kept and must never be put in the rebuilt group (`domain/tables/__init__.py`,
  `docs/decisions/0005-database.md`).
- **Only `storage` touches SQL.** Other layers call `Warehouse`, `RosterRepository` or
  `OperationsLog`. Always open a `Database` in a `with` block: on Windows an open
  connection keeps the file locked.
- **Never print data through rich markup.** Use `_say` / `_tagged` in the CLI; text in
  square brackets is otherwise swallowed as a style tag.
- **Warnings are errors** in the test suite.

## The workbench (`apps/workbench`)

Read `docs/decisions/0008-workbench.md` first. `docs/WORKBENCH.md` is the user's guide.

- **The UI computes nothing.** A page sorts, filters, formats and draws. If it needs a
  number - a rank, a total, a change, a correlation - give a service a method that
  returns it. Deciding which rows are worth drawing is a service's job too.
- **Charts go through `wb/charts.py`**, and onto a page through `components.chart`, which
  adds the table view and the exports. The house rules (one scale, thin marks, ink text,
  series caps) are tested in `tests/ui/test_charts.py`; do not work around them in a page.
- **Colours live in `wb/theme.py`.** `.streamlit/config.toml` repeats them and a test
  keeps the two in step. A new colour has to pass `tests/ui/test_theme.py`.
- **Every figure says what it is**: measured, derived, estimate, modeled or the user's
  assumption. Estimates over a span carry "≈". Missing is a dash and an explanation,
  never a zero. A page that shows a modeled value lists the Modeled tag in its header.
- **Cache on the build id.** Accessors in `wb/data.py` take `build` first. Rosters are
  never cached.
- **Text is gender-neutral**: "they", "the player", never "he".
- **A clickable table takes its key from `state.table_key`** and calls `state.choose`
  for whatever row is picked, with no further condition. A fixed key leaves the row
  selected, and it then overrules every later choice in the sidebar.
- **Never assign to a widget's session key after the widget is drawn.** Park the value
  and apply it at the top of the next run (`state.choose`, `builder.CREATED`).
- **Headline tiles cut off long text.** Keep a figure's context to about twenty
  characters, or give the row fewer tiles (`components.figures(..., per_row=3)`).
- **Page tests** (`tests/ui/test_pages.py`) draw a page with `AppTest` and compare what
  it shows with what the service returns. `tests/ui/test_sweep.py` tries every control
  on every page; a new page must be added to its `STARTS`. `AppTest` cannot click a
  table row or edit a table cell: see `tests/ui/test_clicks.py` and `TestRosterEdits`.
- **Look at it, and click through it.** A running server keeps old modules loaded:
  restart `fol ui` after a code change, then check the page in the light and the dark
  theme and use every control you touched. Passing tests say nothing about clipped
  labels, collisions, or a click that does the wrong thing.

## Conventions

- Seasons: `2025-26` (`Season.parse`). Money: whole USD integers. Shares: fractions 0-1.
  Datetimes: UTC, naive. Missing text: null, never `""`.
- The league year rolls over on July 1; the season with playable stats is found from the
  data, not from the calendar.
- Tests never touch the real `data/` directory: use the `project` / `settings` fixtures.
- `tests/fixtures/raw` is a miniature raw store of real responses. The `raw`,
  `normalized` and `tables` fixtures read it; `tables` is a private copy a test may break.
- The fixture store holds one season of players for two teams, so nothing can be fitted
  on it. `tests/league.py` invents a league of many seasons whose team ratings a test
  plants; `tests/value_reference.py` computes the value model on it with plain loops, as
  an independent answer; `tests/synthetic_lab.py` loads it into a database. Its usage and
  assist figures are spread out so that every archetype has someone to fill it.
- stats.nba.com adds and drops response columns between seasons: select by name, list
  what you need in `required=`, never index by position.
- When patching files from a shell heredoc, backslashes get mangled. Use the editor
  tools for anything containing Windows paths.
- pytest fixtures are module-level functions. A fixture written as a method of a test
  class with a scope wider than `function` is an error in this pytest version.
