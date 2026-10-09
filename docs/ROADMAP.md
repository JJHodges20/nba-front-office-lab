# Roadmap and Milestone Status

The full plan is [NBA_Front_Office_Lab_Roadmap.pdf](roadmap/NBA_Front_Office_Lab_Roadmap.pdf).
This page tracks progress against it.

## Vision

A clean front-office workspace that can identify high-value NBA players, analyse
historical team success, construct rosters under financial constraints, and eventually
estimate playoff and championship outcomes - without reducing roster building to
points-per-dollar.

> **Core principle.** Do not ask only "which players have the best stats for the least
> money?" Ask "which combination of players creates the most championship-relevant
> basketball value under our financial constraints?"

## Versions

| Version | Focus | Primary outcome |
| --- | --- | --- |
| V0 | Project Foundation | Architecture, data contracts, season rules, testing foundation |
| V1 | NBA Analytics Workspace | Current player/team stats, contracts, manual roster builder, clean UI |
| V2 | Winning Benchmarks | Historical playoff and championship thresholds, era-aware analysis |
| V3 | Player Value Engine | Basketball value, contract efficiency, surplus value, archetypes |
| V4 | Roster Fit Engine | Complementary skills, redundancy, weaknesses, role coverage |
| V5 | Budget Roster Optimizer | Strong rosters subject to payroll and roster constraints |
| V6 | Contender Probability Model | Playoff-round and championship probabilities |
| V7 | Scenario Simulator | What-if signings, trades, injuries, development, Monte Carlo seasons |
| V8 | Advanced Front Office Intelligence | Trades, aging curves, draft value, multi-year planning |

## Milestones

