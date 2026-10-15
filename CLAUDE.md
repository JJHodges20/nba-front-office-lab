# NBA Front Office Lab - working notes for Claude Code

Read `docs/ROADMAP.md` for milestone status and `docs/ARCHITECTURE.md` for the layer
rules before changing anything. The source plan is
`docs/roadmap/NBA_Front_Office_Lab_Roadmap.pdf`.

## Commands (Windows)

```powershell
.\.venv\Scripts\python.exe -m pytest -n auto      # all tests except live-network ones, in parallel (~5 min)
.\.venv\Scripts\python.exe -m pytest tests\unit -n auto  # everything but the workbench pages (~3 min)
.\.venv\Scripts\python.exe -m pytest tests\unit\domain   # one area, serially
.\.venv\Scripts\python.exe -m pytest -m network   # live-network tests only
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format .
.\.venv\Scripts\fol.exe --help
.\.venv\Scripts\fol.exe refresh                  # ingest what is new, then build
.\.venv\Scripts\fol.exe info                     # version, data locations, configured seasons
.\.venv\Scripts\fol.exe seasons                  # cap, tax, apron and roster rules by season
.\.venv\Scripts\fol.exe raw                      # what the raw store holds
.\.venv\Scripts\fol.exe contracts template       # a contract file to fill in (then import, then build)
.\.venv\Scripts\fol.exe contracts preview FILE --source "..." --as-of YYYY-MM-DD   # a file against the one in use; stores nothing
.\.venv\Scripts\python.exe scripts\convert_salary_dataset.py <player_salaries.csv> <out.csv>   # the MrBridge/HoopsHype salary table as a contract file
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
.\.venv\Scripts\fol.exe simulate show             # the simulator's measured parameters and the wins test
.\.venv\Scripts\fol.exe simulate fit --write      # measure them again on the built database (configs/models/simulator.json)
.\.venv\Scripts\fol.exe simulate report --write   # regenerate docs/research/SIMULATOR.md
.\.venv\Scripts\fol.exe ui --no-browser           # the workbench at http://localhost:8501 (Ctrl+C stops it)
.\.venv\Scripts\fol.exe api                       # the HTTP API at http://localhost:8000, every endpoint at /docs (Ctrl+C stops it)
.\.venv\Scripts\fol.exe rag index                 # embed the documents into data/rag for the API's answers (Ollama running)
.\.venv\Scripts\fol.exe rag status                # whether that index matches the documents
.\.venv\Scripts\python.exe -m pytest tests\assistant  # the assistant's evaluation cases, their figures recomputed
.\.venv\Scripts\python.exe -m pytest -m ollama    # the assistant against the local model (Ollama running)
.\.venv\Scripts\python.exe scripts\benchmark_ollama.py --write   # benchmark the candidate models (docs/research/ASSISTANT_MODELS.md)
.\.venv\Scripts\python.exe scripts\evaluate_answers.py --write   # the assistant's whole answers, end to end (docs/research/ASSISTANT_ANSWERS.md)
.\.venv\Scripts\python.exe scripts\evaluate_search.py --write    # web search and the news feeds on frozen queries, live (docs/research/SEARCH_QUALITY.md)
.\.venv\Scripts\python.exe scripts\evaluate_experiments.py --write   # experiment proposals drafted end to end on frozen questions (docs/research/EXPERIMENT_PROPOSALS.md)
.\.venv\Scripts\python.exe scripts\measure_session.py --write    # a working session timed, asked twice on a copy of the data (docs/research/ASSISTANT_SESSION.md)
.\.venv\Scripts\fol.exe current refresh            # fetch what is due: this season's games, transactions, the injury report, the news feeds
.\.venv\Scripts\fol.exe current status             # when each current source was last fetched, and what is held
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
  `services`, `interfaces` and the outer `assistant` and `server` load settings.
- **No cap figures in Python.** Season-specific money lives in `configs/seasons/`. A test
  fails on any dollar-sized literal in source code.
- **Verify cap figures.** Every figure in `configs/seasons/` cites a source and a
  retrieval date. Never add or change one from memory.
- **A contract file may be history.** The file in use (`docs/DATA_SOURCE_REGISTER.md`)
  lists every salary a team paid from 2015-16, split by team: a player who changed teams
  within a season appears under each team with what each owed. The import's duplicate
  rule and the quality check are per team, season and kind of contract;
  `ContractService.salaries` adds a player's shares up; a season's cap share is blank
  where `configs/seasons/` has no rules file (before 2024-25). A row the league's player
  index does not hold is reported and left out, never guessed; the converter's alias and
  id lists are the record of the spellings that differ
  (`docs/decisions/0017-contract-history.md`).
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
  `docs/research/ROSTER_FIT.md`, `docs/research/POSTSEASON.md`,
  `docs/research/SIMULATOR.md`, `docs/research/ASSISTANT_MODELS.md`,
  `docs/research/ASSISTANT_ANSWERS.md`, `docs/research/SEARCH_QUALITY.md`,
  `docs/research/EXPERIMENT_PROPOSALS.md` and `docs/research/ASSISTANT_SESSION.md` come from
  `fol dictionary|metrics|benchmarks --write`, `fol value report --write`,
  `fol fit report --write`, `fol playoffs report --write`, `fol simulate report --write`,
  `scripts/benchmark_ollama.py --write`, `scripts/evaluate_answers.py --write`,
  `scripts/evaluate_search.py --write`, `scripts/evaluate_experiments.py --write` and
  `scripts/measure_session.py --write`. The
  first two are checked by tests; the research
  documents depend on the database, so regenerate them at a milestone gate after the
  data, a model, the evidence or the research code changes.
- **A model is fitted on request and applied by every build.** `fol value fit --write`
  writes `configs/models/player_value.json`; `fol build` applies it and never fits. Do
  not edit that file, and do not fit inside a build, a service or a page. Changing
  `configs/models/player_value.yaml`, a feature or a term changes nothing until the
  model is fitted again - and a test fails until it is
  (`docs/decisions/0010-player-value.md`). The model is tested twice: with each season's
  minutes as played (3.01, the measure of the rating alone and the basis of every
  comparison with simpler methods) and with the minutes projected (3.63); a forecast -
  the optimizer, the simulator, a chance read for a roster - carries the second figure
  (`docs/decisions/0016-audit.md`).
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
  (`docs/decisions/0013-roster-optimizer.md`). SciPy's `milp` (HiGHS) is the solver, and
  every solve goes through `modeling/optimizer.SOLVER`, one thread: called from one thread
  and then another - a page's runs, the assistant's questions - HiGHS hung or crashed (A9).
  Never call `milp` directly.
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
  model" tab is the evidence, and nothing calls a chance a verdict. The file also scores
  the season model as a forecast reads it (`Evaluation.before_season`), from the rating
  predicted before each season; show both readings, never only the better one.
- **The simulator draws from tested parts and measures nothing it cannot test.** A
  scenario (`domain/scenario.py`) is a roster plus the user's assumptions, all tagged
  "Your assumption"; a season is drawn (`modeling/simulator/monte_carlo.py`) from the
  value model's projections and tested error, the postseason model's season steps, and
  what `fol simulate fit --write` measures into `configs/models/simulator.json`: five
  figures (the value model's miss, a season's noise, the miss on strength, wins per
  point, residual wins) and two distributions (projection misses by reliability band,
  games missed by rotation players). A roster's
  spread is calibrated to the value model's RMSE with the minutes projected, never to
  the sum of the players' spreads. The field is not modelled and every page says so. No build applies it; the
  wins test's coverage is the evidence and a test fails if the shipped intervals drift
  from their claim (`docs/decisions/0015-simulator.md`). The invented league plays
  regular seasons from a planted game model (`tests/league.py`) for these tests.
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
- **Services read fresh, and remember within one answer.** `Lab.read` goes to the
  warehouse every time, so a rebuild in another process is seen at once. A service that
  reads the same tables many times for one answer wraps that work in
  `with lab.remembering():`; nothing is cached across answers below the workbench. The
  workbench caches on the build id, and a model status on the model files' stamps as
  well (`Lab.model_stamp`), so a refit shows without a rebuild or a restart.
- **Refit in order.** A value refit changes the version the build applies and that the
  other files name: `fol value fit --write`, `fol build`, `fol playoffs fit --write`,
  `fol simulate fit --write`, `fol fit test --write`, then the research documents.
- **The assistant is the outermost layer** (`docs/decisions/0018-ai-research-assistant.md`).
  The workbench imports only `front_office.assistant.api`; of providers and pipelines the
  assistant uses only `providers.ollama`, `providers.web`, `pipelines.current`,
  `pipelines.web` and `pipelines.contract_review` (which stores nothing - never
  `pipelines.contracts`, whose import writes). Tests enforce both. Its model is local: `providers/ollama.py` accepts the loopback address
  only, refuses models Ollama marks remote or names as cloud, and sends the context length
  with every request; `configs/assistant.yaml` has no field for a key.
- **No tool writes.** The registry (`assistant/tools.py`) has read, compute, net and draft
  tools only. Saving a roster is the user's click on a reviewed proposal. Never give the
  model table reads, SQL, code, files, a URL it composed, a fit, a build, an import or a
  setting; outside text reaches it quoted as data.
- **A proposal is saved only by the user's click, and only as proposed.** `optimize_roster`
  asks the optimizer what the user asked and nothing else (never the Roster Optimizer
  page's example requirements); each roster found is a `RosterProposal`
  (`domain/proposals.py`) that travels with the answer for the session.
  `assistant.api.save_proposal` -> `ProposalService.save` finds an earlier save by the
  fingerprint in a roster's notes, refuses when the build, the value model, the contract
  file or a salary has changed, and writes the roster and its players in one transaction
  (`RosterRepository.create_with_players`, which `OptimizerService.save` uses too). R01
  and R03 run on the `priced` test database (`priced_template`), the user's decision at A5.
- **An experiment proposal is never applied** (A8). `propose_experiment` drafts one only
  when the user asks, for one of the four tested models (`domain.experiments.TESTED_MODELS`;
  archetypes are rules, left out by the user's decision). The idea is the model's, in
  words: its fields refuse any figure, so none can be echoed in a result and cited back. The
  plan is the lab's (`services/experiments.py`): what a change must beat from the model's
  fitted file, never a document's figure; how it is tested and what was tried, quoted from
  its decision by heading (a test fails if a heading goes); and the rules in
  `configs/experiments.yaml`, written as the lab works - change one only with its decision.
  A proposal travels with the answer; the user's click keeps it in the workspace
  (`research_experiments`), and nothing leads from it to a model file, a setting or the
  lab's data. A change to a model is still a milestone of its own, fitted on request.
- **The user's research is a third file**, `data/assistant/assistant.sqlite`
  (`storage/research.py`, contracts in `domain/tables/research.py`): never in the lab's
  database, never touched by a build. It is versioned: a change to a research contract needs
  a new `Migration` in `storage/research.py` (and a test that brings an older file forward);
  a new file is made at the latest version, an older one is backed up to `backups/` first,
  and ids are never reused. A turn keeps its whole answer as JSON (`domain/research.py`'s
  codec), so an old answer draws exactly as it was and is never rewritten - asking again
  makes a new turn. A file that cannot be used - damaged, not the store, or from a later
  lab - is `ResearchUnreadable`, checked with SQLite's `quick_check` before anything is
  written to it; AI Research then offers *Set it aside and start afresh*
  (`WorkspaceService.set_aside`), which renames it and its `-wal`/`-shm` beside itself and
  never deletes it (A9). A locked file is not a damaged one: it is never offered.
- **A question runs in a workspace** (`api.start(question, workspace_id)`). A follow-up reads
  the last three answered turns of its own workspace's conversation under way and nothing
  else. The workspace's notes reach the model's prompt but never the answer checker: they
  are background, not evidence. A "he" or "they" with nothing to mean is asked about before
  the model runs (`orchestrator._nobody_named`). Every proposed roster waits in its workspace
  until the user saves or declines it, and every press is logged. *Stop* is looked for before
  each reply, as soon as a reply comes back, and before each call: nothing a reply asks for
  is run once the user has pressed it (A9).
- **Saved rosters place their starters with `domain/lineup.py`**: from the nine who play the
  most, each at a position they are listed at where the roster allows (the user's wish at
  the A5 review), and of the lineups that fit, the one with the most projected impact (at
  the A6 review), for every save.
- **A handler formats; the services compute.** A tool's handler (`assistant/*_tools.py`)
  calls service methods and writes what they return as the workbench shows it, with the
  evidence: the build, the contract file's date, a source's address and times. It never
  computes a metric, ranks, or fits. Every figure in an answer must be in a result the
  model was given (`assistant/checker.py`), and a place ("6th") only on a place - for the
  same field, the league or a conference, where the answer names one (A7): so a tool writes
  every place with its field ("4th of 30", "3rd in the East"); an empty read of the lab
  carries the build. A chance or a benchmark's share goes with its interval:
  an answer without one is sent back once, then noted. A question asking for a verdict gets
  a qualified answer and a note, whatever the model says.
- **A modeled figure goes out with its error, and the assistant makes none up.**
  `assistant/model_tools.py` reads the fitted files through the services and cites them by
  revision: a chance with its 95% interval and the season model's record read both ways, a
  scenario with the interval of the seasons drawn and the wins test, a projection with
  the simulator's band for players that well known. A single player's projection has no
  tested interval - say so; never build one in the assistant. A fit profile carries the
  limit that there is no fit score while the evidence is not usable. A scenario for the
  season ahead takes each player's current team (the user's decision): one naming a player
  not on that roster is not run, and the result says which team they are with.
- **The document index is built for each search.** `research_docs` reads `docs/` afresh
  (`config/documents.py`) and searches it with FTS5 in memory (`storage/documents.py`); no
  index file exists. The generated glossary and dictionary and the assistant's recorded
  answers are left out. A section is cited by file and heading (evidence kind `docs`).
- **Current information is a cache beside the lab.** `data/current.sqlite`
  (`storage/current.py`) holds what `pipelines/current.py` fetched: the season's games,
  the league's transactions, the latest injury report, the news feeds' items (A7), and a
  log of every attempt. A
  refresh never touches the lab's database and a build never drops the cache. A source is
  fetched only when its interval (`configs/assistant.yaml`, `current:`) has passed; a
  failure keeps the last copy and says how old it is. "Not on the report" is never
  "healthy". The league's injury report may not be redistributed: never commit one - the
  tests draw their own (`tests/injury_pdf.py`).
- **News comes only from feeds the source register allows** (A7). `configs/assistant.yaml`
  (`news:`) lists them - Hoops Rumors alone, the user's choice - and a feed is added only
  after its robots.txt (AI agents included) and its terms are checked and recorded in
  `docs/DATA_SOURCE_REGISTER.md`. A feed passes every check a page passes
  (`WebProvider.fetch_feed`) and is read by `processing/feeds.py` (a declared entity refuses
  it, and so does a zero byte, which would hide one); each article is one `news_items` row. The pipeline's default refresh leaves the feeds
  out: name `news`. A report never changes a table, a roster or a contract. The model reads
  the feeds through `moves_and_rumors`, named for what they carry: called `news`, the tool
  drew questions about reporting, why a title was won included, away from the web.
- **A contract file is checked before it is imported, and the check stores nothing.**
  `pipelines/contract_review.py` reads a candidate exactly as an import would and compares
  it with the file in use; a source label never imported before is flagged until its terms
  are checked. `fol contracts preview` and Contract Explorer's *Check a new file* reach it;
  the import stays `fol contracts import`, the user's command. `contract_updates` puts the
  moves since the file's date beside the file - never a figure to import.
- **The web goes through `providers/web.py` alone, and never with a URL the model wrote.**
  `read_source` takes an id: a search result's or a pasted link's. Every address, every
  redirect and the address connected to must be public; robots.txt is read for AI agents
  too; refused sites (Sports Reference's, Spotrac, nba.com) are left out of results. The
  search key is the user's own: `FOL_OLLAMA_API_KEY`, from the environment or the
  git-ignored `.env` (template: `.env.example`, which must never hold a value) - never
  `OLLAMA_API_KEY`, never printed, never in a test (the
  conftest removes it). Tests use `tests/web_fakes.py`; nothing in the suite reaches the
  network outside the `network` and `ollama` markers, and a guard in `tests/conftest.py`
  fails any test that tries (A9). Only `providers` import what opens a connection
  (`interfaces` too, for `fol ui`'s check on its own server); an architecture test says so.
- **The evaluation cases are frozen.** `tests/assistant/fixtures/cases.yaml`: never edit a
  case to make a model pass. `tests/assistant/test_cases.py` recomputes every figure in it
  through the services; when a rebuild or refit changes one, update it deliberately and
  say why in the development log. A case the user decides is wrong changes by that
  decision alone, logged and commented; a saved benchmark is then judged again with
  `--rescore`, not run again until it passes (`docs/AI_EVALUATION.md`). The end-to-end
  run's current and web tools see `tests/assistant/recorded.py`, an invented world dated
  the case file's day; change it only to fix what it gets wrong about that day.
- **The API is an interface too** (the capstone: `docs/decisions/0019-capstone-api.md`,
  `docs/CAPSTONE.md`). `server/` imports domain, config, pipelines, services and only
  `front_office.assistant.api`; it validates and formats, and computes nothing. Every request
  and response is a Pydantic model in `server/schemas.py`, and every endpoint but `/health`,
  `/auth/register` and `/auth/token` asks for `auth.current_user`: a test reads both off the
  published schema. The accounts are a fourth file, `data/api/accounts.sqlite`, which no build
  touches; a password is only ever a bcrypt hash, never returned or logged. The signing key
  is `FOL_API_SECRET` (environment or `.env`) or `data/api/signing.key`: never print it, never
  give `configs/api.yaml` or `.env.example` a value for it; tests sign with their own. The
  data endpoints (`server/data.py`) send each figure under its metric key beside `metrics`
  saying what it is, a modeled one with the value model's test, and never a salary or a
  contract figure; they open the lab per request and never create it.
- **RAG sits beside the assistant's keyword search, never in its place.** `research_docs`
  and its frozen cases are unchanged. The API's answers come from `assistant/rag.py` through
  `assistant.api.ask_documents`: the passages the keyword search reads, less the text a model
  or the web wrote (`configs/api.yaml`'s `rag.left_out`), embedded into ChromaDB
  (`data/rag/`, `chromadb` imported by `storage` alone), the nearest given to the
  assistant's model as quoted data, the answer held to them by the assistant's checker.
  ChromaDB gets every embedding from Ollama - never an embedding function, which would
  download a model - and runs with its telemetry off; never read a collection's
  `configuration` (a deprecation warning). Import it lazily outside the server: it takes a
  second to load. Tests script Ollama through `assistant.api.connect` and embed with
  `tests/rag_fakes.words`.
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
  Charts are also read on a phone (UI polish P4): a long axis title takes two lines, a
  line's name keeps to the chart, cap-line names take three rows - and a page still keeps
  its axis titles and category labels short, since a phone's plot can be 150px wide.
- **Colours live in `wb/theme.py`.** `.streamlit/config.toml` repeats them and a test
  keeps the two in step. A new colour has to pass `tests/ui/test_theme.py`. The page's
  primary colour is the forest-green `brand`, never a chart colour (UI polish P1). Every
  series reaches 3:1 on its chart and tick labels 4.5:1, in both themes (P4). Code in text
  is the secondary ink (`codeTextColor`): left unset it is the green of a good state, and a
  file path read as a link (P7).
- **Styling is the theme's.** No page writes CSS or HTML. What the theme cannot set is a
  rule in `wb/style.css`, applied once by the frame (`style.apply()`), listed in
  `docs/ui-polish/DESIGN_SYSTEM.md` and held to that list by `tests/ui/test_style.py`; a new
  rule is the owner's decision. Errors, warnings, successes and notes go through
  `components.alert`, one icon per kind (UI polish P2). A tag that several pages use -
  `components.NOTE`, `CHECK`, `OUT_OF_DATE`, `NO_ANSWER` - is written once; a test holds
  every tag word to one icon and one colour (P3). Streamlit gives CSS no theme marker and no
  colour variable, so a rule's colour must read on both themes: the focus ring on links
  (P8) is the dark brand, at 3:1 or more on either.
- **The frame lists every page twice**: as the top bar's menus and, for the keyboard, as
  *All pages* at the foot of the sidebar (`app.all_pages`, UI polish P8). Both read `PAGES`,
  so a new page goes there once.
- **README screenshots are taken from a copy rebuilt without the contract file**, so no
  salary is published (UI polish P8; `docs/ui-polish/FINAL_AUDIT.md` section 7).
- **Nothing in `app.py` may stand alone as an expression.** Streamlit's "magic" draws a bare
  string or name in the main script on the page: write a note there as a `#` comment, never
  a docstring under a constant (at P3 one appeared above every title). A test checks.
- **What cannot be undone asks first** (the owner's decision, UI polish P3): a delete or a
  clear is `components.confirmed_button`, off until its box is ticked and never the page's
  primary button. A test keeps any page from drawing a plain Delete or Clear button.
- **A segmented control is for a few short choices.** On a row of its own it wraps in a
  narrow window; inside columns or beside other controls it cannot, and its last choices go
  out of reach (the simulator's *Regression* at 1024px). There, a longer set is a selectbox.
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
- **Key a fold, a tab row or a popover that must stay open while the page changes around
  it.** Unkeyed, one whose label changes - a count - or that moves up a place when a line
  above it goes - a notice - is drawn as a new one, closed. At UI polish P7 declining a
  roster closed the workspace's shelf, and a delete's popover closed as its box was ticked.
  Keep counts out of a tab's name.
- **A form that starts again gets new widgets.** Give its widgets their stored values with
  `value=` and end their keys with what they show (`research._stamp`) or with how many
  times the form was sent (`research.SENT`). Popping a key is not enough: the browser keeps
  showing what was typed and sends it back on the next click - at A6 a workspace's old
  notes were written back over its summary that way. Starting widgets through
  `st.session_state.setdefault` failed too: the settings form came back with an empty
  name, and a list showed "Choose an option" for a stored `None`. `AppTest` sees none of
  this; the browser pass does.
- **Never call `st.switch_page` from a fragment that reruns itself** (`run_every`): a run
  of it arriving after the switch left the new page blank. Link to the page with
  `st.page_link` instead (the dialog's *Open in AI Research*).
- **Plain words on screen.** The user wants simple, easy language wherever possible: short
  sentences, everyday words, a statistic explained in a few words where it appears. This
  holds for page text, notes, table headings, chart titles and the assistant's answers
  (its rule 13); keep a lab term such as net rating or 95% interval where it is needed.
- **Headline tiles cut off long text.** Keep a figure's context to about twenty
  characters, or give the row fewer tiles (`components.figures(..., per_row=3)`). Each row
  is a grid that wraps in a narrow window (UI polish P3): tiles at least 11rem in a row of
  five, 14rem in a row of four or fewer. It hooks the rows' keys, `tiles-N` and
  `tiles-wide-N`, counted afresh each run from `components.new_page()` in the frame: draw
  tiles only through `components.figures`.
- **The AI Research page reaches the assistant through `front_office.assistant.api`
  alone**, imported by its full name (`import front_office.assistant.api as api`: the
  boundary test reads `from front_office.assistant import api` as the whole package). A
  question runs as an `api.Job` in its own thread with its own `Lab`; the page only starts
  it, looks in on it from a fragment, and takes the finished turn in at the top of the
  next run. The tool chooses a result's chart (`domain.assistant.Chart`); the page draws
  it, and declines one the house rules would refuse. Model text goes through `_prose`
  (a dollar sign is not a formula, an image is not fetched) and outside text through
  `_escaped`. No page test reaches Ollama or the network: `tests/ui/conftest.py` keeps the
  assistant offline unless a test scripts a model (`tests/ui/test_research_page.py`).
  An answer is drawn by `wb/answers.py` wherever it appears; its widget keys come from the
  kept turn's id. Opening the page makes a workspace if there is none, and asking keeps
  turns: a test that asks, or counts workspaces, works on a private copy of a project.
  A status box that a fragment draws again is written into without a `with` block
  (`answers.under_way`): leaving one marks it complete, and a running question showed a
  tick (UI polish P7). The conversation comes straight after the workspace and its one fold
  of shelves; the mode and the conversation's buttons sit under it, by the question box.
- **Ask the Docs reaches the lab's API through `wb/api_client.py` alone** (the capstone,
  decision 0019): the workbench's one module that opens a connection, with `requests`, to
  the address `FOL_API_URL` names and no other; the architecture test excepts it and only it.
  The token stays in the session. Its page tests run the real app in their process through
  `api_client.connect`; every other UI test finds the API not answering
  (`tests/ui/conftest.py`). `AppTest` files an expander that has an icon as a status box:
  give a fold a test looks for no icon.
- **Ask AI about this** (`wb/ask.py`) goes under a page's header:
  `ask.button(ask.from_filters(page, filters, roster_id=...))`. It never changes the
  sidebar, asks in the workspace open on the AI Research page, and shares that page's one
  running question (`state.AI_JOB`). Its `body` is a plain function so a test can draw it
  inline: in a browser a dialog reruns alone, which `AppTest` cannot follow.
- **Page tests** (`tests/ui/test_pages.py`) draw a page with `AppTest` and compare what
  it shows with what the service returns. `tests/ui/test_sweep.py` tries every control
  on every page; a new page must be added to its `STARTS`. `AppTest` cannot click a
  table row or edit a table cell: see `tests/ui/test_clicks.py` and `TestRosterEdits`.
- **Look at it, and click through it.** A running server keeps old modules loaded:
  restart `fol ui` after a code change, then check the page in the light and the dark
  theme and use every control you touched. Passing tests say nothing about clipped
  labels, collisions, or a click that does the wrong thing - nor about a chart whose
  settings are right and which draws nothing: the chance curve's uncertainty band was
  never on screen until UI polish P6 read the chart in a browser. A browser pass cannot share
  the machine with a parallel test run: Streamlit's connection-error dialog appears under
  load and intercepts every click. Look with a team and a player chosen as well as without:
  some charts and controls appear only then, and at P5 two of them were cut at 1024px.
  Reach the pages through the top bar - an address typed in starts a new session, which
  drops the sidebar's choices. A page with a question box opens at its end. Check the
  assistant's surfaces live, with the local model, on a throwaway copy of the data:
  Ollama's own log (`%LOCALAPPDATA%\Ollama\server.log`) counts its chat requests, the way to
  show that nothing is asked twice (P7). For the offline state, point a copy of `configs/` at
  an empty local port through `FOL_HOME` - never stop the owner's Ollama. And go through a
  changed page once with the keyboard alone (P8: `docs/ui-polish/FINAL_AUDIT.md` section 5).

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
