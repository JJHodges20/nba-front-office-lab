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

The later roadmap stages (player value, roster fit, optimisation, prediction, simulation)
sit between `analytics` and `services` in one layer, `modeling`.

This document describes the structure as built. Every layer's package and import rule
existed from milestone 1 except `modeling`, which milestone 9 added; a layer's code
arrives with the milestone that builds it. See `docs/ROADMAP.md` for the milestones.

## Layers and what each may import

All layers live in `src/front_office/`. A layer may import itself, the layers listed for
it, and nothing else in the project (decision
[0001](decisions/0001-layered-architecture.md)).

| Layer | Responsibility | May import |
| --- | --- | --- |
| `domain` | Shared vocabulary: seasons, cap-rule models, data contracts. Pure, no I/O. | nothing |
| `config` | Settings, season rules, eras and model files read from `configs/`, and the lab's own documents from `docs/` for the assistant's search. The only place YAML is parsed. | `domain` |
| `providers` | Adapters that retrieve data from external sources and return it unchanged. The only layer that touches the network. | `domain` |
| `rawstore` | Immutable, timestamped snapshots of what providers returned. | `domain` |
| `processing` | Pure functions that turn raw payloads into frames satisfying a data contract. | `domain` |
| `storage` | Database schema (built from the data contracts), repositories, and the in-memory search over the lab's documents. The only layer that writes SQL. | `domain` |
| `quality` | Data-quality checks. They report problems; they never repair data. | `domain` |
| `analytics` | Every formula. Pure functions over frames. | `domain` |
| `modeling` | Estimates fitted to the lab's own data and tested out of sample. Pure functions over frames. | `domain`, `analytics` |
| `pipelines` | Orchestrates provider -> rawstore -> processing -> storage, and applies the fitted models. | `domain`, `config`, `providers`, `rawstore`, `processing`, `storage`, `quality`, `modeling` |
| `services` | What the UI and CLI call: repositories + analytics, returned display-ready. | `domain`, `config`, `storage`, `analytics`, `quality`, `modeling` |
| `interfaces` | The `fol` command line. Thin. | `domain`, `config`, `pipelines`, `services` |
| `assistant` | The AI research assistant: typed tools over the services, a local language model. Outermost. | `domain`, `config`, `providers`, `pipelines`, `services` |
| `apps/` (UI) | Streamlit workbench. Displays what services return. | `domain`, `services`, `assistant` |

The lower layers (`providers` through `modeling`) take plain values as arguments rather
than reading configuration themselves. Only `pipelines`, `services`, `interfaces` and
`assistant` load settings, which keeps everything beneath them trivially testable.

Two rules are narrower than a layer (decision 0018). The workbench reaches the assistant
through `front_office.assistant.api` alone. The assistant uses only `providers.ollama`
and `providers.web` of the providers, and `pipelines.current` (fetching current
information), `pipelines.web` (reading a page) and `pipelines.contract_review` (checking a
contract file, storing nothing - A7) of the pipelines, so it cannot reach the
stats.nba.com ingest, a build, a fit or a contract import.

Third-party libraries are confined the same way: `nba_api` and `requests` only in
`providers`; `sqlalchemy` and `sqlite3` only in `storage`; `yaml` only in `config`; `pypdf`
only in `processing`; `typer` and `rich` only in `interfaces`; `streamlit` and `plotly` only
in `apps/`.

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
the **provenance** of each column (decision [0002](decisions/0002-data-contracts.md)).

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

## Metrics

What a data contract is to a table, a `MetricSpec` (`domain/metrics.py`) is to a number
on screen: its key, label, description, display format, provenance and which direction
is better. The specs are grouped in catalogs next to the code that computes them:
`PLAYER_METRICS` and `TEAM_METRICS` in `analytics`, and the value, role, roster-fit and
postseason catalogs the later milestones added; `services/glossary.py` lists them all.

- `analytics/formulas.py` defines each formula once; the catalog modules call it.
- A service returns frames whose columns are catalog keys, together with the catalog,
  so a screen labels and formats a number without knowing how it was produced.
- `docs/METRICS.md` is generated from the catalogs (`fol metrics --write`), and a test
  fails if the committed file is stale.
- League-published figures are passed through and tagged `measured`. Where the lab
  estimates instead - team ratings over a span of games - the service names the
  estimated metrics. See `docs/decisions/0006-metrics.md` and `0007-team-metrics.md`.

## From source to table

