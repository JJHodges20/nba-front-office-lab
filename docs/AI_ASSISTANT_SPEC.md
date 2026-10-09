# The AI Research Assistant - specification

What the assistant does, what it may touch, and how an answer is put together. The
architecture and its reasons are [decision 0018](decisions/0018-ai-research-assistant.md);
how it is tested is [AI_EVALUATION.md](AI_EVALUATION.md). This document describes the
design as approved at milestone A0; each milestone notes here what it built.

## Purpose and scope

Ask a basketball question in plain words; get back an answer whose every figure comes
from the lab's services or a dated source, with the lab's distinctions kept: measured,
derived, estimated over a span, modeled, the user's assumption, and reported elsewhere.

| Release | Milestones | What it can do |
| --- | --- | --- |
| First usable | A0-A3 | History and seasons from the lab; completed games, injuries and transactions; public reporting through web search, feeds and pasted links; tables and charts; Quick and Deep modes. Conversations last the session, and the page says so. |
| Full | A4-A9 | The value model, fit, postseason chances and the simulator; 2-4 roster proposals saved only by the user's click; named workspaces that persist; asking from any page; contract-update review; research proposals for the models. |

**Not in scope:** in-progress play-by-play; a CBA-legal trade or signing plan (the
optimizer finds affordable rosters, not legal transactions); any change the assistant
makes to data, models, settings or rosters on its own; a fitted "fit score".

## How a question becomes an answer

1. **Context.** The page hands over the sidebar filters (season, phase, team, player), the
   workspace's active scenario if any, and sources the user pasted.
2. **Names first, without the model.** A deterministic pre-pass resolves player, team and
   season mentions against the lab's own name tables (`players`, `team_seasons` with
   each season's franchise name). One candidate: its id goes to the model. Several: the
   user is asked which, before any tool runs. None: the model may call
   `resolve_entities`.
3. **Planning.** Common questions with one obvious tool may be routed by rule; otherwise
   the local model picks a tool and its arguments from the registry.
4. **Execution.** The executor validates the arguments against the tool's Pydantic model
   (one repair attempt on failure), checks the permission class and the mode's limits,
   runs the tool with a timeout, and stores the result under an id.
5. **The answer.** The model writes from the results only. A checker compares every
   number in the text with the cited results as displayed; an unmatched figure is sent
   back once for repair, then removed, and the answer is marked *qualified*.
6. **Display.** The workbench shows the text, then tables and charts drawn from the stored
   results, then the evidence: sources with their dates, the build, model revisions,
   assumptions and warnings.

## Quick and Deep

| | Quick | Deep |
| --- | --- | --- |
| For | One fact or one comparison | Several sources, scenarios or explanations |
| Tool calls | up to 3 | up to 12 |
| Web searches / pages read | 1 / 2 | 4 / 8 |
| Time budget | 90 s | 5 min, with progress and a cancel button |
| Model thinking | off where the model allows | on |

The model may suggest Deep; the user's choice stands. The figures are starting points,
set from A1's measurements in `configs/assistant.yaml`.

## The tool registry

