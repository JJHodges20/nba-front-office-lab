# The AI Research Assistant - specification

What the assistant does, what it may touch, and how an answer is put together. The
architecture and its reasons are [decision 0018](decisions/0018-ai-research-assistant.md);
how it is tested is [AI_EVALUATION.md](AI_EVALUATION.md). This document describes the
design as approved at milestone A0; each milestone notes here what it built.

## Built so far

| Milestone | What exists |
| --- | --- |
| A0 | This specification, [decision 0018](decisions/0018-ai-research-assistant.md), the evaluation design and its 59 cases. |
| A1 | `configs/assistant.yaml` and its validation (`domain/assistant.py`, `config/assistant.py`); the Ollama adapter (`providers/ollama.py`); the `assistant` layer: the tool registry with every tool's arguments model (`tools.py`), the rules and context (`policy.py`), the first move and its one repair (`routing.py`), scoring (`evaluation.py`), and the facade's readiness check (`api.py`); the boundary tests; the benchmark and its report. Default model `qwen3:8b`, fallback `qwen3:4b-instruct`, an 8,192-token context in both modes. No tool runs yet. |
| A2 | The assistant answers. Names first (`services/entities.py`, `assistant/names.py`): an ambiguous name is asked about before the model runs. The lab's read tools over the services (`assistant/lab_tools.py`); the executor (`executor.py`), which refuses an id the lab does not hold; the loop (`orchestrator.py`) within each mode's calls, time and context; the answer checker (`checker.py`): a figure no result holds, a chance where none was given, a verdict, a claim to have saved something or a citation of nothing is sent back once, then cut out. Current information (`pipelines/current.py` into `data/current.sqlite`, read by `services/current.py`; `fol current refresh`, `fol current status`) and its tools (`current_tools.py`). The web (`providers/web.py`, `processing/web.py`, `pipelines/web.py`, `web_tools.py`): Ollama's web search with the user's own key, and pages - search results and pasted links - read by id after every check. The end-to-end evaluation (`scripts/evaluate_answers.py`, [ASSISTANT_ANSWERS.md](research/ASSISTANT_ANSWERS.md)). The forecasting tools are A4's; the page is A3's. |
| A3 | The AI Research page (`apps/workbench/wb/views/research.py`, in the workbench's Ask group): the assistant's state, web search's and each current source's; Quick and Deep; a question answered in the background (`assistant.api.Job`) with its steps shown and a stop; each answer with its kind, its text, notes and limits, its results' rows and charts, its evidence and its workings; a question back answered by a click; failure said on the page, never as an error. The conversation lasts the session. |
| A4 | The forecasting tools (`assistant/model_tools.py`): `player_value` (a player's seasons and projection, a season's leaders, the projections, where an impact comes from, roles beside how often they carry over, value for money against the user's contract file, the model's test), `roster_fit` (a team's or built roster's profile as description, the evidence, the champions), `postseason_outlook` (a team or roster as a team of its strength, any net rating, a season's bracket and every team's chances, the model's record) and `simulate_scenario` (a team or roster before and after the user's assumptions). Every modeled figure goes out with its error: a chance with its 95% interval and the season model's record read both ways; a projection with how far projections of players that well known have missed; a scenario with the interval of the seasons drawn and the wins test. Each result cites the model files it read, by revision. The document index (`domain/documents.py`, `config/documents.py`, `storage/documents.py`, `services/documents.py`, `assistant/document_tools.py`): `research_docs` searches the lab's documents with SQLite FTS5, built in memory for each search, and cites each section by file and heading. |
| A5 | Roster proposals (`domain/proposals.py`, `services/proposals.py`, `assistant/proposal_tools.py`). `optimize_roster` runs the optimizer with what the user asked for - a budget, a roster size, groups, roles, players locked in or left out - and nothing else. Each roster found (2-4, each differing from the others by at least three players) becomes a proposal: its players and where each would start, their salaries from the contract file, the payroll and what is left under the budget, the projected net rating with the value model's typical miss, what was asked for, and what it rests on (the build, the value model's revision, the contract file's date). The AI Research page shows each under the answer with a *Save approved roster* button; `assistant.api.save_proposal` refuses, in plain sentences, if anything the proposal rests on has changed, and otherwise saves it in one transaction (`RosterRepository.create_with_players`) with its fingerprint in the roster's notes, so that a second press finds it. The Roster Optimizer page's save uses the same transaction. Proposals last the session, with their answer. A third test database, `priced`, gives every projected player an invented salary. |
| A6 | Workspaces (`domain/tables/research.py`, `domain/research.py`, `storage/research.py`, `services/workspaces.py`): named research kept in `data/assistant/assistant.sqlite`, which no build touches - versioned, backed up before an upgrade, and refused when it is not the store or comes from a later lab. A workspace keeps every question and its whole answer as it came back, with the data build and value model it read; findings the user bookmarks, as copies; the rosters its answers proposed, until saved or declined, and every press; notes - the user's, and summaries the local model writes on request - given to the model as background, never evidence; and a focus (season, phase, team, roster) its questions are about when they name nothing. A follow-up reads only its own workspace's conversation under way; a "he" or "they" with nothing to mean is asked about. An old answer says when the data or the model has changed since, or when the current information or web pages it read may have, and can be asked again beside itself. Workspaces are made, renamed, archived, restored, cleared, deleted, and exported as Markdown or JSON. *Ask AI about this* on eight pages asks about what the page shows, in the open workspace, without touching the sidebar (`apps/workbench/wb/ask.py`; the answer drawing shared in `wb/answers.py`). Every save places the starters at positions they are listed at (`domain/lineup.py`). |
| A7 | Wider sources and the contract-update review. News from the feeds the source register allows - Hoops Rumors' main, transactions and team feeds (`configs/assistant.yaml`, `news:`), the user's choice after ESPN, Yahoo and CBS Sports turned AI agents away, NBC Sports' terms barred automated tools and Wikipedia's robots barred its API - fetched with every check a page passes (`WebProvider.fetch_feed`), read by `processing/feeds.py` (RSS or Atom, no declared entities), each article once, kept in `data/current.sqlite` (`news_items`) for 120 days. The `moves_and_rumors` tool dates every headline and gives each a source id to read; a search result says the date its address shows, or that it shows none. The search-quality evaluation (`assistant/search_quality.py`, `scripts/evaluate_search.py`, `docs/research/SEARCH_QUALITY.md`). The contract-update review: `pipelines/contract_review.py` compares a candidate file with the one in use and flags what to check, storing nothing (`fol contracts preview`, Contract Explorer's *Check a new file*); `contract_updates` lists the moves since the contract file's date beside what the file holds. At the A6 review's wish: starters by projected impact among the lineups that fit, and places checked for what they rank. |
| A8 | Experiment proposals for the lab's models, never applied (`domain/experiments.py`, `config/experiments.py` and `configs/experiments.yaml`, `services/experiments.py`, `assistant/experiment_tools.py`). Only when asked, `propose_experiment` drafts one for one of the four tested models - player value, postseason, simulator, roster fit: the assistant's idea in words, without figures, beside the lab's test - what a change must beat, from the model's file; how it is tested and what was tried, quoted from its decision; the leakage to rule out and the steps of a future milestone. The page shows it under the answer, kept apart from the idea, to keep in the workspace (`research_experiments`, the research store's version 2) or download as a document. The evaluation of drafting (`assistant/experiment_evaluation.py`, `scripts/evaluate_experiments.py`, `docs/research/EXPERIMENT_PROPOSALS.md`). |

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
   number in the text with what the model was given, as displayed (dates and years are
   labels, not figures); it also catches a chance where no result is one, a verdict, a
   claim to have saved or changed something, and a citation of a result no tool returned.
   Each is sent back once for repair, then cut with its sentence, and the answer is marked
   *qualified*. A model that says it will look something up and stops, or cites a result
   it never fetched, is asked once to make the call.
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
web; may fill a cache); **draft** (a proposal for the user to review, kept only by their click). There is no
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
| `moves_and_rumors` | net | team_id, player_id, moves_only, days | `pipelines.current` (the news feeds, when due) and `CurrentDataService.news()`: dated headlines, each a source to read | A7 |
| `contract_updates` | net | team_id, player_id | `CurrentDataService.transactions()` and `.news()` since `LabStatus.contract_as_of`, beside `ContractService.salaries()`; nothing imported | A7 |
| `web_search` | net | query, max_results | `providers.web` (Ollama web search) | A2 |
| `read_source` | net | source_id | `providers.web`: a source id from search results, a feed, or the user's message - never a URL the model wrote | A2 |
| `player_value` | read | view (player, season_leaders, projections, breakdown, roles, value_for_money, model_evidence), player_id, season | `ValueService.player()`, `.season()`, `.projections()`, `.parts()`, `.roles()`, `.for_money()`, `.card()`, `.status()` | A4 |
| `roster_fit` | read | team_id + season, or roster_id; view (profile, evidence, champions) | `FitService.team()`, `.roster()`, `.evidence()`, `.champions()`, `.status()` - description; no correction while the evidence is not usable | A4 |
| `postseason_outlook` | read | view (team, roster, strength, bracket, season_odds, model_record), team_id, season, roster_id, net_rating, top_players | `PostseasonService.team()`, `.roster()`, `.outlook()`, `.bracket()`, `.season_odds()`, `.series()`, `.model()`, `.status()` | A4 |
| `simulate_scenario` | compute | subject (team, roster), subject_id, add/remove player ids, per-player assumptions, availability, development | `SimulatorService.default_scenario()`, `.run(Scenario)`, `.status()` - arguments validated into `domain.scenario.Scenario` | A4 |
| `research_docs` | read | query | new full-text index (SQLite FTS5, built in memory for each search) over `docs/` - less the generated metric glossary and data dictionary, which `metric_definition` reads at the source, and the assistant's own recorded answers - cited by file and heading | A4 |
| `optimize_roster` | compute | budget mode, budget in millions, roster size, group and role minimums, locked and excluded ids, options (2-4) | `OptimizerService.defaults()` (the seasons and the roster size only), `.solve(OptimizerRequest)`, then `ProposalService.from_report()`: each roster found becomes a proposal kept with the answer | A5 |
| `propose_experiment` | draft | model (a tested one), name, observation, hypothesis, change, failure modes - in words, no figures | `ExperimentService.draft()`: the idea beside `ExperimentService.plan()` - the model file's figures, the decision's sections, `configs/experiments.yaml`; the proposal travels with the answer | A8 |

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
  is missing is said). A question back to the user and a refusal are answers too. The
  outcome is code's call, from the results and the words: a result that holds nothing new
  but was checked - no game played yet, no report published - carries a limit and makes
  the answer qualified; a lab table without the season makes it insufficient; an answer
  that says it cannot is insufficient without a figure and qualified with one; an answer to
  a question that asks for a verdict is qualified, with a note, since the verdict is the
  part the lab never gives (A4).
- **The lab's language.** A benchmark is a frequency among past teams, with its count and
  interval, never a team's chance. A chance comes only from the postseason model or the
  simulator, with its 95% interval and the model's record. Ratings over a span carry "≈".
  Eras are compared within their own seasons. No verdicts ("a contender"), no
  recommendations ("should sign"), no single "best" roster; trade-offs instead. League
  statistics are credited to NBA.com. A roster from the optimizer is a hypothetical
  affordable roster, not a legal acquisition plan.

## Charts and tables

Every result's rows are on the page, with a CSV. A tool attaches the chart its rows call
for (`domain.assistant.Chart`): a team's or a player's seasons as a line, a player's season
as percentile bars, players compared as dots on one scale, every team's net rating as
bars, a benchmark's shares with their 95% intervals. The page draws it with `wb/charts.py`
through `components.chart`, so it has its table view and exports, and declines one the
house rules would refuse (more players than its colours can tell apart), saying so. The
model plays no part in a chart: the specification first had it ask for one, and A3 left
that out (decision 0018). No code, SQL or chart definition from the model is run.

## Current information

| Source | Fetched again when older than | Notes |
| --- | --- | --- |
| The season in progress's league game logs (stats.nba.com) | 60 minutes | Regular season, play-in and playoffs, through the existing provider; the snapshots go to the raw store, where the next build finds them. A game the build already holds is marked. Preseason games are not fetched, and the tool says so. |
| Injury report (official PDF) | 30 minutes | The latest report of the last four quarter hours, found by its published name. A player not listed is "not on the report", never "healthy"; a team not yet submitted is said so. Times are the league's, Eastern. |
| Transactions (stats.nba.com player movement) | 3 hours | Each with the league's date; a move dated after the lab's build is flagged, since the lab's rosters do not show it. Kept unchanged when the file has not changed. |

The intervals are starting values in `configs/assistant.yaml` (`current:`), to be set from
how often each source changes in season. A question fetches only what is due; a source
that fails is logged and its last copy used, dated. Everything fetched is kept in
`data/current.sqlite`, apart from the lab's database: a refresh never touches what a build
made, and nothing refits a model. `fol current refresh` fetches by hand and `fol current
status` shows each source's state; so do the AI Research page's badges and its *Fetch
current information* button. Opening the page fetches nothing (decision 0018, A3).
`fol refresh` stays a separate, explicit step.

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
- **Fetching.** http and https on the standard ports only; no credentials in an address;
  every address the name resolves to, after every redirect, must be public (no loopback,
  private, link-local, shared or reserved ranges), and so must the one connected to; 2 MB
  and 20 seconds a page; no cookies or credentials sent; robots.txt honoured for the lab and
  for AI agents (ChatGPT-User, Claude-User, Perplexity-User, GPTBot, ClaudeBot,
  PerplexityBot) - rules that cannot be read allow nothing; no login, payment or bot-check
  workarounds (401, 402, 403, 407, 429, 451 end it). Sports Reference's sites and Spotrac
  are refused, and so is nba.com: the league's data comes through the lab's own sources. A
  search result from a refused site is left out, and the result says so.
- **Budgets.** A question may search the web once and read two pages in Quick mode, four
  and eight in Deep; a page read twice is fetched once.
- **Local only.** See decision 0018: loopback model host, remote models refused, no keys
  in configuration. The web search key is read by the web provider alone, from the
  environment variable `FOL_OLLAMA_API_KEY` or that line of the project's git-ignored
  `.env`, sent only to ollama.com, and never shown, logged or put in an error. Never
  `OLLAMA_API_KEY`, which Ollama's own tools pick up by themselves. Without a key,
  `web_search` says it is not set up and pasted links can still be read.
