# Development Log

One entry per milestone: what was built, what was decided, and the evidence for the
completion gate. Newest first.

## Milestone 9 - Player value engine (2026-10-04)

**Built**

- Thirty seasons of players. `player_history_start` in the settings; player season lines
  (totals and advanced) for every season since 1996-97 through the rate-limited provider,
  with game logs and rosters still kept for recent seasons only; and
  `analytics/players.py::team_minutes`, which splits a traded player's published minutes
  between teams by the logged minutes.
- A `modeling` layer, importing `domain` and `analytics` only. `modeling/value`:
  `features.py` (fifteen features in eight components, per 100 on-court possessions and
  against the league), `pooling.py` (earlier seasons pooled by minutes at weights 1, ½
  and ¼; reliability against 750 minutes of ballast), `design.py` (the terms an estimate
  is a weighted sum of, defined once for fitting and scoring), `estimate.py` (offense and
  defense fitted separately by least squares to the teams' relative ratings, every
  player's estimate built from earlier seasons only; an expanding-window test from
  2006-07 against six simpler methods; one ablation per component; intervals from
  resampling whole seasons), `scoring.py` (season impact centred so the league's average
  minute is zero, the projection into the next season, wins above replacement),
  `availability.py` (projected share of team minutes from three seasons and age, tested
  against "the same as last season"), `wins.py` (wins per point of net rating from the
  standings, by season), `market.py` (a line through salary and wins; surplus value) and
  `catalog.py` (the value metrics).
- `domain/value_model.py`: the specification and the fitted model as frozen pydantic
  models - every weight with its interval, the test, the baselines, the ablations, the
  backtest, replacement level, projected minutes. `configs/models/player_value.yaml` is
  edited by people; `configs/models/player_value.json` is written by
  `fol value fit --write` and read by every build. `fol value show`, and
  `fol value report --write` for [research/PLAYER_VALUE.md](research/PLAYER_VALUE.md).
- `modeling/archetypes.py` and `configs/archetypes.yaml`: eight roles as rules - the
  weakest percentile on a role's measures among the players it is open to, within the
  season - the `player_archetypes` table, and how well each role carries over from one
  season to the next.
- `pipelines/value.py`: a build applies the model on file and the rules and never fits;
  it notes when there is no model, when seasons have finished since it was fitted, and
  when roles cannot be scored.
- `services/value.py` - `ValueService`: status, a season's players with their ranks,
  projections, a player's history, the parts of a season's impact, roles, who fills a
  role, the role summary with persistence, value for money, the model card - and
  `services/value_report.py`. Value columns and roles in the player views; value gaps in
  Data Health; the glossary grows to 113 metrics.
- The **Player Value** page: Season, Projections, Roles, Value for money, The model. The
  Modeled tag. A role column and "Roles filled" on the Player Explorer. `charts.scatter`
  draws a trend line.
- Quality checks, 54 from 45: three on player lines against the game logs and the team's
  totals, within tolerances the source's own rounding allows (the exact comparisons are
  now warnings), three on the value table (the parts add up to the impact, every regular
  season is valued, the minutes-weighted average impact is zero) and one on roles (a
  player who fills a role has exactly one primary role, among those filled).

**Decisions** ([0010](decisions/0010-player-value.md), [0011](decisions/0011-archetypes.md))

- Value is a fitted model, not a composite with chosen weights. The weights are asked of
  thirty seasons of team results, every estimate is built from seasons before the one
  predicted, and a part of the model keeps its place only if leaving it out costs
  accuracy on seasons the model had not seen. What was tried and left out - playoff
  minutes among it - is tabled in the decision.
- A fitted model is a file written on request. A build applies it and never fits one,
  rows carry the revision, and the page, the report and Data Health say when the model
  is behind the data or ahead of the build.
- Impact is centred so the league's average minute is worth nothing; offense and defense
  are fitted separately and add up; a replacement player is the impact of players beyond
  each team's top ten; wins use the season's own wins per point.
- The price of a win is read off the contracts on file, never a published figure; with
  few contracts the line is rough and says how many it rests on. Nothing is valued
  beyond one season ahead.
- Archetypes are rules in configuration, scored by the weakest percentile within a
  season. Nothing about them is fitted; what is measured instead is how often a role
  carries over to the next season. Tracking data was left out: recent seasons only.

**What the research says** (revision 1, fitted on 1996-97 to 2025-26; the document has the rest)

