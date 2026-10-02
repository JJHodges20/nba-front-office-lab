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
| 3 | Contracts and salary-cap data | Contracts, season rules, cap-normalised salaries | Done (import path; no contract file supplied yet) |
| 4 | Database and repositories | Persistent storage and clean data-access boundaries | Done |
| 5 | Player analytics | Reusable player calculations and comparison tools | Done |
| 6 | Team analytics | Team efficiency, point differential, pace, historical outcomes | Done |
| 7 | Front Office UI foundation | Navigation, filters, player/team explorers, Team Builder | Done |
| 8 | Historical contender analysis | Playoff/championship benchmark research | Done (team level; roster make-up and payroll await player and contract history) |
| 9 | Player value engine | Validated value features, surplus value, archetypes | Not started |
| 10 | Roster fit engine | Fit, redundancy, role coverage, weaknesses | Not started |
| 11 | Roster optimizer | Budget and roster constraints, multiple candidate rosters | Not started |
| 12 | Playoff/championship model | Calibrated postseason probability models | Not started |
| 13 | Simulator | Scenario and Monte Carlo analysis | Not started |
| 14 | Full-system audit | Architecture, leakage, tests, UI, documentation, performance | Not started |

Milestones 1-7 make up **v1.0 - League and Roster Analytics**, the first release target.
All seven are done; one acceptance criterion below stays open until a contract file is
supplied.

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
- [ ] Player contracts and season-specific cap information are available in the workspace.
  **Open.** Cap rules for 2024-25 to 2026-27 are configured from cited sources and shown.
  Contracts have a tested import path and every view that uses them, but the workspace
  holds none: no source permits collecting them automatically, so they come from a file
  the user supplies ([CONTRACT_DATA.md](CONTRACT_DATA.md)). Importing one closes this.
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
  The history views describe and say so; nothing scores, ranks or projects a roster.

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