Permission classes: **read** (the lab's database and model files, through the services);
**compute** (an optimizer or simulator run kept in memory); **net** (current data and the
web; may fill a cache); **draft** (a proposal stored for the user to review). There is no
write class.

| Tool | Class | Arguments | What it calls | From |
| --- | --- | --- | --- | --- |
| `resolve_entities` | read | text, kind | new `EntityService`: `players` (names, first and last season), `team_seasons` (franchise names by season), `Lab.team_labels()` | A2 |
| `data_status` | read | - | `Lab.status()`, `Lab.model_stamp()`, `HealthService.sources()`, `.gaps()`, each model service's `status()`, the current cache's dates | A2 |
| `player_stats` | read | player_id, season, season_type, view (season, career, games, form), last_games | `PlayerService.table(season, season_type, window=, qualification=)`, `.profile()`, `.game_log()`, `.rolling(full_spans=True)` | A2 |
| `compare_players` | read | player_ids (2-5), season, season_type, metrics, last_games | `PlayerService.table()` then `.compare(table, ids, keys)` | A2 |
| `team_stats` | read | team_id, season, season_type, view (season, history, games, form, rotation), last_games | `TeamService.table()` (with `estimated` for spans), `.profile()`, `.game_log()`, `.rolling()`, `.rotation()` | A2 |
| `league_context` | read | season, view (standings, team_ranks, averages, champions, playoffs) | `LeagueService.standings()`, `TeamService.table()`, `LeagueService.averages()`, `.champions()`, `.playoffs()` | A2 |
| `historical_benchmarks` | read | stage, measure, era, first/last season | `BenchmarkService.era()` or `Era.between()`, `.summary()`, `.rates()`, `.profiles()`, `.separation()` | A2 |
| `metric_definition` | read | metric | `METRIC_CATALOGS`, `PlayerService.metric()`, `TeamService.metric()` | A2 |
| `contract_info` | read | view (player, team, league, cap_rules), season, player_id, team_id | `ContractService.salaries()`, `.team_payrolls()`, `.commitments()`, `.outlook()`, `.cap_rules()`, `.sources()`; always with `LabStatus.contract_as_of` | A2 |
| `current_games` | net | team_id, since, until | new `CurrentDataService` over `data/current.sqlite` | A2 |
| `injury_report` | net | team_id, player_id | new `CurrentDataService` | A2 |
| `transactions` | net | team_id, player_id, since | new `CurrentDataService` | A2 |
| `web_search` | net | query, max_results | `providers.web` (Ollama web search) | A2 |
| `read_source` | net | source_id | `providers.web`: a source id from search results, a feed, or the user's message - never a URL the model wrote | A2 |
| `player_value` | read | view (player, season_leaders, projections, breakdown, roles, value_for_money, model_evidence), player_id, season | `ValueService.player()`, `.season()`, `.projections()`, `.parts()`, `.roles()`, `.for_money()`, `.card()`, `.status()` | A4 |
| `roster_fit` | read | team_id + season, or roster_id; view (profile, evidence, champions) | `FitService.team()`, `.roster()`, `.evidence()`, `.champions()`, `.status()` - description; no correction while the evidence is not usable | A4 |
| `postseason_outlook` | read | view (team, roster, strength, bracket, season_odds, model_record), team_id, season, roster_id, net_rating, top_players | `PostseasonService.team()`, `.roster()`, `.outlook()`, `.bracket()`, `.season_odds()`, `.series()`, `.model()`, `.status()` | A4 |
| `simulate_scenario` | compute | subject (team, roster), subject_id, add/remove player ids, per-player assumptions, availability, development | `SimulatorService.default_scenario()`, `.run(Scenario)`, `.status()` - arguments validated into `domain.scenario.Scenario` | A4 |
| `research_docs` | read | query | new full-text index (SQLite FTS5) over `docs/`, cited by file and heading | A4 |
| `optimize_roster` | compute | budget mode, budget in millions, roster size, group and role minimums, locked and excluded ids, options (2-4) | `OptimizerService.defaults()`, `.budget_for()`, `.solve(OptimizerRequest)`; each roster found becomes a draft proposal | A5 |

**Never exposed to the model:** `Lab.read` or any table read, SQL, Python, a shell, files,
a URL it composed, any `pipelines` function but the current-data refresh (and that one is
run by the executor, never chosen by the model), `BuilderService` edits, the optimizer's
or simulator's `save`, settings and model files.

**Saving a roster** is not a tool. The workbench shows a proposal's players, payroll, the
contract file's date, its assumptions and its projection; the user presses *Save approved
roster*; the application checks the proposal's fingerprint and that nothing it rests on
has changed, then saves it in one transaction, with the fingerprint in the roster's notes
so a second click finds it rather than saving twice (A5).

## What a result carries

`result_id`; the tool and its validated arguments; the outcome (`ok`, `empty`,
`unavailable`, `error`); a bounded table for the model (the full table stays with the
page); for each column its label, unit and provenance from the metric catalogs or table
contracts; the stamps - build id and time, model revisions, the contract file's as-of
date, and for an outside source its URL, publication, effective and retrieval times;
intervals wherever the service gives them; warnings (an estimate over a span, a model not
current, stale data); and the user's assumptions, tagged as theirs.

## What an answer must do

- **Four parts** for anything substantial: the answer; the evidence (figures with units,
  seasons, dates, sources); the reading (measured, derived, estimated, modeled, assumed,
  reported - kept apart); the limits (interval, sample size, what is missing, how old the
  data is).
- **Three outcomes:** *supported* (answered from results), *qualified* (part answered,
  the rest named as missing, stale or estimated), *insufficient* (nothing invented; what
  is missing is said). A question back to the user and a refusal are answers too.
- **The lab's language.** A benchmark is a frequency among past teams, with its count and
  interval, never a team's chance. A chance comes only from the postseason model or the
  simulator, with its 95% interval and the model's record. Ratings over a span carry "≈".
  Eras are compared within their own seasons. No verdicts ("a contender"), no
  recommendations ("should sign"), no single "best" roster; trade-offs instead. League
  statistics are credited to NBA.com. A roster from the optimizer is a hypothetical
  affordable roster, not a legal acquisition plan.

## Charts and tables

The model may ask for a chart by naming a kind, a result id and its columns. The page
checks the request - a known kind, columns that exist, at most the series the house rules
allow, one unit per axis - and draws it with `wb/charts.py` through `components.chart`, so
it has its table view and exports. Kinds map onto the existing builders: bars
(`diverging_bars`, `stacked_bars`), lines (`line`, `lines`), `scatter`, intervals
(`interval_rows`, `interval_columns`, `band_line`), `histogram`, percentiles
(`percentile_bars`, `comparison_dots`). No code, SQL or chart definition from the model is
run.

## Current information

| Source | Refreshed when older than (starting values) | Notes |
| --- | --- | --- |
| This season's league game logs (stats.nba.com) | 1 hour on game days, 12 hours otherwise | Preseason games are labelled preseason and never counted as regular season. |
| Injury report (official PDF) | 30 minutes on game days | A player not listed is "not on the report", never "healthy". Teams not yet submitted are said so. |
| Transactions (stats.nba.com player movement) | 3 hours | Shown with the transaction date; a move newer than the build is flagged against the lab's rosters, which are not changed. |

At launch the workbench checks once per session and fetches only what is due, showing
*checking*, *updated*, *unavailable* or *cached as of*. A manual refresh is on the page.
`fol refresh` stays a separate, explicit step; nothing refits a model.

## Settings and failure

`configs/assistant.yaml` holds the Ollama address (loopback only), the default and
fallback models, the context length and thinking per mode, temperature and output limits.
With Ollama stopped the page says how to start it and every other page works as before.
Without a network the lab's own questions still work; current and web tools say
*unavailable* or *cached as of*. A source that fails returns its last good copy, dated.

## Safety

- **Outside text is data.** Page, feed and document text reaches the model quoted, as a
  tool result, never in the instructions. The model cannot compose a URL: `read_source`
  takes a source id. No tool writes. A page that asks for anything is ignored, and the
  evaluation includes such pages.
- **Fetching.** http and https only; every address, after every redirect, must be public
  (no loopback, private, link-local or reserved ranges); size and time limits; no cookies
  or credentials; robots.txt honoured, judged as an AI agent; no paywall or bot-check
  workarounds. Sports Reference and Spotrac are refused; www.nba.com pages are not
  fetched.
- **Local only.** See decision 0018: loopback model host, remote models refused, no keys
  in configuration; the web search key is read from the environment by the web provider
  alone.
