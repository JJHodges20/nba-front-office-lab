# Full-system audit

Milestone 14 of the roadmap: a review of the whole lab against its own rules, in six
passes - architecture, leakage, tests, the workbench, documentation and performance -
with what was found, what was changed, and what was left as it is and why. Audited at
milestone 13 (commit `2b411c1`) on 2026-10-05; the changes are milestone 14's commit.

How it was done: the architecture, leakage and documentation passes were each a
read-only review of the whole code base, the leakage review re-running every backtest
with the project's own functions against a read-only copy of the database; the test,
workbench and performance passes were measured - a coverage run of the suite, every
page and tab opened in a browser in both themes, and profiles of the slow paths. Every
finding below was verified against the code before anything was changed.

## Summary

| Pass | Found | Changed | Left, and why |
| --- | --- | --- | --- |
| Architecture | No import rule broken. Two pages doing model arithmetic; five formulas living in services, one of them disagreeing with analytics; four caches that missed a refit; two dead functions; a bare `except`; an invented $100M fallback; a dead URL path on the default page. | All of these. | The value-for-money line is still fitted on request (it describes a contract file the user supplies); `wins_per_net_point` is still estimated inside a build (it converts points to wins season by season); the largest modules and the duplicated small helpers are listed, not rewritten. |
| Leakage | Every expanding window is formed correctly. The value model's test knew each season's minutes, which no forecast does; the season model was scored on the season it had just played; the shipped simulator file no longer matched the code; an in-progress season dropped its active players from the pools. | A second value-model test with the minutes projected, whose error the optimizer, the simulator and the postseason model now carry; the season model also scored from the rating predicted before the season; every model file refitted; the pool fixed. | All-season value weights still reach top-player quality and the fit measures (measured at +0.003 log loss); the simulator's own parameters are measured in sample (within a point of coverage, in the safe direction). |
| Tests | 2,958 tests, 98% of statements covered, no skips, warnings as errors; the page sweeps were the long pole, one of them ten minutes under a full run. | The slow paths underneath the sweeps; tests for every change above. | The sweeps themselves: they try every control and should. |
| Workbench | Every page and tab drawn in both themes. A dead path on the default page; one lowercase sentence; a hint that left out the rebuild step. | All three. | A wide table column on Roster Fit that scrolls. |
| Documentation | No broken link, no undocumented command, the generated documents exact. The contract import instructions omitted `fol build`; a dozen stale statements. | All of them, and the generated documents regenerated. | - |
| Performance | Warehouse reads built frames from a dictionary per row; the contract check round-tripped every integer column through floats; the simulator re-read tables per team and computed intervals a table never shows; roster-subject scenarios were never cached. | All of these. | Cold page loads are now one to five seconds; a shared read cache across calls was not added, since every page already caches on the build. |

## Architecture

The layer rules of [ARCHITECTURE.md](ARCHITECTURE.md) hold: no forbidden import, no SQL
outside `storage`, no settings loaded below `pipelines`, no fitting outside the
`fol ... fit` commands except the one noted below, no cap-sized figure in Python, no
gendered text.

Changed:

- Model arithmetic on pages. The Postseason Outlook page computed the inverse logit of
  the home advantage with a hard-coded *e*, and the report did the same; it is now a
  method of the game model in `domain`. The Scenario Simulator page subtracted two
  profile columns to make its change column; the service returns it.
- Formulas in services. A player's per-stint on/off difference was written in the player
  service while the catalog metric lives in analytics; it is one analytics function now.
  The postseason service re-derived top-player quality for a built roster; the model's
  features define it once. The roster fit service placed a team among its season's
  teams with an inline percentile, rank and median; that is a `modeling` function. The
  postseason service carried its own percentile interval, not NaN-safe, beside the
  NaN-safe helper the rest of the model uses.
- Caches that missed a refit. The four model statuses in the workbench were cached on
  the build id only, yet they key every model cache by revision: after `fol ... fit
  --write` the old model stayed on screen until a rebuild or a restart. They are keyed
  on the model files' stamps as well.