| # | Milestone | Deliverable | Status |
| --- | --- | --- | --- |
| 1 | Repository and architecture | Package structure, configuration, test foundation, documentation | Done |
| 2 | NBA data ingestion | Players, teams, games, standings, advanced statistics | Done |
| 3 | Contracts and salary-cap data | Contracts, season rules, cap-normalised salaries | Done (the user's contract file - the MrBridge salary dataset, 2015-16 to 2026-27 - imported and built in on 2026-10-05; cap shares where a season's rules are configured, 2024-25 on) |
| 4 | Database and repositories | Persistent storage and clean data-access boundaries | Done |
| 5 | Player analytics | Reusable player calculations and comparison tools | Done |
| 6 | Team analytics | Team efficiency, point differential, pace, historical outcomes | Done |
| 7 | Front Office UI foundation | Navigation, filters, player/team explorers, Team Builder | Done |
| 8 | Historical contender analysis | Playoff/championship benchmark research | Done (team level; payroll history is in the database from 2015-16, not yet in the research; where the champions' rosters stood is in the roster fit research) |
| 9 | Player value engine | Validated value features, surplus value, archetypes | Done (surplus value reads the imported contract file) |
| 10 | Roster fit engine | Fit, redundancy, role coverage, weaknesses | Done (fit is description; the evidence supports no correction to the sum of the parts) |
| 11 | Roster optimizer | Budget and roster constraints, multiple candidate rosters | Done (prices its pool from the imported 2026-27 salaries) |
| 12 | Playoff/championship model | Calibrated postseason probability models | Done (tested out of sample from 2006-07; chances shown with intervals and the evidence) |
| 13 | Simulator | Scenario and Monte Carlo analysis | Done (seasons drawn from tested parts; the field is not modelled) |
| 14 | Full-system audit | Architecture, leakage, tests, UI, documentation, performance | Done ([AUDIT.md](AUDIT.md): every pass with what was found, changed and left) |

Milestones 1-7 make up **v1.0 - League and Roster Analytics**, the first release target.
All seven are done, and the last acceptance criterion below closed on 2026-10-05 when the
user's contract file was imported. Milestone 8 is the roadmap's version 2 (*Winning Benchmarks*), milestone 9 its
version 3 (*Player Value Engine*), milestone 10 its version 4 (*Roster Fit Engine*),
milestone 11 its version 5 (*Budget Roster Optimizer*), milestone 12 its version 6
(*Contender Probability Model*) and milestone 13 its version 7 (*Scenario Simulator*);
the surplus-value half of version 3 and the optimizer's pool both read the same file.
With milestone 12 the lab shows its first forecast: a chance of each postseason stage,
with its interval, from a model validated on seasons it had not seen
([decisions/0014](decisions/0014-postseason-model.md)). Milestone 13 lays a user's
assumptions over a roster and draws thousands of seasons for it from those tested parts,
before and after a change ([decisions/0015](decisions/0015-simulator.md)). Milestone 14
audits the whole: it found every test window clean and the forecasts' error understated,
and the forecasts now carry the error of a test that projected minutes too
([AUDIT.md](AUDIT.md), [decisions/0016](decisions/0016-audit.md)).

## AI Research Assistant (A0-A9)

An assistant that answers questions in plain language from the lab's services, current
information and public reporting, on a local language model, with every figure traced to
its source. The plan is the user's *NBA Front Office Lab AI Research Assistant* roadmap; the
architecture is [decision 0018](decisions/0018-ai-research-assistant.md), the design
[AI_ASSISTANT_SPEC.md](AI_ASSISTANT_SPEC.md), the measuring [AI_EVALUATION.md](AI_EVALUATION.md).
Lettered so as not to clash with the milestones above; each passes the same gate.

| # | Milestone | Deliverable | Status |
| --- | --- | --- | --- |
| A0 | Audit, decisions, evaluation cases | Decision 0018, the specification, the evaluation design, 59 frozen cases that check their own figures, the source register | Done (2026-10-09) |
| A1 | Local model and benchmark | The Ollama adapter (loopback only, remote models refused), the `assistant` layer and its boundary rules, the typed tool registry, the routing benchmark on this machine's GPU, a default and fallback model | Done (2026-10-09: `qwen3:8b`, fallback `qwen3:4b-instruct`; [ASSISTANT_MODELS.md](research/ASSISTANT_MODELS.md)) |
| A2 | Tools, evidence, current data, the web | Name resolution, the read tools, the evidence record and answer checker, game logs, the injury report and transactions, web search and pasted links | Planned |
| A3 | The AI Research page | Quick and Deep, the evidence panel, tables and charts, cancel, failure states | Planned |
| A4 | Forecasting tools | Value, fit, postseason and simulator tools; the document index | Planned |
| A5 | Roster proposals | 2-4 options as drafts; the approved save, atomic and checked against its fingerprint | Planned |
| A6 | Workspaces | Named, persistent research; asking from any page; export and delete | Planned |
| A7 | Wider sources | More feeds, search quality, contract-update review | Planned |
| A8 | Research proposals | Experiments for the models, written up, never applied | Planned |
| A9 | Release audit | Every test, the evaluation, failure and offline runs, documentation | Planned |

## Completion gate for every milestone

- Targeted automated tests pass.
- Relevant data-quality checks pass.
- The UI workflow is visually reviewed if the milestone affects the interface.
- No unrelated architectural boundary was weakened.
- Changes are documented and committed before the next milestone begins.

Evidence for each gate is recorded in [DEVELOPMENT_LOG.md](DEVELOPMENT_LOG.md).

## Version 1.0 acceptance criteria

Assessed at the milestone 7 gate (2026-10-01).

- [x] Current player and team statistics can be refreshed and inspected.
  `fol refresh` fetches what is new and rebuilds; the workbench shows it.
- [x] Player contracts and season-specific cap information are available in the workspace.
  Closed 2026-10-05. Cap rules for 2024-25 to 2026-27 are configured from cited sources
  and shown. No source permits collecting contracts automatically, so they come from a
  file the user supplies ([CONTRACT_DATA.md](CONTRACT_DATA.md)): the MrBridge salary
  dataset (HoopsHype's public salaries, 2015-16 to 2026-27) is imported and built in, and
  every salary, payroll, cap and value-for-money view and the optimizer read it. Cap shares
  are blank for seasons before 2024-25 until their rules are configured.
- [x] Player and team profiles expose consistent, tested metrics.
  One catalog per subject, one formula per metric, generated glossary ([METRICS.md](METRICS.md)).
- [x] The workspace compares points scored/allowed and possession-adjusted efficiency.
  League Overview and Team Explorer; ratings over a span of games are marked as estimates.
- [x] A clean Player Explorer and Team Explorer are usable from the UI.
- [x] The manual Team Builder tracks roster membership, payroll, cap percentage, and aggregated team indicators.
  Payroll and cap percentage need salaries: from the contract file, or typed in per
  player as the user's own assumption.
- [x] Data Health displays freshness, failed updates, missing data, and source status.
- [x] Historical team data is stored in a way that supports Version 2 benchmark research.
  Every team-season since 1996-97 with league-relative ratings, and every playoff series.
- [x] All major analytics functions have automated tests.
- [x] No predictive championship claim is presented before the historical benchmark and modeling stages exist.
  True at the milestone 7 gate: the history views described and said so, and nothing
  scored, ranked or projected a roster. The models that do came in milestones 9 to 13,
  each with its test on seasons it had not seen.

## Standing cautions from the roadmap

- Any composite player score must be empirically validated; weights are not objective
  because they produce a tidy 0-100 number.
- Avoid magic thresholds ("50 wins makes a contender"); report historical frequencies
  and conditional probabilities instead.
- Raw scoring from different eras is not comparable without league-relative context.
- There is one champion a season: postseason models must handle class imbalance, be
  evaluated out of sample, be calibrated, and show their uncertainty.
- Optimiser weights are assumptions: show several strong rosters, never one "best".
- Performance models, value scores, optimiser outputs and championship probabilities are
  analytical estimates and are never presented as guarantees.