```
fol ingest:  provider.fetch(dataset) -> Snapshot -> RawStore.save()
fol check:   RawStore -> normalize() -> tables + issues -> quality checks   (writes nothing)
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

## The database

```
fol build:  RawStore -> normalize() -> quality checks -> Warehouse.replace() [one transaction]
```

One SQLite file, `data/front_office.sqlite`, whose tables are generated from the data
contracts. Tables come in two groups:

- **Rebuilt** - the league tables, the modeled tables computed from them
  (`player_value_scores`, `player_archetypes`, `team_fit_profiles`) and the last build's
  own report (`build_issues`, `check_results`, `raw_snapshots`). Every build drops and
  rewrites all of them inside
  a single transaction, so a reader sees one complete build or the other, never a mix,
  and a failed build leaves the previous one in place.
- **Kept** - the user's rosters (`custom_rosters`, `roster_players`) and the history
  (`fetch_log`, `builds`). Created once and never dropped.

Three repositories are the only way in or out: `Warehouse` (read league tables, replace
them), `RosterRepository` (the user's rosters) and `OperationsLog` (fetch and build
history). They return frames that satisfy the table's contract. See
`docs/decisions/0005-database.md`.

## Services and the workbench

```
fol ui:  apps/workbench/app.py -> wb.views.<page> -> front_office.services.Lab -> storage + analytics
```

`services.Lab` opens the database and the season rules; the services hang off it:
`players`, `teams`, `league`, `benchmarks`, `contracts`, `builder` (the user's rosters),
`value`, `fit`, `optimizer`, `postseason`, `simulator` and `health`.
A service reads tables, calls analytics, and joins the result with names. It contains
no formulas. It reads fresh, so a rebuild in another process is seen at once; for one
answer that reads the same tables many times it asks the lab to remember what it reads
(`Lab.remembering`), and the memory ends with the answer. The warehouse builds a frame
from the row tuples a cursor returns and conforms it to the table's contract on the
way out.

The workbench (`apps/workbench`) is a Streamlit app:

| Part | Role |
| --- | --- |
| `app.py` | The frame: navigation, global filters, data status. |
| `wb/views/` | One module per page, each with a `render()`. |
| `wb/state.py` | The global filters: season, phase, team, player, comparison window. |
| `wb/data.py` | Access to the lab. Results are cached per build id; a model status on the model files' stamps as well, so a refit shows without a rebuild. |
| `wb/charts.py` | Chart builders: a frame and a palette in, a figure out. |
| `wb/theme.py` | The palette, for a light and for a dark surface. |
| `wb/components.py`, `wb/formats.py` | Shared pieces and text formatting. |

It displays what services return and computes nothing itself; see
`docs/decisions/0008-workbench.md`. `.streamlit/config.toml` holds the page theme, which
a test keeps in step with `wb/theme.py`.

## Season rules

Cap thresholds, salary exceptions, maximum salaries and roster limits live in
`configs/seasons/<season>.yaml`, one file per season, each citing where its figures were
verified. `front_office.domain.cap_rules.SeasonRules` validates them (thresholds must
ascend, a source is mandatory, unknown keys are rejected) and exposes a `version`
fingerprint that is stored with anything computed from the rules.

To add a season: copy the latest file, rename it, update the `season` field and every
figure, and cite the announcement. The loader refuses a file whose name and `season`
field disagree.

## Eras and benchmark research

Historical research is asked of an *era*, a named span of seasons defined in
`configs/eras.yaml` (`domain/eras.py`), or of any span chosen on the spot. An era never
reaches outside the seasons whose postseason is complete.

```
fol benchmarks:  team_seasons -> analytics.benchmarks -> services.benchmarks
                 -> docs/research/BENCHMARKS.md, and the Winning Benchmarks page
```

`analytics/benchmarks.py` holds the research: stage frequencies by band with Wilson
intervals, profiles of the teams at each stage by league rank within their season, and
within-season concordance with intervals from resampling seasons. Nothing is fitted;
see `docs/decisions/0009-benchmarks.md`. The document is generated from the database
and is never edited by hand.

## Player value

```
fol value fit --write:  database -> modeling.value.fit_value_model
                        -> configs/models/player_value.json
fol build:              league tables + that file -> modeling.value.score_players
                        -> player_value_scores
                        + configs/archetypes.yaml -> modeling.archetypes.assign_archetypes
                        -> player_archetypes