- Dead code, a bare `except Exception` on the optimizer page, a $100M fallback invented
  on the page where the service now supplies the starting budget, a qualification policy
  defined in the UI, and a date range the UI computed from a raw table.
- The League Overview is the default page and is served at the root; its `league` path
  was dead and answered "Page not found".

Left as it is:

- `services/value.py` fits the value-for-money line (salary against wins) when the tab
  opens. It describes the contract file the user supplied and is recomputed when the
  file changes; nothing is projected from it. Recorded in [decision 0016](decisions/0016-audit.md).
- Every build re-estimates wins per point of net rating season by season
  (`modeling/value/wins.py`). It converts a rating into wins for the season it is read
  in and is documented as such.
- Six modules over 800 lines (the command line, three pages, the charts, the quality
  checks) and fourteen functions over 100 lines. They are long because they lay out
  reports; splitting them is housekeeping, not a defect.
- Small helpers written more than once (`_listed`, `utc_now`, `rounded`, `_rmse`, a few
  verdict strings). Listed here so the next milestone can fold them; none disagrees.

## Leakage

Every out-of-sample claim was traced. The expanding windows of the value model, the
postseason model and the fit evidence train on seasons before the one tested; features
for a season come from the seasons before it; league normalisation uses the same
season's league, which is correct. Four things made the figures look better than the
models' real use, in order of weight.

1. **The value model's test knew each season's minutes.** It predicted a team from its
   players' projected impacts weighted by the minutes they went on to play, which no
   forecast has. Tested again with the minutes projected by the minutes model fitted on
   earlier seasons, and replacement level for the rest, the miss rises from 3.01 to 3.63
   points of net rating, the projected minutes covering 87% of the floor. The optimizer,
   the simulator and the postseason model now carry 3.63; the first test stays as the
   measure of the rating alone. The simulator's wins test, drawn around the projected
   ratings with that error, holds the wins that happened 51%, 81% and 96% of the time for
   its 50%, 80% and 95% intervals (it was 53%, 83% and 97% around ratings that knew the
   minutes).
2. **The season model was scored on the season it had just played.** It is read, on the
   Postseason Outlook and Scenario Simulator pages, for a roster before a season. Scored
   as a forecast reads it - from the rating the value model predicted before the season,
   averaged over that prediction's error, with the top-player quality typical of such a
   rating - the log loss for making the playoffs is 0.517 against 0.250 from the season
   played and 0.691 for the base rate; for the title 0.112 against 0.091 and 0.146. Every
   stage still beats its base rate. The reading is in the model file, on the page and in
   the research document, beside the other.
3. **Top-player quality comes from value weights fitted on every season.** Refitting the
   weights inside each postseason window moves the series log loss by +0.003 and the
   season stages by at most +0.002; the two versions of the quality correlate at 0.99.
   Measured, documented, left.
4. **The simulator's own parameters are measured on all seasons.** Measured with earlier
   seasons only, coverage moves by about a point, in the safe direction. Left. The
   shipped file, though, no longer matched the code: the least-known band had grown from
   1,027 to 3,942 player-seasons when players the model never valued were counted. Every
   model file was refitted in order - value, build, postseason, simulator, fit evidence -
   so that each cites the others' current revision.

A bug, not a leak: while a season was being played, the value service's pool kept only
the players who had not yet appeared in it, so the optimizer and the simulator would
have dropped every active player once the first games were in. The pool is everyone
projected into the season.

## Tests

| Measure | At milestone 13 | Now |
| --- | --- | --- |
| Tests | 2,958 | 2,969 |
| Statement coverage | 98% (14,467 statements, 306 missed; nothing under 81%) | - |
| Slowest test | the Winning Benchmarks sweep, 170 s with coverage on | - |
| Suite, `pytest -n auto` | about six minutes | about five minutes |