- On 600 team-seasons from 2006-07 on, each predicted from earlier seasons only, the model
  misses a team's net rating by 3.01 points (RMSE; offense 2.05, defense 2.14). The
  league's player impact estimate misses by 3.38, on-court net rating by 3.54,
  plus-minus by 3.55, last season regressed by 3.97, last season as it was by 4.41 and
  the league average by 4.92 - every difference clear of zero.
- Leaving out the team results costs most (RMSE +0.16), then the minutes prior for the
  unproven part of an estimate (+0.11); on-court results, scoring efficiency and age each
  cost about +0.05, all clear of zero. Creation, defensive activity, rebounding, spacing
  and ball security cannot be told from adding nothing on this evidence; they stay
  because the box score as a whole is missed when it goes, and the document says no
  single weight in them should be leaned on.
- Replacement level is -2.32 points per 100 possessions. A team's net rating is 1.23 times
  the sum of its players' same-season impacts (correlation 0.96): impacts are cautious by
  construction. A point of net rating was worth 2.57 wins in 1996-97 and 2.23 in 2025-26.
- Projected minutes miss by 0.130 of a team's minutes on 13,675 player-seasons, against
  0.143 for assuming last season's share.
- Every role is filled again several times more often than by anyone at all: the primary
  creator 64% against 6%; the connector least, 38% against 10%.

**Verification**

- The model is tested on an invented league (`tests/league.py`) whose team ratings are
  planted from chosen weights, against a reference that computes the model with plain
  loops and shares no code with it (`tests/value_reference.py`): every weight is
  recovered on both sides of the ball when nothing is left to luck; with luck added the
  intervals widen and still hold the truth; a season's prediction does not move when its
  own results are changed; the baselines, replacement level, centring, wins per point and
  projected minutes are worked by hand; the first season is only ever history; unfinished
  seasons and incomplete teams are left out. Archetypes are tested on hand-made players
  (percentiles and ties, groups by position and height, tiers, the primary role, missing
  measures, persistence) and on the invented league with the shipped rules.
- Services and pages are checked against the invented league valued by the planted model
  and against the fixture store valued by the model the lab ships; the quality checks
  against a scored league with each fault planted in turn.
- Mutation spot-check: 150 planted bugs across the features, the fit, scoring, projected
  minutes, the market, the pipeline, the checks, the services, the report, the roles and
  the pages. 140 were caught at once. Eight exposed gaps - playoff lines slipping into the
  features, a backtest season seeing its own results, the wrong season's age, projection
  rows in a season table, salaries with no value in the market, the money table ignoring
  the team filter, the Modeled tag on every view, the three-point prior taking the whole
  record's league rather than the season's - each closed with a test and then caught.
  One mutant was equivalent to the code, which was simplified instead; one mutation had
  missed its line and was caught once aimed.
- The page was looked at in both themes, every tab, on the real data and on a demo lab
  with invented contracts, and clicked through in a browser: rows of the season table and
  of a role's table, ordering, the position and team filters, the tabs, the weights'
  side, roles across seasons, the Player Explorer's role column. Looking changed a
  duplicated export key, a model tab that broke without a test on file, and "1 players".
- The sweep runs the new page from two starting states without an exception.

**Found on the way**

- `_team_baselines` looked a team's last season up only among the rows it could fit on,
  so a baseline could miss a season that was on record. Caught by the tests before it
  reached the data.
- In the older seasons a player's published season line, the game logs and the team's
  totals disagree by the source's own rounding and by games a log lacks: three more rows
  in [0003](decisions/0003-source-quirks.md), the exact checks demoted to warnings, and
  tolerance checks as the errors.
- `fol build` and `fol check` answered a missing configuration file with a traceback;
  now a plain error.
- A build that empties a modeled table is not refused, unlike one that empties a league
  table: the league tables are whole, and a note says what to run.

**Gate**