fol value report:       the file + the database -> docs/research/PLAYER_VALUE.md
```

`modeling/value` holds the model. `features.py` turns a season into rates per 100
possessions against the league; `pooling.py` pools earlier seasons by minutes;
`design.py` defines the terms an estimate is a weighted sum of, once, for fitting and
scoring alike; `estimate.py` fits the weights to team results and tests them one season
at a time against simpler methods; `scoring.py` applies a fitted model; `availability.py`
projects minutes; `wins.py` and `market.py` turn impact into wins and wins into money.

The specification (`configs/models/player_value.yaml`) is edited by people. The fitted
model (`configs/models/player_value.json`) is written by `fol value fit --write` and
carries its weights with their intervals and every piece of evidence for them. A build
applies it and never fits one, so values change only when someone fits the model again.
Tests of fitting use an invented league with planted weights (`tests/league.py`) and a
loop-based reference that shares no code with the model (`tests/value_reference.py`).
The model is tested twice: with each season's minutes as played, the measure of the
rating alone and the basis of every comparison with simpler methods, and with the
minutes projected by the minutes model, the error a forecast carries
(`Validation.projected`; decision 0016).
See `docs/decisions/0010-player-value.md`.

`modeling/archetypes.py` scores every player against the roles defined in
`configs/archetypes.yaml` (`domain/archetypes.py` validates them, `config/archetypes.py`
loads them): the measures, the groups a role can be open to, the weakest-percentile
score within a season, and how well each role carries over between seasons. Nothing in
it is fitted, and the build applies the rules after the value model because the
defensive roles use its defensive impact. See `docs/decisions/0011-archetypes.md`.

## Roster fit

```
fol build:            value and archetype tables -> modeling.fit.team_profiles
                      -> team_fit_profiles (every real team-season)
fol fit test --write: the value model's test + last season's profiles
                      -> modeling.fit.fit_evidence -> configs/models/roster_fit.json
a page:               FitService.team / FitService.roster -> the same profile code,
                      placed among team_fit_profiles; the evidence read off the file
