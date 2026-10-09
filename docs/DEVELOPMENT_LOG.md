# Development Log

One entry per milestone: what was built, what was decided, and the evidence for the
completion gate. Newest first.

## Milestone A0 - AI Research Assistant: audit, decisions, evaluation cases (2026-10-09)

The first milestone of the assistant track ([ROADMAP](ROADMAP.md#ai-research-assistant-a0-a9)):
a read-only audit of the lab against the user's assistant roadmap, the decisions it
needed, and the cases every model will be scored on. No production code changed.

**The audit**

- Read the project's instructions, architecture, roadmap, audit, source register,
  decisions and research documents; dumped every public service signature from the
  source; checked the workbench's frame, filters, caches, charts and tags; checked the
  data (build 16 of 2026-10-06, stats.nba.com last fetched 2026-10-01/02, the contract
  file as of 2026-07-07, all four model files at revision 2) and this machine (Ollama
  0.40.0 on the loopback address, an RTX 4060 with about 1.9 GB of its 8 GB already in
  use, Docker present but not needed).
- Three research passes verified the outside facts: Ollama's interface and its cloud
  features; the NBA's terms, robots files and data endpoints; and every no-cost route to
  general web search. Their findings, with the decisions, are in decision 0018 and the
  source register.
- One request to stats.nba.com through the lab's own provider, with the user's approval,
  to test an upstream report of blocking: it answered (45 rows, 0.5 s). Nothing was saved.

**Built**

- [Decision 0018](decisions/0018-ai-research-assistant.md): an outermost `assistant`
  layer reached by the workbench through one module; the local-only model; three kinds of
  data in three files; typed tools with no write class; every figure from a tool; the
  sources.
- [AI_ASSISTANT_SPEC.md](AI_ASSISTANT_SPEC.md): the tool registry mapped to exact service
  methods, what a result carries, what an answer must do, Quick and Deep, current data,
  safety.
- [AI_EVALUATION.md](AI_EVALUATION.md) and `tests/assistant/fixtures/cases.yaml`: 59 cases
  in 17 categories, 17 of them with no answer in the usual sense, 56 frozen figures from
  the fixture build and the invented contract file. `tests/assistant/test_cases.py` checks
  the file and recomputes every figure through the services.
- The source register: the assistant's sources with their terms; the NBA's section 9 on
  the existing stats.nba.com use; the user's permission for salary rows in the local
  model's prompts.
- The assistant track in the roadmap.

**Decisions** ([0018](decisions/0018-ai-research-assistant.md)), all approved by the user

- The `assistant` layer and its import rules; the two new data files.
- General web search through Ollama's web search on the user's free account; SearXNG,
  DuckDuckGo scraping, and Google's and Bing's closed APIs are out.
- Salary rows may go to the local model: the user read HoopsHype's terms.
- Candidates for A1: `qwen3:4b`, `qwen3:8b`, `qwen3:4b-instruct`, with `qwen2.5:7b` for
  reference.

**Changed from the plan**

- Recorded payloads for the current-data and web cases arrive with the adapters in A2,
  since their shape depends on them; A0's cases carry the conversations, and two web
  cases already end in a tool's result (an empty search; a page carrying instructions).
- The forward-looking test that the proposed layer rules are acyclic was left out: A1
  lands the rule itself, and `test_layer_rules_have_no_cycles` checks it there.
- `propose_rosters` is not a tool the model calls: each roster `optimize_roster` finds
  becomes a draft for the user to review.

**Found on the way**

- `qwen3:4b` now names the Qwen3-4B *thinking* model, which always reasons before
  answering; `qwen3:4b-instruct` is the same size without it.
- `OptimizerService.save` creates a roster and then adds each player in a separate
  transaction. A5 adds an atomic save for approved proposals.
- The research documents are stamped with build 14; builds 15 and 16 changed only the
  contract tables, so their content stands.
- The user's Ollama runs with a 16K default context (`OLLAMA_CONTEXT_LENGTH`), and cloud
  enabled. The adapter will set the context on every request and refuse remote models.

**Gate**

| Check | Result |
| --- | --- |
| `ruff check .`, `ruff format --check .` | Pass |
| `pytest tests\assistant tests\architecture` | 81 passed |
| Production code changed | None: `docs/` and `tests/assistant/` only |
| UI | Not affected |

## Contract data - the MrBridge salary dataset (2026-10-05)

Not a milestone: the contract file that the one open acceptance criterion waited on
arrived, and the lab was changed where its shape did not fit. The user supplied
MrBridge's *NBA Salary Cap & Contracts 2016-2026* dataset (HoopsHype's public salaries,
snapshot of 2026-07-07): every salary a team paid from 2015-16 to 2026-27, one row per
player per team per season, with the site's own ids and flags.

**Built**

- `scripts/convert_salary_dataset.py`: rewrites the dataset's salary table into the lab's
  long layout - the site's ids left out, the two-way and option flags carried as type and
  option, the four rows that list one player twice for the same team, season and kind
  added up, 38 spellings and 15 ids written as the league's indexes have them, one row
  left out with its reason - and prints every merge, flag and omission.
  `tests/unit/test_convert_salary_dataset.py` covers each of these on small files and
  checks that the shipped lists name real differences only.
- The import's duplicate rule (`processing/contracts.py`) and the quality check
  (`quality/checks.py`, now `one_active_contract_per_player_team_season`) are per team,
  season and kind of contract: a move within a season, a two-way contract converted to a
  standard one and dead money beside an active contract are all allowed.
- `ContractService.salaries` adds up a player's active shares for a season and carries
  the option, guarantee and seasons remaining of the contract that runs on; the Player
  Explorer, the value-for-money view and the optimizer's pool read it.
- The plausibility bands describe a season's full list: a salary is suspect below 0.003%
  or above 45% of the cap, a team's first-season count below ten or above forty.
- Payroll is priced by default in the league year the file was current for - the one
  that holds its as-of date, now carried on the lab's status - instead of the earliest
  priced season in the file, which a history put at 2024-25. The Team Explorer's
  contract-by-contract table starts at the season on screen and leaves out the
  contracts that ended before it.
- Imported and built in (build 16): 4,189 contracts for 1,627 players, 7,229 contract
  seasons from 2015-16 to 2026-27; cap shares for 2024-25 to 2026-27, blank before. The
  54 rows the import could not match are camp signings who never appeared in a game and
  are in no league index.
- Documentation: the converter section of [CONTRACT_DATA.md](CONTRACT_DATA.md); the
  source register's account of what the lab does with each of the dataset's sixteen
  files and under what terms; the Contract Explorer's note in the workbench guide; the
  roadmap's last acceptance criterion closed; a postscript in the audit; the rule in
  `CLAUDE.md`; decision 0017.

**Decisions** ([0017](decisions/0017-contract-history.md))

- A contract file may be history, split by team; the import's rules and the checks
  match that grain instead of the template's.
- A player's own salary for a season is the sum of what the teams paid.
- The dataset is converted outside the lab by a committed script that holds the record
  of every difference; the importer is not taught the dataset's layout, because a
  `player_id` column means the league's id for every file.
- Only the salary table is used. The payroll table is a cross-check; the cap figures for
  the seasons before 2024-25 are not transcribed, since a rules file needs the floor, the
  exceptions and the roster limits from a cited source and the schema has two aprons
  where those seasons had one.

**Verification**

- The converter on the real file: 7,288 rows read, 7,283 written, four merges (each
  listed with both amounts), one row left out, every row of the report read.
- A dry-run import before anything was stored: every one of the 738 rows the first pass
  could not match was traced to the Clippers' name, a spelling, a shared name or a camp
  signing, and the lists were built from that report, each target checked in the league's
  player index.
- The dataset's own payroll table against the lab's payrolls: all 360 team-seasons
  present, 311 equal to the dollar, the rest short by exactly the rows left out
  ($10,618,795 of $49,967,361,444).
- The dataset's cap, tax and apron figures for 2024-25 to 2026-27 equal the lab's rules
  files.
- Tests for the per-team rule (same team rejected; a move, a two-way conversion and dead
  money allowed), for the summed salary and the contract that runs on (a player paid by
  two teams in the priced fixture), and for the renamed check everywhere it is named.
- The default payroll season on five shapes of file - looking ahead, a history, a history
  that stops before its date, a file that starts after its date, one without a date -
  and the windowed table on a frame holding a contract that had ended.
- Build 15 showed the old check failing 441 times, every failure a move between teams or
  the one two-way conversion; build 16, with the rules above, has no error and the same
  seven standing warnings as before the import.

**Found on the way**

- The lab's three assumptions - one contract per player per season, fourteen or fifteen
  per team, nothing below a two-way salary - were the invented template's, not the
  format's. A season's full list of everyone a team paid runs to 24 in the file's first
  season and the dataset's own payroll table counts up to 36.
- The league's team index names the Clippers "LA Clippers"; the dataset writes "Los
  Angeles Clippers", and 476 rows went unmatched until the script named the team as the
  index does.
- Name matching strips suffixes, so "Marcus Thornton II", who played no NBA game, would
  have been handed to the elder Marcus Thornton; the script leaves the row out and says
  why. "Scottie Pippen Jr" and "Scotty Pippen Jr." differ in the first name, not the
  suffix, and are an alias.
- The dataset lists both of John Wall's 2022-23 amounts under Houston; the second equals
  that season's taxpayer mid-level exception, which another team paid him. The lab
  carries what the file states; the doubt is recorded in decision 0017.
- Two of three full-suite runs printed a Windows access violation from inside the
  Streamlit test harness while it read a table, under different tests. The first killed
  its worker and failed that test, which passes on its own; the second was survived and
  every test passed. Not the lab's code; noted so the next person does not chase it.
- The Windows console is cp1252: the script reconfigures its output to UTF-8 before it
  prints an accented name.

**Gate**

| Check | Result |
| --- | --- |
| Automated tests | 3,000 passed, none skipped; about five minutes with `pytest -n auto` |
| Data-quality checks | `fol check`: 57 checks, 50 passed, 7 standing warnings, 0 errors; build 16 loaded 971,080 rows |
| UI review | Contract Explorer, Player Explorer, Team Explorer, Player Value, Team Builder and Roster Optimizer in both themes through a browser on the final code, with the real contracts on screen |
| Architectural boundaries | `tests/architecture` passes; no rule changed. The converter is a script outside the package and imports nothing from it; the summed salary is `services`; the rule and the check are `processing` and `quality` |
| Lint | `ruff check` and `ruff format --check` clean |

**Open items carried forward**

- Season rules for 2015-16 to 2023-24: the floor, the exceptions and the roster limits
  from a cited source, and a schema that allows one apron before 2023-24. Until then the
  cap columns for those seasons are blank.
- Payroll in the contender research, now that twelve seasons of history are in the
  database.
- HoopsHype's own terms were not checked; the dataset's README states research and
  educational use, and the responsibility rests with whoever supplied the file (decision
  0004).
- From milestone 14: value weights refitted inside each postseason window; a wins test
  through the simulator's own draw; the field; lineups; the long modules and duplicated
  helpers.

## Milestone 14 - Full-system audit (2026-10-05)

**Built**

- [AUDIT.md](AUDIT.md): the audit in six passes - architecture, leakage, tests, the
  workbench, documentation, performance - with what was found, changed and left.
- The value model tested a second time with the minutes projected
  (`modeling/value/estimate.py`, `Validation.projected`, `BacktestRow.projected_net`):
  3.63 points of net rating against 3.01 with the minutes as played, the projected
  minutes covering 87% of the floor. The optimizer, the simulator and the postseason
  model carry the second figure; the Player Value page and the research document show
  both.
- The season model scored as a forecast reads it (`Evaluation.before_season`): from the
  rating predicted before each season, averaged over its error, with the typical
  top-player quality; on the Postseason Outlook page's model tab and in the research
  document beside the in-season reading.
- Every model file refitted in order against build 14: value revision 2, postseason
  revision 2, simulator revision 2 (its least-known band had drifted from the code), fit
  evidence revision 2; every research document regenerated.
- Performance: warehouse reads from row tuples; integer and text fast paths in the
  contract check; `Lab.remembering` for one answer's reads; postseason intervals only
  where shown; roster-subject scenarios cached on the roster's stamp; the status caches
  keyed on the model files' stamps so a refit shows without a rebuild.
- Rule fixes: the home-court chance as a method of the game model; the profile's change
  column, a stint's on/off difference, top-player quality for a roster and a team's
  standing among its season each defined once in the layer that owns them; the NaN-safe
  interval everywhere; dead code gone; the optimizer page's `except Exception` and its
  invented $100M fallback gone; the qualification policy and the season's date range in
  services; the default page served at the root alone.
- The pool for a season being played keeps the players who have appeared in it.
- Documentation: the contract import followed by a build everywhere it is described;
  a dozen stale statements corrected; two planned tables removed as decided against and
  lineups deferred; the glossary's origin note; the benchmark limits; the regeneration
  order in the research headers.

**Decisions** ([0016](decisions/0016-audit.md))

- A forecast carries the error of the test that projected minutes too; the rating-alone
  test stays for the comparisons with simpler methods.
- The season model is scored both from the season played and from what could be known
  before it, and both are shown.
- Fitted files are refitted in order and each names the others; statuses are keyed on
  the files' stamps.
- The lab remembers reads within one answer and never across answers.
- The value-for-money line, a description of the user's contract file, may be fitted on
  request.

**Verification**

- The projected-minutes test on the invented league: present, finite, its share in
  range, every backtest row carrying its projected rating, and a file without it still
  readable. The simulator's error is that figure and says so; its wins test is drawn
  around the projected ratings.
- The before-the-season reading on the invented league: present when predictions are
  given and absent when they are not, every stage scored, and never a better log loss
  than the season played.
- The read memo: fresh outside a block, once within it, copies to callers, nested blocks
  sharing one memory. The intervals switch changes nothing but the intervals. An emptied
  roster is five replacement players. The pool during a season keeps appeared players.
- The warehouse's tuple reads give frames equal to the dictionary reads on every table
  measured; the contract check's fast paths pass the domain, storage and processing
  tests unchanged.
- The whole suite, `fol check` (57 checks, 7 standing warnings, no error) and a rebuild
  (build 14, 959,661 rows). Every page and tab in both themes through a browser on the
  final code.

**Found on the way**

- The running workbench loads code at the first request and keeps it: a code change
  under a browser walk produced an import error on screen, and every screenshot pass
  after a change needs the server restarted first.
- Streamlit serves the default page at the root and ignores its path; a page's URL path
  on the default page is dead.
- Streamlit's own "connection error" dialog appears when the machine is saturated, and
  it intercepts every click; browser passes cannot share the machine with a parallel
  test run.
- `pyproject.toml` already passes `-q`, so a second `-q` hides the summary line; a test
  count comes from the collection's per-file lines.

**Gate**

| Check | Result |
| --- | --- |
| Automated tests | 2,969 passed, none skipped; about five minutes with `pytest -n auto` |
| Data-quality checks | `fol check`: 57 checks, 50 passed, 7 standing warnings, 0 errors; build 14 loaded 959,661 rows in one to two minutes |
| UI review | Every page and every top-level tab in both themes through a browser on the final code; the three fixes re-checked the same way |
| Architectural boundaries | `tests/architecture` passes; no rule changed. Reads and the memo are `storage` and `services`; the second value test and the before-the-season reading are `modeling`; the pages compute nothing new |
| Lint | `ruff check` and `ruff format --check` clean |

**Open items carried forward**

- A contract file, which every salary view and the optimizer wait on.
- Value weights refitted inside each postseason window, and fit measures built from
  them: +0.003 log loss, measured and left.
- A wins test through the simulator's own draw, on rosters as they stood before each
  season.
- The field: a league simulation with a schedule, standings, the play-in and the bracket.
- Lineups; the long modules and the duplicated small helpers listed in the audit.

## Milestone 13 - Scenario simulator (2026-10-05)

**Built**

- `domain/scenario.py`: a scenario - a subject (a real team as it stands for the season
  ahead, or a roster built in the Team Builder), the players added and removed, a
  per-player adjustment (games missed, development in points of impact, a share of the
  minutes, a salary), the availability and development presets, and how many seasons to
  draw - with its validation and a fingerprint. `domain/simulator.py`: the specification
  (`configs/models/simulator.yaml`: the seasons the noise is measured over, the
  reliability bands, the rotation threshold, the quantiles kept, the wins test's draws
  and levels, the interval shown) and what a measurement writes down - the five figures,
  the noise by era, how projections have missed by band, the missed-games distribution
  and the wins test.
- `modeling/simulator/`: `measure.py` (a season's own noise from the spread of game
  margins; how far projections have missed by how well the player was known, weighted
  by the minutes played; the share of a season rotation players have missed; wins per
  point of net rating and the residual wins), `monte_carlo.py` (one scenario drawn
  thousands of times: every player's impact and missed games, the parts added up for
  the minutes drawn, the miss on a team's strength the value model's test leaves, a
  season's noise, wins, the postseason model's season steps) and `fit.py` (the
  measurement on the warehouse and the wins test).
- `pipelines/simulator.py` and `fol simulate fit [--write]`, `fol simulate show`,
  `fol simulate report [--write]`; `configs/models/simulator.json`, revision 1, measured
  on 892 team-seasons, 35,546 regular-season games and 14,569 player-seasons.
- `services/simulator.py` - `SimulatorService`: the teams and the pool for the season
  ahead, a team's or a roster's players with their projections, a scenario drawn before
  and after (payroll, projected rating, wins with their interval, top-player quality,
  the chance of every stage with its interval, the wins distribution, the roster's fit
  profile through the Roster Fit lineup), the season ahead drawn for every team, and a
  scenario saved as a Team Builder roster. `services/simulator_report.py` and
  [research/SIMULATOR.md](research/SIMULATOR.md).
- The **Scenario Simulator** page, in the Forecast group: the subject, the changes
  (players out and in, the two presets, the seasons drawn) and five tabs - Before and
  after, Players (a table of each player's projection and the assumptions typed in),
  Profile, The season ahead, The evidence. The line chart grows an x-axis title and tick
  step; the comparison dots an axis range and format. A screenshot in the README.
- The invented league now plays regular seasons: a double round robin and twelve more
  home games each, 82 in all, from the planted strengths, a home edge and a margin
  noise, so that every measurement can be checked by hand; `postseason_league()` fits
  the value model on it so that a backtest exists for the wins test.

**Decisions** ([0015](decisions/0015-simulator.md))

- A season is drawn from the parts the lab has tested plus five figures measured here,
  and the spread of a roster's strength is calibrated to the value model's
  out-of-sample error, not to the sum of the players' spreads.
- Every input is the user's assumption and is tagged so; the presets move every player
  by the typical miss of players known that well, and a projected share already allows
  for the games typically missed.
- The field is not modelled: each roster is drawn alone, as a team of its strength
  entering any season, and the page and the report say so.
- No store of scenarios: a scenario is saved as a roster, which is what persists.

**Verification**

- The measurements against hand computations: the noise of planted margins, eras
  averaging the seasons they cover, bands from planted misses, quantiles of planted
  missed games, wins per point from the value model's own routine. The Monte Carlo
  without noise is exactly the sum of the parts; scales shares that run over a season
  down; steps the presets by each band's typical size and lets a figure of the user's
  own replace them; reads missed games off the measured distribution and shifts them to
  the preset or the user's figure; is reproducible and spreads as the parameters say;
  takes the players' own spread out of the team-level miss; reads an emptied roster as
  five replacement players.
- The fit on the invented league recovers the planted noise and the value model's wins
  per point, leaves nothing for the strength miss where the ratings carry no noise, and
  writes a file that reads back equal; the wins test's coverage by hand.
- The pipeline measures what the modeling measures, writes nothing unless asked and
  names what is missing; the fixture store measures what it can. The service on the
  invented league: an unchanged scenario is the same before and after; removing the best
  player costs wins and chances; a player added; each adjustment on one player; seeds;
  every team drawn; a scenario saved. The report and the three commands.
- The shipped parameters: over the 600 team-seasons the value model predicted out of
  sample, the 50%, 80% and 95% intervals held the wins that happened 53%, 83% and 97%
  of the time, and the median season missed by 7.6 wins root mean square (6.0 on
  average) against 12.5 for an even record.
- The page: every tab against the service on the fixture store and on the invented
  league; the subject switch; a player removed; a preset; an emptied roster; the save;
  the sweep from two starts. In both themes on the real data, every tab, through a
  browser: as it stands, a player out and one in with both presets set, and every
  player removed.

**Found on the way**

- Players the value model had never seen had no reliability and fell out of the
  development bands; they are the least-known band now, which also lets the fixture
  store measure.
- The invented league's double round robin came to 70 games, not 82; twelve extra home
  games fill the season, so the noise is measured over a real schedule's length.
- Segmented controls with enum options broke under AppTest, which formats an option by
  the string's own `title`, a method on an enum; the options are plain strings with a
  dictionary of titles.
- In the browser: three controls on one row cut the preset names short, so the presets
  have the row and the seasons drawn sit below; an emptied roster showed an empty editor
  over its caption, and its three best players were the mean of nothing, a warning the
  tests treat as an error - it reads as five replacement players now; empty cells in
  the editor read "None"; the wins chart had two ticks.
- The sweep of the simulator page ran for twenty minutes in a full parallel run: the
  service read the projections and the status several times for one scenario and the
  fit tables twice over, and the page never cached the run of a built roster. Each is
  read once now, and the run of a built roster is cached on when the roster last
  changed; the sweep takes about a minute.

**Gate**

| Check | Result |
| --- | --- |
| Automated tests | 2,958 passed, none skipped; about six minutes with `pytest -n auto` |
| Data-quality checks | Unchanged: no table or check was added; the real database stands at build 13 (57 checks, 0 errors, 7 standing warnings) |
| UI review | The new page in both themes on the real data, every tab, through a browser; the subject, the players out and in, both presets and the tabs clicked through, and the two fixes above re-checked the same way |
| Architectural boundaries | `tests/architecture` passes. The scenario and the parameter file are `domain`, the measurement and the Monte Carlo are `modeling`, the measurement on request is a `pipeline`, every figure is computed by a `service` from the file; the page computes nothing and the build applies nothing |
| Lint | `ruff check` and `ruff format --check` clean |

**Open items carried forward**

- The field: a league simulation - thirty rosters, a schedule, standings, the play-in
  and the bracket - would need the parts re-derived so that luck is not counted twice.
- The wins test draws from the predicted rating alone, as the value model's backtest
  keeps it; a test of the whole roster draw, players' misses included, needs rosters as
  they stood before each season, which the warehouse does not keep.
- Scenarios are not stored; a store of named scenarios with their results is the next
  refinement if wanted.
- Milestone 14 is the full-system audit.

## Milestone 12 - Playoff and championship model (2026-10-05)

**Built**

- `domain/stages.py`: the one list of postseason stages, moved out of the benchmark
  research so that the benchmarks and the model read the same stages.
  `domain/postseason.py`: the specification (`configs/models/postseason.yaml`: the first
  test season, how many top players, the neutral postseasons, the series formats and
  when they changed, the reliability bands, the resamples) and what a fit writes down -
  the game model with its intervals and kept draws, the season model's steps, and the
  whole out-of-sample evaluation.
- `modeling/postseason/`: `features.py` (a team by its regular-season net rating and
  top-player quality; the games and series the model is fitted and tested on),
  `series.py` (one game, enumerated through the series format), `bracket.py` (a bracket
  read from the series played; the series model carried through it exactly; home court
  by record, head-to-head, seed, rating), `hierarchy.py` (the season model: conditional
  steps multiplied up, an uncertain rating integrated over by quadrature), `fitting.py`
  (a logistic fit by Newton's method with a trace of ridge; log loss, Brier, calibration,
  reliability with Wilson intervals, intervals from resampling seasons) and `fit.py`
  (both models fitted on every season and tested one season at a time against simpler
  methods and the alternatives tried).
- `pipelines/postseason.py` and `fol playoffs fit [--write]`, `fol playoffs show`,
  `fol playoffs report [--write]`; `configs/models/postseason.json`, revision 1, fitted
  on 2,440 playoff games, 450 series and 892 team-seasons.
- `services/postseason.py` - `PostseasonService`: a decided season's bracket with every
  team's chance of every round before game 1, its series with the chance given to the
  home-court side, every team of a season under the season model, a team of any strength
  with its interval, a real team or a built roster read as a team of its strength (the
  sum of the parts, with the value model's error folded in), and a stage's chance across
  net ratings. `services/postseason_report.py` and
  [research/POSTSEASON.md](research/POSTSEASON.md). The glossary grows to 152 metrics.
- The **Postseason Outlook** page, in a new Forecast group: A team's chances, Every team,
  The bracket, Series, The model. A band-line builder (an estimate with its interval as
  a wash) joins `wb/charts.py`.
- The invented league plays its playoffs: `tests/league.py` seeds sixteen teams, plays
  every series game by game from a planted home advantage and two slopes, and records
  the games, the series and every team's outcome as the real tables hold them;
  `tests/postseason_reference.py` holds the planted parameters and reference
  computations that share no code with the model.

**Decisions** ([0014](decisions/0014-postseason-model.md))

- Two inputs, both known before a playoff game is played and both things the lab can say
  about a roster before a season: net rating and the mean impact of the three best
  players.
- A game model carried through the format and the bracket, exactly; a season model of
  conditional steps, so that the thirty champions on record never carry a model of their
  own.
- Every test an expanding window from 2006-07; intervals from resampling whole seasons;
  no recalibration layer, and the calibration shown instead.
- Winning percentage, and the gap to the conference's eighth-best rating, out-predict
  the season model on seasons already played and are left out on purpose: the model is
  read for a roster before its season, when neither exists. Recorded with the figures.

**Verification**

- The series enumeration against a reference that walks every way a series can go, for
  every format; the other side's complement; even sides split evenly. The bracket
  arithmetic against a bracket played a hundred thousand times from the same parameters,
  every team and every round within a hundredth; the rounds adding up to eight, four, two
  and one; equal teams at a half, a quarter, an eighth and a sixteenth.
- The logistic fit recovers planted weights and finishes on perfectly separated data;
  calibration reads slope one on chances that mean what they say and a half on chances
  sharpened twice; reliability bands, resampling and intervals by hand.
- Fitting on the invented league finds the planted home advantage and slopes inside
  their intervals (0.44 for 0.45, 0.13 for 0.11, 0.28 for 0.30), and the evaluation
  covers eight test seasons - 120 series, 128 team-postseasons, 240 team-seasons - with
  the bracket's mean chances exact.
- The pipeline fits what the modeling fits, writes nothing unless asked, and names what
  is missing (no value model, no database, nobody valued, too little history). The
  service on the invented league (a bracket whose chances add up and whose first round is
  the series model on each pair; every series against the league's own record; thirty
  teams best first; a team and a roster read as a team of its strength) and on the
  fixture store (two valued teams: the bracket says who is missing, most series lack an
  input). The report, and the three commands.
- The page: every tab against the service on the fixture store and on the invented
  league; the empty states; the out-of-date notice; the sweep from three starts.
- The shipped model: beats every simpler method out of sample at every stage, each input
  earns its place, calibration slopes between 0.6 and 1.2, every reliability band covers
  its observed share, and the file is exactly what saving it would write.
- The page in both themes on the real data, every tab, clicked through in a browser: a
  team, a strength set by hand, every team, the 2025-26 bracket, its series, the model.

**Found on the way**

- Yesterday's edit of the command-line module had turned every `"\n"` in it into a real
  line break - a syntax error that left every `fol` command unusable. Repaired first.
- A season without playoff game logs, and a season in which nobody has been valued, broke
  the feature code on an empty text column; both now key on integers and give an unknown
  quality rather than a crash. A huge log-odds overflowed the logistic function during
  Newton's method on a nearly separated step; it is written to never overflow.
- The season model's first step is nearly decided by net rating, so a strong team's
  chance of the playoffs rounds to 100%; it is shown to a decimal with its interval
  rather than as a round number.

**Gate**

| Check | Result |
| --- | --- |
| Automated tests | 2,806 passed, none skipped; about four minutes with `pytest -n auto` |
| Data-quality checks | Unchanged: no table or check was added; the real database stands at build 13 (57 checks, 0 errors, 7 standing warnings) |
| UI review | The new page in both themes on the real data, every tab; the subject switch, the inputs, the stage selectors and the tabs clicked through in a browser |
| Architectural boundaries | `tests/architecture` passes. The stages and the model file are `domain`, the model is `modeling`, the fit on request is a `pipeline`, every chance is computed by a `service` from the file; the page computes nothing and the build applies nothing |
| Lint | `ruff check` and `ruff format --check` clean |

**Open items carried forward**

- The model's chances are a little too sure of themselves at the extremes, more so in
  recent seasons as home advantage has fallen; an era-weighted fit, or a recalibration
  estimated out of sample, is the first refinement to test.
- Top-player quality comes from a value model fitted on every season; a stricter test
  would refit it inside each window.
- The play-in is not modelled, and the season model knows nothing of the field.
  Milestone 13's simulator will put rosters through seasons; a chance given a field is
  where it would start.

## Milestone 11 - Roster optimizer (2026-10-04)

**Built**

- `domain/optimizer.py`: the request - the payroll line (cap, tax line, either apron, or
  an owner's budget) with an optional floor, the roster size, the least number of players
  who must fill each role and each position group, a least projected rating, age and
  salary limits, players locked in and left out, how many rosters to find and by how
  many players they must differ - and the outcome: the rosters, or the reasons there are
  none.
- `modeling/optimizer.py`: an exact integer programme (HiGHS, through SciPy, a new
  dependency). The objective is the sum of the parts - five slots of replacement level
  plus each player's projected impact above it for the share of a season's minutes
  projected - with the cheaper roster preferred among equals by a weight that is never
  a trade. Two budgets bind, the payroll and a season's minutes (with a stated slack,
  the rating scaled down where minutes run over); roles and groups are requirements;
  locks and exclusions fix players; a least rating that nothing reaches is dropped with
  a plain statement of the best; each roster found is cut off before the next search, so
  several distinct rosters come back best first; and when nothing can be found the
  requirement that cannot be met on its own is named.
- `services/optimizer.py` - `OptimizerService`: the pool (every player with a projection
  for the season ahead and a salary for it on file, with the latest season's roles and
  groups), the request to start from (the season's cap and roster limits, the roadmap's
  example requirements), the budget a line resolves to, the rosters dressed with names,
  payrolls against the season's lines and what each swaps against the first, and saving
  a roster into the Team Builder with its five largest projected shares in starting slots
  that suit their groups.
- The **Roster Optimizer** page: the requirements as a form, the rosters as a comparison
  and one tab each, with the model's error on every figure and a save button per roster.
  `FitService.profiles()` is public, for the groups and roles the pool reads.

**Decisions** ([0013](decisions/0013-roster-optimizer.md))

- The objective is the sum of the parts and nothing else: the fit evidence (0012) left no
  validated fit term, and contract value under a fixed budget is what the budget buys.
  Fit enters as the user's requirements, never as a score.
- Two budgets: fifteen players who each expect to play most of every game are not a
  roster anyone can play, so the players' projected minutes may exceed a season's only by
  a stated slack, and a roster that runs over is rated as if everyone played a little
  less.
- Several rosters, each distinct, best first - the roadmap's own argument, that the
  weights behind one best are assumptions.
- Salaries come only from the user's contract file; without one there is no pool, and the
  page says so. The demo lab and the tests use invented salaries, labelled as such.

**Verification**

- The solver is checked against brute force on pools small enough to enumerate every
  roster: the best under four budgets, with role and group requirements, with locks and
  exclusions, and with a least rating; a bigger budget never projects worse; among equals
  the cheaper; the payroll binds, the minutes bind and the rating says so, the floor binds
  only when asked; age and salary limits narrow the pool but not a locked player; each
  roster differs from every earlier one, the second is the best of the rest, and a pool
  that cannot give more gives fewer; every diagnosis, and the request's own refusals.
- The service on an invented league with every projected player under an invented
  contract (no cap rules, so the owner's budget), on the fixture store's nine priced
  players under 2026-27's cap, and on the fixture store without contracts: the pool, the
  defaults, each line's figure, the rosters' arithmetic and order, saving with starters
  in slots, and the fit service reading a saved roster back.
- The page: the empty states, the pool caption, the form submitted through the test
  harness with the roster size, the requirements and a lock set, the comparison and the
  figures against the service, an impossible request's reasons, a dropped rating's note,
  the invented league under an owner's budget, and saving a roster into the Team Builder.
- Mutation spot-check: 26 planted bugs in the solver, the request, the service
  and the page: 22 caught at once; one exposed a gap - the share of a season a roster's minutes cover, never pinned - closed with tests and then caught; three mutations had missed their line after the formatter rewrapped it and were caught once aimed. The harness itself needed two repairs on the way: it decoded test output in the console's code page and crashed on a curly quote, and one run stalled; it now reads UTF-8 and times a run out.
- The page in both themes on the demo lab (real projections, invented salaries) and the
  empty state on the real data; clicked through in a browser: the form filled, rosters
  found, the tabs, a roster saved and opened in the Team Builder and on the Roster Fit
  page.
- The sweep runs the new page from its start without an exception.

**Found on the way**

- HiGHS accepts a solution within a relative gap of one in ten thousand as optimal, which
  let two rosters a hair apart come back in the wrong order; the gap is set a thousand
  times tighter. The salary tie-break was lowered to a hundredth of a point per hundred
  million dollars for the same reason.
- Ten of the optimizer's tests first asked for four-player rosters, and the request
  refuses fewer than five - the right refusal.

**Gate**

| Check | Result |
| --- | --- |
| Automated tests | 2,580 passed, none skipped; about three and a half minutes with `pytest -n auto` |
| Test sensitivity | 26 planted bugs: 22 caught at once; 1 gap closed with tests and then caught; 3 re-aimed mutations caught once aimed |
| Data-quality checks | Unchanged: no table or check was added; the real database stands at build 13 (57 checks, 0 errors, 7 standing warnings) |
| UI review | The new page in both themes on the demo lab and the real data; the form, the results and a save clicked through in a browser |
| Architectural boundaries | `tests/architecture` passes. The request and the outcome are `domain`, the search is `modeling`, the pool and the budget are a `service`; the page computes nothing and the solver reads no settings |
| Lint | `ruff check` and `ruff format --check` clean |

**Open items carried forward**

- The optimizer runs on the real workspace only once a contract file for the season
  ahead is imported; until then the page says what it needs.
- The pool is players under contract. Free agents and trade targets without a salary on
  file cannot be placed; a per-player assumed salary in the request would allow it.
- A roster's projection is the parts added up; a lineup model that redistributes minutes
  among the players chosen would be the next refinement, and the same would feed the
  Roster Fit page.

## Milestone 10 - Roster fit engine (2026-10-04)

**Built**

- `domain/fit.py`: thirty-two fit measures in the roadmap's six areas - offense, defense,
  the possession battle, structure, depth, usage - and the sum of the parts, each defined
  once (key, area, method, source, the roles a count refers to) so that the table that
  stores them, the catalog that labels them and the code that computes them read off one
  list. The rotation (the ten most-used players) and the bench (the sixth to tenth) are
  written conventions.
- `modeling/fit/profile.py`: a player's profile for a season (rates per 100 possessions,
  groups, height, two positions, the value model's impact, the roles filled) and a
  roster's profile from its members and their minutes; every real team-season profiled,
  with previous-season profiles for the test. `modeling/fit/catalog.py`: the measures as
  metrics; the glossary grows to 145. `domain/tables/fit.py`: `team_fit_profiles`, a
  modeled table rebuilt by every build after the value and archetype tables, and two
  quality checks (a real team's usage rates add up to five players' worth; its players
  cover its minutes): 57 checks, from 54.
- `modeling/fit/evidence.py` and `domain/fit_model.py`: the test of whether the measures
  explain what the value model's out-of-sample predictions missed - each measure alone,
  all together, and the combined correction with each area left out - with intervals
  from resampling seasons. `configs/models/roster_fit.yaml` (the specification) and
  `configs/models/roster_fit.json` (the evidence, revision 1); `fol fit test [--write]`
  and `fol fit show`.
- `services/fit.py` - `FitService`: a real team or a built roster profiled with the
  build's own code and placed among the season's teams (percentile, rank, median), role
  coverage with who comes nearest to each role, the sum of the parts with the value
  model's error and whatever correction the evidence supports, and where the champions'
  rosters stood. `services/fit_report.py` and `fol fit report --write` for
  [research/ROSTER_FIT.md](research/ROSTER_FIT.md).
- The **Roster Fit** page: Coverage, Profile, Sum of parts, The evidence, for the
  sidebar's team or a roster built in the Team Builder. The percentile chart's axis
  title now says what the percentile is among.
- The archetype module's `measured()` takes its minutes floor as an argument, so
  profiles cover every player; `fol build` and `fol check` answer a missing
  configuration file with an error rather than a traceback.

**Decisions** ([0012](decisions/0012-roster-fit.md))

- Fit is described, not scored: measures in the roadmap's areas, each player weighted by
  minutes, placed among the season's real teams within the season. No thresholds, and a
  direction is stated only where it is unambiguous.
- Whether fit adds anything is tested beyond the sum of the parts the way the value model
  was tested: previous-season profiles so that nothing of the season predicted leaks in,
  the value model's own misses as the target, one season at a time with only earlier
  seasons to learn from, intervals from resampling whole seasons. A correction is applied
  to a roster only if the measures together leave the predictions missing by clearly
  less.
- The evidence is a versioned file gathered on request and stamped with the value model
  and the role rules it was measured against; the page and the report say when it is
  behind what the database holds.
- The sums of the parts are what fit is measured beyond, not candidates. Lineup data -
  which five played together and how they did - is the direct way to measure fit and
  remains the obvious next step.

**What the research says** (evidence revision 1; the document has the rest)

- On 510 team-seasons, 2009-10 to 2025-26, the value model's predictions missed by 2.96
  points of net rating. No measure, on its own, left them missing by clearly less: every
  change in error lies within ±0.02 of zero and none is distinguishable from nothing.
  Steals (+0.34 points per standard deviation), perimeter defenders (+0.32) and assist
  percentage (+0.22) are clear of zero when fitted on every season at once, and what they
  explain in one season does not carry to the next.
- All 27 tested measures together leave the predictions missing by *more*: 3.14 against
  2.96 (+0.18, +0.06 to +0.33), and the combined correction is better without four of its
  six areas - what fitting many weights to few seasons does when there is nothing to
  find. So no correction is applied to rosters, and "Roster Fit" will not enter the
  optimiser's objective as a validated term; role counts may constrain a roster.
- Where the champions stood: all thirty in the top third of their season on the sum of
  the parts; two in three on floor spacers, three-point accuracy, assist percentage,
  rebound percentage, the bench's impact and the top three players' usage; on free-throw
  rate, turnover percentage and the bench's creators as often below the middle as above.

**Verification**

- Each profile measure is worked by hand on made-up players: minutes weights, lineup sums,
  the rotation and the bench, shares of the profiled minutes, players without a profile,
  the top usage, reliance on one player, minutes covered. Player and team profiles are
  checked against the invented league's own tables - a team's profile against the row the
  build stored for it, a lagged profile against one assembled by hand, the league's
  impacts adding up to nothing - and the fixture store's two real teams cover their
  minutes and add up to five players' usage.
- The evidence is tested on an invented league with one thing planted that the value
  model cannot see: points of offense for every inch of last season's minutes-weighted
  height. The height measure is found strongest and clear of zero, little else is, the
  combined correction is usable and leaving out the structure area is missed. A season is
  corrected from earlier seasons only; a relation with nothing left to luck has a closed
  interval; the evidence survives being written down; too little history is refused.
- The service and the page are checked against the invented league, the fixture store
  and a built roster; the quality checks against a profiled league with each fault
  planted in turn; the pipeline and the commands on a league whose value model carries a
  test.
- Mutation spot-check: 41 planted bugs across the profile, the definitions, the
  evidence, the pipeline, the checks, the service, the report and the page: 34
  caught at once; five exposed gaps - the two-position flag checked on one player only, the roles behind each count never pinned, a standardisation that could reach the tested season through a missing value, coverage counted beyond the rotation, a chart drawing measures that have no standing - each closed with a test and then caught; two mutations had missed their line and were caught once aimed.
- The page in both themes on the real data and on a demo lab with a built roster of
  eleven real players; clicked through in a browser on both: the subject, a team, a
  season, every tab, a member row from a team and from a roster. Looking changed the
  members table, whose value columns the roles column had pushed out of view.
- The sweep runs the new page from two starts (a team; a built roster) without an
  exception.

**Found on the way**

- The test league's generator duplicates a game id when a player has two stints with
  the same team in a season (structure seed 7). The fitted-league fixture uses the
  structure the other labs use; the generator is left as it is, noted here.

**Gate**

| Check | Result |
| --- | --- |
| Automated tests | 2,517 passed, none skipped; about four and a half minutes with `pytest -n auto` |
| Test sensitivity | 41 planted bugs: 34 caught at once; 5 gaps closed with tests and then caught; 2 misaimed mutations caught once aimed |
| Data-quality checks | 57 checks on the real data (build 13): 0 errors, 7 standing warnings; the two fit checks hold on all 892 team-seasons |
| UI review | The new page in both themes, every tab, a team and a built roster; clicked through in a browser on the real data and on the demo lab |
| Architectural boundaries | `tests/architecture` passes. The measures are defined in `domain`, computed in `modeling`, stored by `pipelines`, read by `services`; the page computes nothing; the evidence is gathered in one command and applied only through the service |
| Lint | `ruff check` and `ruff format --check` clean |

**Open items carried forward**

- Fit is measured only as far as box scores and rules allow. Lineup data would let it be
  measured directly and has not been ingested.
- The evidence has to be gathered again after a new value model or a change of the role
  rules; the page, the report and `fol fit show` say which versions it rests on.
- Surplus value still waits on the user's contract file.

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