| Check | Result |
| --- | --- |
| Automated tests | 2,400 passed, none skipped; a little over three minutes with `pytest -n auto` |
| Test sensitivity | 150 planted bugs: 140 caught at once; 8 gaps closed with tests and then caught; 1 equivalent mutant removed by simplifying the code; 1 misaimed mutation caught once aimed |
| Data-quality checks | 54 checks on the real data (build 11): 0 errors, 7 warnings - the three carried from milestone 8, and four where the older seasons' player lines, game logs and team totals disagree within the tolerances the error-level checks hold |
| UI review | The new page in both themes, every tab, on the real data and on a demo lab with contracts; clicked through in a browser; the Player Explorer re-checked with its role column |
| Architectural boundaries | `tests/architecture` passes. The new `modeling` layer imports `domain` and `analytics` only; `pipelines` and `services` consume it; the page computes nothing; fitting happens in one command and nowhere else |
| Lint | `ruff check` and `ruff format --check` clean |

**Open items carried forward**

- Surplus value needs the contract file the user has yet to supply; the market line is
  fitted to whatever is on file and says how many contracts that is.
- Defense is the model's weak side: the box score records little of it, so the model
  leans on the team's results shared among the players who were there. Tracking data
  would help and was left out (recent seasons only).
- The model is fitted on seasons to 2025-26 and must be fitted again when 2026-27 ends;
  the page, the report and Data Health say so when it is behind.
- The research documents are regenerated at gates, not checked by tests.

## Milestone 8 - Historical contender analysis (2026-10-01)

**Built**