```

The measures are defined once in `domain/fit.py` and the table contract, the metric
catalog and `modeling/fit/profile.py` all read off that list. `modeling/fit/evidence.py`
asks whether the measures, taken from the players' previous-season profiles, explain
what the value model's out-of-sample predictions missed; `services/fit.py` profiles a
team or a built roster and applies a correction only if the evidence supports one.
See `docs/decisions/0012-roster-fit.md`.

## The roster optimizer

```
a page:  OptimizerService.pool  (projections for the season ahead + the contract file's
         salaries + the latest season's roles and groups)
         -> modeling.optimizer.solve (an integer programme, HiGHS through SciPy)
         -> rosters, best first, each cut off before the next
         -> OptimizerService.save -> a Team Builder roster, in one transaction
            (RosterRepository.create_with_players; OptimizerService.slots says who starts)
the assistant:  the same run -> ProposalService.from_report -> proposals for review
```

`domain/optimizer.py` holds the request (what a run respects) and the outcome;
`modeling/optimizer.py` the objective - the sum of the parts above replacement for the
minutes projected - the two budgets (payroll and minutes), the requirements, the cuts
that make rosters distinct and the diagnoses of why nothing can be found;
`services/optimizer.py` assembles the pool, resolves a payroll line from the cap rules
and dresses rosters with names. Nothing is fitted and nothing is cached across runs. See
`docs/decisions/0013-roster-optimizer.md`.

## The postseason model

```
fol playoffs fit --write:  database -> modeling.postseason.fit_postseason_model
                           -> configs/models/postseason.json
a page:                    PostseasonService.bracket / series / season_odds / outlook
                           -> the file's parameters and kept draws, applied on request
fol playoffs report:       the file + the database -> docs/research/POSTSEASON.md
```

`domain/stages.py` is the one list of postseason stages, read by the benchmarks and the
model alike; `domain/postseason.py` holds the specification (`configs/models/postseason.yaml`)
and what a fit writes down. `modeling/postseason/` holds the model: `features.py` turns the
tables into what a team is described by (net rating and top-player quality) and into the
games and series the model is fitted and tested on; `series.py` is the game model and a
series enumerated through its format; `bracket.py` reads a bracket from the series played
and carries the series model through it exactly; `hierarchy.py` is the season model, a
chain of conditional steps; `fitting.py` the shared arithmetic (a logistic fit, scores,
calibration, reliability, intervals from resampling seasons); `fit.py` fits both models
and tests them one season at a time against simpler methods and the alternatives tried.

The fitted model is a file written only by `fol playoffs fit --write`. No build applies
it: `services/postseason.py` reads it and computes a chance on request, for a decided
season's bracket and series, for every team of a season, for a real team or a built roster
read as a team of its strength, or for a strength given by hand - every figure with the
interval its kept parameter draws give. The file also scores the season model as a
forecast reads it, from the rating the value model predicted before each season
(`Evaluation.before_season`). Tests of fitting use the invented league with its
playoffs played by a planted game model (`tests/postseason_reference.py`). See
`docs/decisions/0014-postseason-model.md`.

## The scenario simulator

```
fol simulate fit --write:  database -> modeling.simulator.fit_simulator_model
                           -> configs/models/simulator.json (measured figures + the wins test)
a page:                    SimulatorService.run(scenario)
                           -> the roster with the user's assumptions
                           -> modeling.simulator.simulate (thousands of seasons)
                           -> before and after; SimulatorService.save -> a Team Builder roster
fol simulate report:       the file + the database -> docs/research/SIMULATOR.md
```

`domain/scenario.py` is a scenario: the subject (a real team as it stands for the season
ahead, or a built roster), the players added and removed, each player's assumptions
(games missed, development, share of minutes, salary) and the two presets - every one of
them the user's. `domain/simulator.py` holds the specification
(`configs/models/simulator.yaml`) and the measured figures. `modeling/simulator/`:
`measure.py` measures a season's own noise, the residual wins carry, how far projections
miss by reliability and how many games rotation players miss; `monte_carlo.py` draws the
seasons from those figures and from the value model's projections, replacement level and
tested error, reading the postseason model's season steps for the chances; `fit.py`
measures everything and runs the wins test against the value model's own out-of-sample
test with the minutes projected, whose error the simulator carries. `services/simulator.py` assembles and prices a scenario's roster, draws before and
after, and dresses the comparison; `FitService.lineup` places the roster's fit measures
for any set of players and shares. No build applies any of it; the invented league plays
regular seasons from a planted game model so the measurements can be checked. See
`docs/decisions/0015-simulator.md`.

## The AI research assistant

```
a question:  domain.assistant.Context (sidebar, resolved names, sources)
             -> assistant.names: names resolved by code (services.entities); an
                ambiguous one is asked about and the model is not called
             -> assistant.orchestrator: the rules (assistant.policy), the context, the
                tools this build can run (assistant.toolbox, assistant.tools)
                -> providers.ollama: a model on this machine asks for a tool
                -> assistant.executor: the call checked (routing), its ids checked
                   against the lab, its handler run:
                     assistant.lab_tools      -> services
                     assistant.model_tools    -> services (value, fit, postseason, simulator)
                     assistant.document_tools -> services.documents -> config.documents
                                                 (docs/) + storage.documents (FTS5, in memory)
                     assistant.proposal_tools -> services.optimizer -> services.proposals
                                                 (each roster found, a proposal)
                     assistant.current_tools  -> pipelines.current (when due) -> services.current
                     assistant.web_tools      -> providers.web (search) | pipelines.web (a page)
                                                 | news: pipelines.current (the feeds, when
                                                 due) -> services.current.news
                     assistant.contract_tools -> services.current (moves since the contract
                                                 file) beside services.contracts
                     assistant.experiment_tools -> services.experiments (the model files,
                                                 config.experiments, the decisions in
                                                 docs/): a proposal kept with the answer
                -> each result back to the model, quoted as data
             -> assistant.checker: every figure in the answer held by a result, or
                sent back once and then cut -> domain.assistant.Answer
current information:  pipelines.current: stats.nba.com game logs (through the ingest, into
             the raw store), the player-movement file and the injury report
             (providers.nba_current, processing.current), and the news feeds
             (providers.web.fetch_feed, processing.feeds) -> data/current.sqlite
             (storage.current) -> services.current
a contract file checked:  fol contracts preview | Contract Explorer -> assistant.api
             .review_contract_file -> pipelines.contract_review (read as an import reads
             it; compared with the file in use; nothing stored) -> domain.contract_review
the AI Research page:  apps/workbench/wb/views/research.py -> front_office.assistant.api
             (status; start -> a Job: a thread with its own Lab, its steps readable, a
             stop; history; refresh_current) -> each answer drawn with the workbench's
             own components and charts
an approved proposal:  the user's click -> assistant.api.save_proposal -> WorkspaceService
             .save_proposal -> ProposalService.save (nothing it rests on changed, not saved
             before) -> one transaction; the press logged in the workspace
the user's research:  assistant.api.Job (a question in a workspace) -> WorkspaceService
             (services.workspaces: history, notes, record) -> storage.research
             -> data/assistant/assistant.sqlite (versioned, backed up, no build touches it)
Ask AI about this:  a page -> wb.ask (the page's season, team, player, roster) -> api.start
             in the open workspace; wb.answers draws an answer on either page
scripts/benchmark_ollama.py:  each candidate model's first move -> ASSISTANT_MODELS.md
scripts/evaluate_answers.py:  whole answers on the test databases, in a recorded world
             -> assistant.evaluation.score_answer -> docs/research/ASSISTANT_ANSWERS.md
```

The assistant is the outermost layer, beside `interfaces` (decision 0018). Its settings are
`configs/assistant.yaml` (`domain/assistant.py` validates them, `config/assistant.py` loads
them): the loopback address of Ollama, the default and fallback models, and for Quick and
Deep the context length, thinking and output limit. `providers/ollama.py` refuses any
address off this machine and any model Ollama marks as remote, and sends the context
length with every request. `assistant/tools.py` is the registry: every tool's name, its
arguments as a Pydantic model, its permission class (read, compute, net, draft - no
write) and the milestone that builds it; enumerations come from the domain and the
services rather than being written twice. `assistant/routing.py` asks the model for its
first move and checks it, sending an invalid call back once. `assistant/evaluation.py`
reads the frozen cases and scores a move and a whole answer. `assistant/api.py` is what
the workbench calls.

From A2 the assistant answers. Names are resolved by code before the model is asked
(`services/entities.py` over the lab's name tables, `assistant/names.py` over the
question). The orchestrator (`assistant/orchestrator.py`) runs the loop within the mode's
calls, seconds and context; the executor (`assistant/executor.py`) refuses a player or
team id the lab does not hold and turns a handler's failure into a result that says so.
Every handler only calls service methods and formats what they return the way the
workbench shows it: `lab_tools.py` for the lab's data, `current_tools.py` for what
happened since the build, `web_tools.py` for the web. The answer checker
(`assistant/checker.py`) reads every figure of the answer and keeps it only if something
the model was given holds it at the written precision; it reads the lab's language too (a
chance where no result is one, a verdict, a claim to have saved something) and every
citation, which must name a result this answer holds.

Current information lives in `data/current.sqlite`, apart from the lab's database
(`storage/current.py`, contracts in `domain/tables/current.py`): a refresh replaces a
source's table whole and logs every attempt; a build never drops it and it never touches
what a build made. The season's game logs go through the existing ingest, so their
snapshots land in the raw store for the next build. The web provider
(`providers/web.py`) is the only code that reaches arbitrary addresses, after the checks
of the spec's Safety section; `processing/web.py` turns a page into text with the standard
library's HTML parser, and `processing/feeds.py` a news feed into items (A7): the news
feeds are a fourth current source, kept article by article (`news_items`).

From A3 the workbench asks. The AI Research page imports `front_office.assistant.api` and
nothing else of the assistant: `start` answers a question in a background thread with its
own `Lab`, so a long answer never holds a page's connection or its memory, and the page
looks in once a second through a fragment. A result carries the charts its tool chose
(`domain.assistant.Chart`, built in `assistant/lab_tools.py` from the services' own
figures); the page draws them with `wb/charts.py` under the house rules and writes the
rows in the metric catalogs' labels and formats. Page tests never reach Ollama or the
network: `tests/ui/conftest.py` puts an offline model, the lab's own tools and a refresh
that fetches nothing behind the facade, and a test that needs answers scripts a model.

From A4 the assistant reads the fitted models. `assistant/model_tools.py` calls the value,
fit, postseason and simulator services and nothing else: it fits nothing, and gives every
modeled figure with the error the lab measured for it and the model files it read, by
revision. `assistant/document_tools.py` searches the lab's documents: `config/documents.py`
reads the Markdown under `docs/` and cuts it at its headings (`domain/documents.py`), and
`storage/documents.py` indexes the sections with SQLite's FTS5 in memory for each search
- SQL stays in `storage` - so no index file exists to go stale. `assistant/toolbox.py` holds every handler that needs only the lab
(`LAB_HANDLERS`), which the executor runs by default.

From A5 the assistant proposes rosters, and only the user saves one.
`assistant/proposal_tools.py` runs the optimizer with what the user asked for and nothing
else; `services/proposals.py` turns each roster found into a `RosterProposal`
(`domain/proposals.py`) - the players and where each would start, their salaries, the
payroll, the projected rating with its typical miss, what was asked for and what it rests
on - which travels with the result to the page and lasts the session. The page's button
reaches `assistant.api.save_proposal`; `ProposalService.save` finds an earlier save by the
fingerprint in a roster's notes, refuses one whose build, value model, contract file or
salaries have changed, and otherwise writes the roster and its players in one
transaction (`RosterRepository.create_with_players`).

From A6 the research is kept. `data/assistant/assistant.sqlite` is a third file beside the
lab's database and the current cache (`storage/research.py`, contracts in
`domain/tables/research.py`, the shapes and the answer codec in `domain/research.py`): a
build never touches it, it carries a version log, and an older file is backed up before it
is brought forward. `services/workspaces.py` keeps workspaces, the turns asked in them with
their whole answers, findings, proposals waiting for a decision, and every save or decline.
A question runs in a workspace (`api.start(question, workspace_id)`): the job reads that
workspace's conversation under way and its notes - which reach the model's prompt but not
the answer checker - and keeps the turn when done, answered or not. The workbench reaches
the workspaces as it reaches any service (`data.research()`, never cached); the AI Research
page draws them, and `wb/ask.py` asks from any other page about what that page shows. Every
roster save places its starters with `domain/lineup.py`.

From A8 the assistant drafts experiments for the lab's tested models, and nothing applies
them. `domain/experiments.py` holds a proposal's two parts - the idea, the assistant's in
words and without figures, and the plan, the lab's - and the shape of
`configs/experiments.yaml` (`config/experiments.py`), the rules a person wrote for each
model. `services/experiments.py` builds the plan from the model's fitted file, the
rules and the sections of its decision (through `services/documents.py`);
`assistant/experiment_tools.py` puts the idea beside it. A drafted proposal travels with
the answer like a roster; the user's click keeps it in the workspace
(`research_experiments`, the research store's version 2, through `api.keep_experiment`
and `services/workspaces.py`). No path leads from a proposal to a model file, a setting
or the lab's data.
See [AI_ASSISTANT_SPEC.md](AI_ASSISTANT_SPEC.md) and [AI_EVALUATION.md](AI_EVALUATION.md).

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
- `tests/ui/` - the workbench: the palette by arithmetic, the chart builders, every
  page drawn without a browser against a database built from the fixtures, and a sweep
  that puts every control on every page through every value it offers.
- Tests marked `network` call live services and are deselected by default
  (`pytest -m network`).
- Warnings are errors (`filterwarnings = ["error"]`).

## How to add a table

1. Declare its `TableContract` in the matching module under `domain/tables/` and add it
   to that module's `TABLES`. Remove it from `PLANNED_TABLES`.
2. Write the normaliser in `processing/` and finish it with `conform_frame`.
3. Run `fol dictionary --write`.
4. Test the normaliser against a recorded fixture.

## How to add a metric

1. Add its formula to `analytics/formulas.py` if it is new, and compute it where the
   catalog's other metrics are computed.
2. Add a `MetricSpec` to the catalog: label, description, format, provenance, which
   direction is better.
3. Run `fol metrics --write`.
4. Test it by hand on a small example and, where the league publishes the same
   quantity, against the league's figure.

## How to add a page to the workbench

1. Give a service a method that returns everything the page shows. If the page needs a
   number, the service computes it.
2. Add an accessor to `wb/data.py`, cached on the build id.
3. Write `wb/views/<page>.py` with a `render()` and add it to `PAGES` in `app.py`.
4. Draw charts with the builders in `wb/charts.py`, each through `components.chart` so
   it gets its table view and exports.
5. Add the page to `PAGES` in `tests/ui/test_pages.py` and to `STARTS` in
   `tests/ui/test_sweep.py` (a test fails until both are done), and test what it shows
   against what the service returns.
6. Look at it in both themes, and click through anything that can be clicked.

## How to add a stats.nba.com dataset

1. Add it to `NbaStatsDataset` and `_SPECS` in `domain/datasets.py`.
2. Map it to its endpoint in `providers/nba_stats.py`. A test confirms the parameters
   exist in the installed `nba_api`.
3. Request it in `pipelines/ingest.py` (`league_requests` or `team_requests`).
4. Normalise it in `processing/nba_stats/`, wire it into `pipelines/normalize.py`, and
   add any cross-table check to `quality/checks.py`.
5. Add it to `scripts/make_fixtures.py`, rebuild the fixtures, and test against them.