Warnings are errors; nothing is skipped; no test touches the real data directory. The
sweeps that try every control on every page are the long pole, and a test that seems to
hang is one of them: the simulator sweep took twenty minutes before milestone 13's last
fix and the profiling here. What was added: tests for every change in this audit - the
read memo, the intervals switch, the emptied roster, the projected-minutes test, the
before-the-season reading, the in-progress pool, the x-axis options, the deferred
tables - and the revision pins updated for the refitted files.

## The workbench

Every page, every top-level tab, light and dark, through a real browser, with the
sidebar's team and player set. Found and changed: the dead `league` path; an optimizer
empty state that began in lowercase; a Data Health hint and the command line's
post-import message that said to run `fol check` where the salary views need `fol
build`. Found and left: the Roster Fit roles column scrolls sideways in the players
table. Everything else drew as intended: tags on every page, estimates marked, intervals
where a chance is shown, the empty states where a contract file is missing.

## Documentation

Mechanically sound: every relative link resolves, every `fol` command in the documents
exists and every command is documented, the three page lists agree, and the generated
documents were byte-identical to their generators. Changed: the contract-data guide,
the README and the source register now say that an import is followed by a build; the
suite's duration, the roster fit test's span (510 team-seasons, 2009-10 to 2025-26), the
rebuild time, the fit areas, the simulator's figures, the architecture document's account
of the `modeling` layer, the catalogs and the rebuilt tables, the planned tables (two
decided against, lineups deferred), the benchmark document's limit on roster make-up,
the glossary's origin note, the filters each page reads, a like-for-like comparison in
the wins test, the regeneration order in the research headers, and the README's layout
and note on estimates. Every generated document was regenerated.

## Performance

Measured on the real database, this machine, before and after.

| Path | Before | After |
| --- | --- | --- |
| Read `player_seasons`, all rows | 2.46 s | 0.40 s |
| Read `team_games`, all rows | 5.45 s | 0.78 s |
| Read a season of `player_game_logs` | 2.5 s | 0.30 s |
| One scenario drawn before and after | 3.7 s | 1.4 s |
| The season ahead drawn for every team | 8.6 s | 1.8 s |
| Scenario Simulator, cold page load | 10.4 s | 4.9 s |
| Data Health, cold page load | 6.4 s | 1.0 s |
| League Overview, cold page load | 3.4 s | 2.3 s |

What changed: the warehouse builds frames from the row tuples a cursor returns instead
of a dictionary per row; the contract check takes an integer column as integral and a
text column as text without a Python-level pass when the frame already says so; the lab
can be asked to remember what it reads within one answer, so a season drawn for thirty
teams reads each table once; postseason intervals are computed only where they are
shown; a built roster's scenario is cached on the roster's last-changed stamp. The
rebuild (`fol build`) takes one to two minutes; `fol check` runs its 57 checks with 7
standing warnings and no error.

## Version 1.0 acceptance criteria, re-assessed

Every criterion assessed at milestone 7 still holds, with the same one open: contracts
and cap information are in the workspace as soon as a contract file is imported and the
database rebuilt, and no file had been supplied; one was, later that day. The
predictive stages that criterion 10 guarded against came in milestones 9 to 13, each
tested out of sample and shown with its interval; this audit tightened two of those
tests.

## What remains

- A contract file. Every salary, payroll, cap and value-for-money view, and the
  optimizer, wait on it ([CONTRACT_DATA.md](CONTRACT_DATA.md)). *Closed later the same
  day: the user supplied the MrBridge salary dataset, imported and built in; what that
  changed is in the development log's entry of 2026-10-05.*
- Refitting the value weights inside each postseason window, and building the fit
  measures from them: +0.003 log loss, measured, not worth the second fit today.
- A wins test that runs the simulator's own draw, players' misses included, on rosters
  as they stood before each season; the warehouse keeps no such rosters.
- The field: a league simulation with a schedule, standings, the play-in and the bracket.
- Lineups, the roadmap's deferred tables.
- Housekeeping: the long modules and the duplicated helpers above; the sweeps' length.