- `analytics/benchmarks.py`: the research. A team-season frame for completed seasons
  (wins per 82 games, six nested stages from "reached the postseason" to "won the
  championship", league rank within the season on every metric); how often the teams
  in each band of a measure reached each stage, with Wilson intervals; the spread of
  each stage's teams by value and by league rank; how many ranked near the top of the
  league, at one end or both; and how well each metric alone orders the teams that
  reached a stage, measured within seasons with intervals from resampling seasons.
- `domain/eras.py`, `config/eras.py`, `configs/eras.yaml`: named spans of seasons - all,
  the last five and ten, the modern era, the Play-In era - each with its reason, and
  any span chosen on the spot.
- `services/benchmarks.py`: `BenchmarkService` - an era as it falls on the data, the
  research dataset, stage rates by record, net rating, point differential, relative
  ratings or seed (for every team or among those that reached an earlier stage),
  profiles with the teams at the extremes named, rank counts, separation against the
  league or against a narrower field, and headline figures.
- `fol benchmarks --write`: `docs/research/BENCHMARKS.md`, the research as a document
  generated from the database, sentences included.
- The **Winning Benchmarks** page of the workbench, with two new chart builders
  (columns with intervals; rows of a dot on an interval with an inner band). The
  "champions and the field" view moved there from the Analytics Lab.
- A quality check for tied places in the conference standings, and a test helper that
  reads what a chart on a page actually drew.

**Decisions** ([0009](decisions/0009-benchmarks.md))

- A benchmark is a frequency with its count and its interval, never a threshold. A
  band is a way of grouping; its width can be changed.
- Seasons are made comparable by wins per 82 games, league rank within the season, and
  comparing teams only with teams of their own season.
- Separation is within-season concordance, one metric at a time, with an interval from
  resampling whole seasons because the teams of a season depend on each other.
- Eras are configuration; "the modern era" is labelled a convention.
- The research document is generated, never typed.
- History is not applied to a current team. That is a forecast and waits for a model.

**What the research says** (all thirty seasons; the document has the rest)

- No team below 50 wins per 82 games won the championship: 0 of 643, which by the
  interval is consistent with a long-run rate of up to 0.6%. Of the teams at 50 to 55,
  6 of 121 did (2% to 10%).
- All thirty champions ranked in the league's top ten in net rating that season, 27 in
  the top five, and 23 in the top ten at both ends. All were seeded first to third.
- Against the rest of the league, record and net rating put a champion ahead of a
  same-season team about 93% of the time; defensive rating 85% (79% to 90%) and
  offensive rating 83% (77% to 88%) - no difference worth the name. Shooting at both
  ends follows; turnovers, offensive rebounding and free-throw rate separate
  champions from the rest little or not at all, and pace not at all (50%).
- Against the teams they actually had to beat the figures fall: among playoff teams,
  net rating favours the team that won a series 81% of the time, and among teams that
  won a series it favours the conference finalist 68% of the time.

**Verification**

- Analytics are tested on hand-built histories with known answers - the Wilson interval
  against worked values and at both ends for every sample size to 200, band edges,
  nested stages, ties counting half, a lower-is-better metric, a high-scoring and a
  low-scoring era that only a within-season comparison gets right, an interval whose
  width is checked against the exact resampling distribution - and on the three
  fixture seasons.
- On the real database every season has sixteen playoff teams, eight, four, two and
  one at the later stages; the stage counts add up to 480, 240, 120, 60 and 30.
- The page was looked at in both themes and at a laptop width, and its controls were
  clicked through in a browser: the era switch, a span of chosen seasons, the stage,
  the measure and the width of a band, "among", the field of a comparison. Looking
  changed the rank chart (full width, the best rank labelled), the separation chart
  (ordered by value, axis fitted to the data and its reference line, a clipped label),
  the tables beside them (cut off; now full width), and a caption that did not apply
  to seeds.
- The sweep runs the page from two starting states: 148 page runs without an exception.

**Found on the way**

- Through 2000-01 the league's standings leave equal records on the same place: nine
  conference standings have two teams on one place. Kept as published, reported by a
  new warning-level check, and noted wherever seeds are used.
- `fol benchmarks` on a project with no database would have created an empty one;
  it now checks first, as `fol db` does.

**Gate**

| Check | Result |
| --- | --- |
| Automated tests | 1,907 passed, none skipped; under three minutes with `pytest -n auto` |
| Test sensitivity | 68 planted bugs in the research, the eras, the report, the new charts, the page and the command: 63 caught at once; 5 exposed gaps in the tests (two interval end points, two headline counts, a shared extreme, a missing share in the report), each closed and then caught |
| Data-quality checks | 45 checks on the real data: 0 errors, 3 standing warnings (the two known ones and the tied standings) |
| UI review | The new page in both themes and at 1366 pixels, every tab; controls clicked through in a browser; the Analytics Lab re-checked after losing a tab |
| Architectural boundaries | `tests/architecture` passes. Research formulas are in `analytics`, eras in `domain` and `config`, wording and assembly in `services`; the page computes nothing |
| Lint | `ruff check` and `ruff format --check` clean |

**Open items carried forward**

- Roster make-up and payroll distribution of contenders - part of the roadmap's first
  research question - cannot be measured: player detail covers recent seasons only and
  there is no contract history. Player history must be extended before the player
  value work (milestone 9); payroll needs contract data the user has yet to supply.
- Benchmarks use regular-season figures only.
- The research document depends on the database, so no test can tell when the
  committed copy is stale; it is regenerated at each milestone gate.

## Milestone 7 - Front Office UI foundation (2026-10-01)

**Built**

- `apps/workbench`: the workbench, a Streamlit app of seven pages - League Overview,
  Player Explorer, Team Explorer, Contract Explorer, Analytics Lab, Team Builder, Data
  Health - inside one frame: navigation, global filters (season, phase, team, player,
  comparison window) that hold from page to page, and the data status on every page.
- `wb/charts.py`: ten chart builders (scatter, diverging bars and columns, percentile
  bars, line, lines, stacked bars, histogram, comparison dots, meter) that carry the
  house rules; `wb/theme.py`: one palette stepped for a light and a dark surface;
  `components.chart`: every chart with its table view, CSV and interactive HTML export.
- `fol ui`: starts the workbench for this project and opens the browser once it answers.
- Services the pages needed: `ContractService` (salaries, team payrolls against every
  line, commitments, outlook, cap rules, what the file adds up to), `BuilderService`
  (the user's rosters: slots, assumed salaries, payroll, roster-rule checks, pooled
  indicators beside the league), `HealthService` (source states, freshness, failing
  fetches, gaps, checks, build history), `explore.relationship`, league
  season-over-season changes, team percentiles.
- Analytics behind them: `finance` (team payrolls, position against each payroll line,
  a season's salary totals), `rosters` (20 roster indicators, pooled from player totals
  and weighted by minutes), `relationships` (linear and rank correlation with the sample
  they rest on), trailing-span metrics restricted to full spans on request.
- `docs/WORKBENCH.md`, the user's guide; screenshots in the README.

**Decisions** ([0008](decisions/0008-workbench.md))

- The interface displays and never computes. Where a page needed a number the services
  did not give, the service gained it.
- Charts come from one module that knows nothing about Streamlit or basketball, and the
  house rules are its tests: one scale, thin marks, ink text, at most three series in a
  scatter and four in a line chart, enforced with an error rather than another colour.
- The palette is checked by arithmetic, in both themes, and the page theme is kept in
  step with it by a test.
- Nothing is reachable only by hovering; missing is said, not hidden; where a number
  comes from is on the page; no judgement is offered.
- Form charts draw full spans only, and percentiles are written from 1st to 99th.
- A click on a table row acts once: the table then returns under a new key with nothing
  selected. A widget is never written to after it is drawn; the value is parked and
  applied on the next run.
- The workbench listens on this machine only and sends no usage statistics.

**Verification**

- Every page is drawn without a browser for nine kinds of filter state on a database
  with contracts, and again without contracts: none raises, each shows one title and no
  error. What a page shows is compared with what the service returns - headline figures,
  ranks, estimates marked as such, payroll against the lines, roster checks, salary
  sources, correlations, gaps.
- A sweep puts every control on every page through every value it offers - 847 page
  runs from twelve starting states - and presses every button: no exception and no
  error box. Planted crashes behind a single option of a select, a segmented control
  and a text box were each found by it.
- On the real database (build 3, 174,492 rows) all seven pages draw without an
  exception, each in 1.5 to 3.2 seconds from a cold start.
- The journeys the tests cannot make were clicked through in a real browser: choosing a
  team and a player by table row and then changing and clearing the choice in the
  sidebar; and, on a scratch database, creating a roster, adding players, typing a
  salary into the table, changing a slot so that its holder moves to the bench, ticking
  a player off, and deleting the roster. This found two defects no test had shown, both
  fixed and now covered: a selected row went on overruling the sidebar, so a team or
  player chosen by row could not be changed or cleared there; and creating a second
  roster from the "New roster" form raised an error, because the page wrote to the
  roster select after drawing it.
- Palette, measured (OKLab distance x 100; the floors are 15 for full colour vision and
  8 under simulated protanopia and deuteranopia): neighbouring series differ by 19.6 and
  9.1 on the light surface and 19.3 and 8.4 on the dark; the three series a scatter may
  use by 24.0 and 9.2, and 20.9 and 9.4, in every pairing. A fourth scatter series fails
  (13.7 light; 10.6 and 4.8 dark), which is why the cap is three. The figures were
  reproduced by an independent implementation in the tests.
- `fol ui` was started for real: the server answered its health check and served the
  pages.
- Screenshot review of all seven pages in the light and the dark theme, on the real
  data and, for the contract views, on a scratch database with invented salaries kept
  outside the repository. Looking found what the tests could not, and each was fixed:
  colliding labels in the team scatter (labels now choose a free side); truncated
  headline labels; a reference label the line could cross (moved to the margin);
  threshold names overprinting each other (two rows, short names); a stacked chart
  without its legend; "None" and "nan" in empty cells (a dash); cramped roster-table
  columns; a study control hidden in the sidebar (moved onto the page); values clipped
  at the tip of a full percentile bar; a best-in-group player shown at the "100th
  percentile"; form charts that opened with a one-game spike which set the scale for
  the rest of the season (full spans only); date labels written at a slant on narrow
  charts; a player chosen by row whose profile stayed behind another tab (the profile
  now opens); and headline tiles that cut off their text in a row of six (two rows of
  three). Checked again at a laptop width of 1366 pixels.

**Gate**

| Check | Result |
| --- | --- |
| Automated tests | 1,687 passed, none skipped (420 of them for the workbench); about two minutes with `pytest -n auto` |
| Test sensitivity | Services and analytics for the pages: 56 planted bugs, 52 caught at once, 4 gaps closed, then 56 of 56. Workbench and launcher: 85 planted bugs, 77 caught at once; 6 exposed gaps that were closed and then caught; 2 were not bugs (Streamlit itself drops a remembered choice that is no longer offered, so removing the lab's own guard changes nothing) |
| Data-quality checks | Unchanged: 44 checks, 0 errors, 2 standing warnings |
| UI review | All seven pages, light and dark, real data and invented contract data, plus a click-through of the interactive journeys in a browser; issues above fixed and re-shot |
| Architectural boundaries | `tests/architecture` passes, the interface rule no longer skipped: `apps/` imports only `services` and `domain`; `streamlit` and `plotly` appear nowhere else. A search of the pages for arithmetic on data found only rounding, unit conversion and counts of what is drawn |
| Lint | `ruff check` and `ruff format --check` clean |

**Version 1.0**

Milestones 1-7 are the roadmap's version 1.0. Nine of its ten acceptance criteria are
met; the checklist with evidence is in [ROADMAP.md](ROADMAP.md). The tenth - player
contracts available in the workspace - is open: the import path and every view exist
and are tested, but the workspace holds no contracts until a file is supplied.

**Open items carried forward**

- Contract data needs a decision from the user: fill in the template by hand, or
  license a feed. Nothing is collected automatically (decision 0004).
- Cap rules are configured for 2024-25 to 2026-27 only; salaries in other seasons have
  no cap share.
- Kept tables (rosters, history) have no migration mechanism yet; one is needed before
  their contracts change.
- `AppTest` cannot click a table row or edit a table cell. The tests imitate the first
  and test the second at the function that saves the edits; the real thing has to be
  clicked through in a browser whenever those paths change. There is no browser test in
  the suite.
- Static images are saved from the chart toolbar in the browser; there is no
  server-side image export.
- The pages were reviewed at desktop widths. Nothing was designed for a phone.
- Defensive indicators are thin (steals, blocks, defensive rating); lineup data is
  deferred to the roster-fit milestone.

## Milestone 6 - Team analytics (2026-10-01)

**Built**

- `analytics/teams.py`: a catalogue of 25 team metrics (record, scoring, efficiency, the
  four factors at both ends, style); season metrics with league-relative ratings;
  league averages by season; standings with games behind; home, road and recent
  records and streaks; how each season ended; metrics over any span of games and over
  trailing spans, with possessions estimated from box scores and calibrated per season.
- `services/teams.py`: `TeamService` - the season table with ranks and league reference
  lines, the same for a span of games or the postseason, a franchise profile with every
  season on record, game log, rolling metrics, and the rotation (what each player did
  for this team).
- `services/league.py`: `LeagueService` - standings, league averages by season, the
  history of every team-season with rating ranks and outcome, champions, and the
  playoff bracket of a season.
- `domain/glossary.py` and `fol metrics --write`: `docs/METRICS.md`, generated from the
  metric catalogs, with a test that fails when the committed file is stale.
- `analytics/comparison.ranks` can rank within a group (a season).

**Decisions** ([0007](decisions/0007-team-metrics.md))

- A season's ratings and pace are the league's published figures. A span of games uses
  estimated possessions - the mean of both teams' box-score estimates, scaled by a
  per-season factor - and every view built that way names its estimated metrics.
- Era comparisons use league-relative ratings against the pooled league average of the
  same season.
- The four factors use the standard definitions; the league's differently defined team
  rebound percentage is not imitated.
- Outcomes are stated per team-season; no threshold or "contender" judgement is drawn.

**Verification**

- Estimator choice was made on evidence from all 892 team-seasons: calibrated, the
  estimate is unbiased, within 0.20% of counted possessions on average (worst 0.86%),
  and reproduces published offensive ratings within 0.22 on average. The table of
  alternatives is in the decision record.
- Team turnover rate, assist percentage, effective field goal and true shooting
  percentage equal the league's published figures to three decimals for every team in
  the three fixture seasons, with one exception that is itself a known source
  inconsistency (Sacramento, 1996-97) and is asserted as the only one.
- On the real database the champions view (from the playoff series table) and the
  outcome flags of the team-season table name the same champion and runner-up in all
  thirty seasons, and the Finals results through 2024-25 match the historical record.
- On the real database: team table 0.12 s; last-15-games table 0.21 s; franchise
  profile 0.12 s; standings 0.15 s; history of 892 team-seasons 0.11 s.

**Gate**

| Check | Result |
| --- | --- |
| Automated tests | 1,101 passed, 1 skipped (UI boundary test) |
| Test sensitivity | 58 planted bugs in team analytics, ranks, the two services and the glossary: 58 caught |
| Data-quality checks | Unchanged: 44 checks, 0 errors, 2 standing warnings |
| UI review | Not applicable |
| Architectural boundaries | `tests/architecture` passes; services import only domain, config, storage, analytics |
| Lint | `ruff check` and `ruff format --check` clean |

**Open items carried forward**

- In the first days of a season the team table holds only teams that have played, so
  standings are incomplete until every team has a game.
- Team payroll against the cap lines belongs with the contract views (milestone 7).

## Milestone 5 - Player analytics (2026-10-01)

**Built**

- `analytics/formulas.py`: every basketball formula, once. Shooting percentages,
  effective field goal and true shooting percentage, turnover percentage, per-game,
  per-36 and per-100 rates, ratings, pace, estimated possessions.
- `analytics/players.py`: a catalogue of 45 player metrics in the roadmap's six groups
  (availability, scoring, creation, rebounding, defense, impact); season metrics; metrics
  over any span of games; rolling metrics; recent availability; on/off combined across
  teams for traded players.
- `analytics/comparison.py`: qualification thresholds, percentiles oriented so higher is
  better, ranks, side-by-side comparison, pooled group averages, position groups.
- `analytics/finance.py`: cap share and a payroll's position against each threshold.
- `domain/metrics.py`: `MetricSpec`, which carries each metric's label, description,
  format, provenance and better direction.
- `services/`: `Lab` (opens the data, reports what it holds) and `PlayerService` (season
  table, profile, game log, rolling metrics, availability, comparison).

**Decisions** ([0006](decisions/0006-metrics.md))

- Derived metrics are computed by the lab; league-measured ones are passed through and
  labelled as such, never approximated.
- A rate with no denominator is missing, not zero.
- Percentiles are computed within a qualified group and always read "higher is better".

**Verification**

- The lab's effective field goal and true shooting percentages equal the league's
  published values to three decimals, and its offensive rating to one decimal, for every
  team in three seasons and every shooter in the fixture data. On the full store the
  same holds for 477 players.
- That comparison also showed where the league's definitions differ from the textbook
  ones (team rebound percentage, player turnover rate); each is recorded in the
  decision record and in the metric's description.
- On the real database: the 2025-26 player table (582 players, 45 metrics, percentiles)
  is produced in 0.3 s; a last-ten-games table in 0.7 s; a player profile in 0.2 s.

**Gate**

| Check | Result |
| --- | --- |
| Automated tests | 946 passed, 1 skipped (UI boundary test) |
| Test sensitivity | 30 planted bugs in formulas, metrics, comparison, finance and the service: 27 caught at first; the three misses were real gaps in the service tests, now closed (30 of 30) |
| Data-quality checks | Unchanged: 0 errors, 2 standing warnings |
| UI review | Not applicable |
| Architectural boundaries | `tests/architecture` passes; analytics imports only domain |
| Lint | `ruff check` and `ruff format --check` clean |

**Open items carried forward**

- Defensive indicators are limited to steals, blocks, fouls and on-court defensive
  rating. Tracking-based measures (contested shots, rim defence) need more datasets and
  belong with the value engine.

## Milestone 4 - Database and repositories (2026-10-01)

**Built**

- `storage/schema.py`: SQL tables generated from the data contracts, with a fingerprint
  of their shape.
- `storage/database.py`: the SQLite database, with transactional DDL, write-ahead
  logging and foreign keys on.
- `storage/warehouse.py`: `Warehouse.replace` rewrites every rebuilt table inside one
  transaction; `Warehouse.read` returns contract-conforming frames with simple filters.
- `storage/rosters.py`: `RosterRepository` for the user's rosters.
- `storage/operations.py`: `OperationsLog` for the history of fetches and builds.
- Contracts for seven new tables: `custom_rosters`, `roster_players`, `fetch_log`,
  `builds`, `build_issues`, `check_results`, `raw_snapshots`.
- `pipelines/build.py`: normalise, check and load in one step; record the build.
- Commands: `fol build`, `fol refresh` (ingest then build), `fol db`. `fol ingest` now
  records every fetch that reached the source.

**Decisions** ([0005](decisions/0005-database.md))

- One SQLite file through SQLAlchemy Core; tables generated from contracts.
- League tables and the last build's report are rebuilt together in one transaction;
  the user's rosters and the fetch and build history are kept across builds.
- A build with problems still loads and records them; a build that would empty a
  populated table is refused unless forced.
- Foreign keys are enforced only between kept tables.

**Something learned the useful way.** A probe before writing any storage code showed
that, with SQLAlchemy's defaults, a `DROP TABLE` inside a rolled-back transaction stays
dropped on SQLite. Had the rebuild been written on the assumption that transactions
cover DDL, a failed build would have destroyed the previous one. The database layer now
controls transactions explicitly and a test proves a failed rebuild restores the old
tables.

**Verification**

- `fol build` on the real store: 174,492 rows in about twenty seconds, 32 MB.
- Read back from the database, every league table equals what was written, column for
  column, with the same types.
- Reads: one season of team rows in 0.05 s; one season of player game logs (26,651
  rows) in 0.4 s; every team game since 1996 (76,046 rows) in 1.1 s.
- A reader with an open transaction sees the previous build until the new one commits.
- Rosters survive rebuilds.

**Gate**

| Check | Result |
| --- | --- |
| Automated tests | 745 passed, 1 skipped (UI boundary test) |
| Test sensitivity | 20 planted bugs in storage and the build: 18 caught; both survivors were equivalent (a redundant branch, since removed; one half of a two-part recipe, now asserted directly) |
| Data-quality checks | `fol build` on the real store: 0 errors, 2 standing warnings |
| UI review | Not applicable |
| Architectural boundaries | `tests/architecture` passes; `sqlalchemy` appears only in `storage` |
| Lint | `ruff check` and `ruff format --check` clean |

**Open items carried forward**

- Kept tables have no migration mechanism yet; one is needed before their shape changes.
- Every build reloads everything. Fine at twenty seconds; revisit if it grows.

## Milestone 3 - Contracts and salary-cap data (2026-10-01)

**Built**

- `providers/contract_file.py`: reads a contract file the user supplies and returns its
  text unchanged as a snapshot, with the user's statement of where the figures came from
  and when they were current.
- `processing/contracts.py`: parses the wide and long layouts, reads dollar amounts and
  option/guarantee markers, matches rows to known players and teams, and builds
  `contracts` and `contract_years` with each salary's share of its season's cap.
- `salary_cap_rules`, `contracts` and `contract_years` are now part of every build.
- `pipelines/contracts.py`: `fol contracts import` validates a file before storing it;
  `fol contracts template` writes a file listing every rostered player.
- Ten more quality checks: five foreign keys and five contract checks.
- `docs/CONTRACT_DATA.md`: the file format.

**The permissions check, and what it changed**

The roadmap requires checking automated-use permissions before building a contract
scraper. The check found that Basketball Reference's terms prohibit this project's use
of its data, that Spotrac refuses automated requests, and that the one API offering
contracts charges for them. No scraper was built. Contract data enters through a file
the user supplies ([0004](decisions/0004-contract-data-from-user-files.md)).

**Consequence for version 1.0.** The acceptance criterion "player contracts ... are
available in the workspace" is met by the import path, not by shipped data. Until a
contract file is imported the contract tables are empty and the build says so.

**Defects found by tests in this milestone**

- *Raw store ordering.* Snapshot file names were written to the second, so two imports
  within one second could sort in hash order and the older be taken as the newest. Names
  now carry microseconds and versions are ordered by fetch time. Names written to the
  second are still read.
- *Data read as markup.* The command line passed data through rich's markup, which
  swallowed a scope printed as `[all seasons]`. Data is now printed as plain text.
- *An unpaired game crashed its own check.* `games_are_paired` failed with a type error
  on exactly the input it exists to report. (Found and fixed in milestone 2's tests.)

**Decisions**

- A file-level problem rejects the whole contract file; a row that cannot be matched to
  a player is left out and reported. The first means the file is not what the user
  thinks it is; the second is an ordinary spelling difference.
- A contract file is validated before it is stored, so a bad file never becomes the
  newest snapshot and cannot break the next build.
- Cap share is null for seasons with no configured cap. It is never extrapolated.

**Verification**

- `fol contracts template` on the real store lists 622 rostered players.
- `fol check` on the real store: 44 checks, 42 passed, 0 errors, the same 2 standing
  warnings, and a note that no contract file has been imported.
- Contract logic is tested with an invented cast and invented salaries only. No real
  salary figure appears anywhere in the repository.

**Gate**

| Check | Result |
| --- | --- |
| Automated tests | 636 passed, 1 skipped (UI boundary test) |
| Test sensitivity | 15 planted bugs in the contract import, checks and raw store: 14 caught; the survivor was a redundant filter, since removed |
| Data-quality checks | `fol check` on the real store: 0 errors, 2 standing warnings |
| UI review | Not applicable |
| Architectural boundaries | `tests/architecture` passes; no rule changed |
| Lint | `ruff check` and `ruff format --check` clean |

**Open items carried forward**

- A contract file has to be supplied before salaries, payroll and cap share can be used.
- Cap rules exist for 2024-25 to 2026-27 only; later contract seasons have no cap share.

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
  player's games and points equal the player's game log; in all 7,882 team-games with player
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
