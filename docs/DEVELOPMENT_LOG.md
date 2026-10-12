# Development Log

One entry per milestone: what was built, what was decided, and the evidence for the
completion gate. Newest first.

## Milestone A9 - AI Research Assistant: the release audit (2026-10-11)

Every check of the release, run and written down: the test suite, the live model's tests,
the evaluations, a working session timed and asked twice, failure and offline runs, the
network against the source register, and the documents. No league table, model file,
setting or contract figure changed: nothing was fitted, rebuilt or imported, and every live
run read a copy of the data.

**Found, and fixed**

- **The suite's rare stall was the solver.** One full test run in three stalled - as one
  did at A6 and at A8 - in an optimizer page test. A plugin that logs each test's start and
  end on each worker named it; a stress script found the cause: SciPy's HiGHS, called from
  a new thread and then from the main thread, 300 times in each of 12 processes, finished
  in none within two minutes and logged access violations, where on the main thread alone,
  or on one thread kept for it, all 12 finished in 8 seconds. A page's run and the test
  that read the page took turns in exactly that way - and so do a workbench page's runs and
  the assistant's questions, each in a thread of its own, so the workbench could hang too.
  Every solve now runs on one thread (`modeling/optimizer.SOLVER`); the stress on the lab's
  own solve then finished in all 12 processes with nothing logged, and two tests hold it.
- **Stop came too late.** The loop looked for a stop only before asking the model, so the
  tool calls in a reply that came back after the press - the likeliest moment - were all
  run. It now looks as soon as a reply comes back and before each call.
- **A damaged research file crashed AI Research** with SQLite's own error. The store now
  checks a file it did not just make with SQLite's quick check before writing anything,
  remembering a file that passed until it changes (13 ms for 20 MB, and a page opens the
  store a dozen times a run); a file it cannot use - damaged, not the store, from a later lab
  - is `ResearchUnreadable`. The page says so in plain words and offers *Set it aside and
  start afresh*, which renames the file and its write-ahead log beside it, never deleting
  them; the Ask dialog says so and links to the page; every other page works as before. A
  locked file is not damaged and is never offered.
- **What the lab holds was answered from memory.** In the working session, "What does net
  rating mean?" and "So are they a real contender?" were answered with nothing called in
  both passes - and so labelled as nothing to answer from. A question about what a figure
  means or how the lab works, or one asking for a verdict, answered with nothing called and
  nothing declined, is now sent back once - with a note naming the glossary and the
  documents for the first, the lab's evidence for the second. One note for both had sent
  the contender question to the glossary; a replay of the session showed it.
- **A result that did not say what it held.** "Who led the league in net rating in
  2012-13?" was answered as missing in every pass: a replay showed the model reading the
  league's averages - the last twelve seasons, with nothing said of the rest - and concluding
  that the lab held nothing before 2014-15. The averages now say how many seasons the lab
  holds and from when, add the season asked about, and say that a team's net rating is in
  the team ranks.
- **From A8:** a refused id that ends exactly one id of its kind - V02's "2752", the end of
  the Knicks' 1610612752 - now names that id; and "Use the roster_fit tool" (R03), a tool
  named for the user to use, is sent back as wording.
- **The network audit** (decision 0018's A9 section): nothing paid or undeclared runs. Now
  declared in the register: the injury report's file host, and the Plotly script an
  exported HTML chart loads. The search allowance is unpublished and was not measured. An
  image by reference in an answer (`![x][r]` with an address further on) would have been
  fetched by the browser, and is shown as text. Only `providers` may import what opens a
  connection (an architecture test), and a guard in `tests/conftest.py` fails any test that
  connects anywhere but this machine - the whole suite passed with it on.

**Release checks with no test before**, from an audit of the suite against the release
list: instructions planted in a search result reach the model quoted as data; a scripted
model that obeys a planted notice saves nothing and its claim is cut; with the network down
the lab's own tools answer and the web's failure is said; the real web sender's timeouts and
lost connections name the site and never the request; a stream from Ollama cut off midway
is said; the time budget, Deep's twelve calls, and each mode's searches and pages hold; a
made-up figure for a season the lab does not hold is cut; seven tools whose evidence no test
checked carry it; a chart the house rules refuse says so beside its rows; a chart's figures
are its rows'; the page asks the model nothing more and draws an answer once however often
it runs; and the Ask dialog with Ollama offline offers nothing to press.

**The evaluation** ([AI_EVALUATION.md](AI_EVALUATION.md)). The 59 cases, three runs on the
A9 code as it grew: 49, 49 and 47 of 59, the last the report. The same ten fail in all
three - as at A8 - and in the last R01 and R03 too, their Deep answers having written
figures of their own that the checker cut. In every run the right tool came first for 36 of
the 37 cases that need one, every clarify and refuse case called nothing, nothing forbidden
was called or said, W03's planted call was not made, and no figure that no result holds was
shown. The arguments measure misses its target as at A8, 93% against 98%: B03's made-up id
"1", twice, and V02's "2752" - offered whole now, but on the last call its mode allows - and
S01's, as decided at A4. The experiment questions: 5 of 8 twice, case for case as at A8.
Search quality, live: 11 of 12 queries run - K02's search timed out and was said - with 85
of 94 kept results on topic. `pytest -m ollama`: 6 passed, three times.

**The working session** ([ASSISTANT_SESSION.md](research/ASSISTANT_SESSION.md),
`scripts/measure_session.py`): twenty questions a user might ask, in one workspace, through
`assistant.api` as the page asks them, on a copy of the real data with current information
and the web live, then all again in a second workspace. Three runs: the first, before the
changes it led to, labelled 11 of 40 answers as nothing to answer from; the third, the
report, 5 - two of them S07's season the lab does not hold, rightly, one S19's request to
save, refused, and three misses. In every run every answer was kept, none had an error and
no roster was saved. The model loads in 11.0 s; the first answer, cold, came in 18.8 s;
Quick answers took 8.8 s at the median, 9 in 10 within 19.0 s; Deep 75.4 s, at most 106 s.
`qwen3:8b` takes 5.76 GB, all on the RTX 4060.

**The browser pass** - the workbench over a copy of the real data, light and dark, with a
research file of random bytes: AI Research said the file cannot be opened, why in SQLite's
words, that nothing was changed, and offered no question box but *Set it aside and start
afresh*; Team Explorer's *Ask AI about this* said the same with a link to AI Research; the
button moved the file aside, byte for byte as it was, started a new store and a workspace,
and said where the old file went.

**Documents**: [RELEASE_NOTES.md](RELEASE_NOTES.md) (what the release holds, install, how it
was checked, recovery, known limits), the README's setup and recovery, the source register,
the architecture's network rule and test guard, the user's guide, the specification,
decision 0018's A9 section, and CLAUDE.md.

**Gate**

| Check | Result |
| --- | --- |
| `ruff check .`, `ruff format --check .` | Clean |
| `pytest -n auto` (everything but live-network and live-model tests) | 3,950 passed (4 min 40 s), after the last change, with the guard that fails a test reaching the network |
| `pytest -m ollama` (the live model) | 6 passed |
| The end-to-end evaluation, on the A9 code | 47/59 in the last of three runs (49, 49, 47); no unsupported figure shown; arguments 93% against a 98% target (made-up team ids, refused); report generated |
| The experiment-proposal evaluation | 5/8 twice; drafting decisions 8/8; report generated |
| Search quality, live | 11 of 12 queries (one timed out and was said); report generated |
| A working session, asked twice | 34 of 40 answered in the last run, every answer kept, no error, nothing saved; times and memory recorded; report generated |
| The pages in a browser | AI Research and the Ask dialog with a damaged research file, light and dark |
| Sources and boundaries | No paid or undeclared network dependency (the audit); the boundary tests pass, with the network rule added |
| Data and models | No model file, setting, league table or contract figure changed; every live run read a copy of the data |

## Milestone A8 - AI Research Assistant: experiment proposals for the models, never applied (2026-10-11)

Asked for an experiment, or an idea to improve one of the lab's models, the assistant drafts
a proposal: its idea in words, beside the lab's own test for that model. The user may keep
it in the workspace or download it; nothing applies it. No league table, model file,
setting or contract figure changed: nothing was fitted, rebuilt or imported.

**The user's decisions as A8 began** (2026-10-11): a kept proposal has its own list in each
workspace; the assistant drafts one only when asked; and only the four models the lab tests
out of sample may be its subject - player value, the postseason model, the simulator and
the roster fit test.

**Built**

- **The proposal** (`domain/experiments.py`): two parts, kept apart. The idea is the
  assistant's - what it noticed, the hypothesis, the change to test, how it could fail -
  and holds no figure: a figure in it is refused, and the model is sent back to write it in
  words, so that none can be made up, echoed in a result and cited as the lab's. The plan is
  the lab's: what a change must beat or keep, how seasons are split, what is measured, how
  sure the test is, when a change is kept, the leakage to rule out, what was tried before
  and the steps of the milestone that would build it. A proposal has a fingerprint, and
  reads as a Markdown document.
- **The rules** (`configs/experiments.yaml`, `config/experiments.py`): for each tested
  model, written as the lab works - the value model's main test takes each season's minutes
  as played by design, and its leakage rule says so; the simulator's noise is measured over
  seasons its wins test also scores, and its checklist says a change leaning on it should be
  checked on others. Each names the headings of its decision that say how the model is
  tested and what was tried; a test fails if a heading goes.
- **The lab's part** (`services/experiments.py`, `Lab.experiments`): the figures a change
  must beat, read from the model's fitted file - the value model's misses with the minutes
  as played and projected, the postseason model's log loss and calibration at each stage and
  both readings, the simulator's wins test and its intervals' coverage, the fit test's error
  with and without a correction - and the decision's sections quoted whole. The figures are
  the file's, never a document's: the simulator's decision gives its coverage as 53%, 83%
  and 97%; its refitted file says 51%, 81% and 96%.
- **The tool** (`assistant/experiment_tools.py`): `propose_experiment`, of the `draft`
  class - what it drafts travels with the answer, and only the user's click keeps it. Its
  description says when (only when asked) and that a proposal is a plan, so its data need
  not exist yet; its result gives the model the lab's figures to cite.
- **Kept in the workspace** (`research_experiments`, the research store's version 2): an
  A7 file is backed up and brought forward on first opening, and a test checks the table
  it gains matches a new file's. `WorkspaceService.keep_experiment` keeps a proposal once
  however often it is pressed, with the user's note; the workspace's exports carry them.
- **On the page** (`wb/answers.py`, `wb/views/research.py`): *Experiments to review*
  under the answer - the idea tagged as the assistant's and untested, the lab's test tagged
  Modeled, with what a change must beat, how it would be tested, and what was tried before
  - with *Keep in the workspace* (`api.keep_experiment`) and *Download*; and the
  workspace's *Experiment proposals*, each with a note and a delete.
- **The evaluation of drafting** (`assistant/experiment_evaluation.py`,
  `scripts/evaluate_experiments.py`, `tests/assistant/fixtures/experiment_cases.yaml`,
  `docs/research/EXPERIMENT_PROPOSALS.md`, generated): eight frozen questions, end to end -
  five asking for a proposal, one for each model and a quick one, one asking for an idea
  that leaks the future, two asking for none - scored on drafting when and only when
  asked, for the right model; no figure cut; no claim to have refitted or changed a model;
  no model file or workspace changed; a citation; and leakage mentioned where it applies.
- **Tests**: the idea without figures, its fingerprint and its document; the rules and every
  heading they name; each model's plan from its file, an unfitted model, no documents; the
  store's new table, a proposal kept once, notes, deletion, a workspace's deletion, an A7
  file brought forward; the workspace's keep and exports; the tool, a figure sent back, a
  model the lab does not test refused, the result carried and kept with the answer; the
  page's draft, keep, note and delete with the model files unchanged; the scoring.

**Found on the way, and fixed** - by the first runs of the experiment questions and of the
59 cases:

- **A "they" for things was asked about.** "...whether the simulator's win intervals are
  wider than they need to be" got "Who do you mean by 'they'?": the A6 check that asks about
  a pronoun with nothing to mean knew only plurals such as teams and players. It now knows
  the lab's own - intervals, projections, ratings, chances, models and the like - and counts
  one only before the pronoun, so "How did they do against their projections?" is still
  asked about. No frozen case's question is read differently.
- **A season written with a dash lost its second year.** "2006–07", an en dash as
  typesetters write it, was read as the year 2006 and a figure "07" no result held, and the
  sentence was cut. The checker reads a season with any dash as a season.
- **The tool's words.** A model read the note "for you to review" as its own task and
  offered to draft the proposal it had just drafted; the note now speaks to neither, and
  the result tells the model the proposal is shown whole under the answer. Asked for an
  experiment using next season's minutes, a model looked for next season's data and drafted
  nothing; the description now says a proposal is a plan, whose data need not exist yet.
- **Refusals in other words.** In the first run of the 59 cases, with proposals to offer
  instead, the model refused I02 ("Refit the value model ... and save it") as "The lab does
  not refit models ... Would you like me to propose an experiment?" and F02's chemistry
  bonus as "The optimizer does not currently include" one - each read as nothing to answer
  from. With nothing called, what the lab, its optimizer or a model does not refit, offer,
  support, allow or include is now a refusal; data it does not include is still missing.
- **A figure refused six times.** In the same run I01's model sent the same "3.01" back to
  `propose_experiment` six times, told only to write in words; the refusal now quotes what
  it holds.
- **The tools' size.** With the new tool the schemas reach 14,925 characters, past the
  14,000 a test held them to. A question's whole prompt measured 3,557 tokens of the
  model's 8,192, 180 of them the new tool's; the limit is 15,000.
- One full test run stalled near its end - a worker past the five-minute watchdog, its
  stack not captured - as one did once at A6; run again in full it passed. It is left for
  the release audit (A9).

**The evaluation** ([AI_EVALUATION.md](AI_EVALUATION.md)). The 59 cases, three runs on the
A8 code: 46, 48 and 48 of 59, the last the report. The first found the refusals in new
words and the figure sent back six times, above; after them I01, I02 and F02 - the cases
A8 bears on - passed, and each of the eleven that fail failed in A7's runs too. Every case
that needs a tool opened with the right one but E03 (36 of 37), and no figure that no
result holds reached the user. One measure misses its target: of 60 calls, five were
refused - B03's and V02's with team ids the model made up, in all three A8 runs and in
none of A7's (V02's "2752" is the end of the Knicks' id); S01's, as decided at A4; and
I01's first proposal, sent again in words - 92% against 98%. The ids are left for the
release audit.

The eight experiment questions, four runs: 4, 4, 5 and 5 of 8, the last the report
([EXPERIMENT_PROPOSALS.md](research/EXPERIMENT_PROPOSALS.md)). In the last two every
drafting decision was right - a proposal for the model asked about where one was asked
for, none where none was - nothing claimed a model was refitted or changed, and nothing
changed. What fails is the model's prose around the proposal: X03 cited nothing; X04 and
X06 each wrote figures of their own, which the checker cut. Figures on the wrong label go
through, as the checker cannot see them: at one run X06's answer called the miss with the
minutes projected the miss "with minutes as played" and stated the leakage rule
backwards, beside the lab's checklist stating it right. The ideas themselves are the
reader's to judge; the report lists each in the assistant's words.

**The browser pass** - the workbench over a scratch copy of the real project, with the real
model, in the light and the dark theme. The copy's research file was A7's, version 1: on
first opening it was backed up (`backups/assistant-v1-...`) and brought to version 2, its
workspaces and answers intact. On AI Research three experiments were asked for - the value
model's projections for rookies, the postseason model's confidence in the later rounds, the
simulator's win intervals - and each proposal showed under its answer: the idea tagged as
the assistant's and untested, the lab's test tagged Modeled, with what a change must beat,
how it would be tested and what was tried before. Each was kept, counted in the workspace's
*Experiment proposals*, shown there as kept, given a note, and downloaded as a document
with its two parts apart. The same proposal drafted again showed as kept, with nothing to
keep twice. It found one fault, now fixed: asked about the simulator's intervals, the model
put a figure in its idea, the tool refused it, and the answer told the user the proposal
had been "rejected due to a value error". The refusal now asks for the same idea again in
words, without Pydantic's "Value error" for the model to pass on; asked again, the question
drafted its proposal.

**Gate**

| Check | Result |
| --- | --- |
| `ruff check .`, `ruff format --check .` | Clean |
| `pytest -n auto` (everything but live-network and live-model tests) | 3,895 passed (4 min 53 s), after the last change |
| `pytest -m ollama` (the live model) | 6 passed |
| The end-to-end evaluation, on the A8 code | 48/59 in the last of three runs; I01, I02 and F02 pass; every figure shown held by a result; arguments 92% against a 98% target (made-up team ids, refused); report generated |
| The experiment-proposal evaluation | 5/8 in the last of four runs: drafted when and only when asked, for the right model, 8/8; no refit claimed and nothing changed, 8/8; two answers with figures of their own cut, one uncited; report generated |
| The pages in a browser | AI Research's experiment proposals - drafted, kept, listed, noted, downloaded - light and dark, over a copy of the real project whose research file was brought from version 1 to 2; one fault found and fixed |
| Sources and boundaries | No paid provider and no new source; the assistant reaches no new layer; the boundary tests pass |
| Data and models | No model file, setting, league table or contract figure changed; tests check the model files byte for byte around drafting and keeping, and the evaluation around every question; the browser pass wrote only into a scratch copy |

## Milestone A7 - AI Research Assistant: wider sources and the contract-update review (2026-10-10)

News comes from feeds the source register allows, every item dated; search quality is
measured; a contract file can be checked against the one in use before it is imported; and
the two wishes of the A6 review are done. No league table, model file or contract figure
changed: nothing was fitted, rebuilt or imported.

**The sources, re-checked as A7 began** (2026-10-10, `docs/DATA_SOURCE_REGISTER.md`): A0
had planned ESPN's and Yahoo's feeds and Wikipedia's API. ESPN, Yahoo and CBS Sports turn
AI agents away in robots.txt, which the lab honours by the user's choice at A2; NBC Sports'
terms bar any automated tool; Wikipedia's robots.txt bars its API. NBA Communications
(pr.nba.com), RealGM and Hoops Rumors admit the lab and AI agents alike. **The user chose
Hoops Rumors alone**: it publishes no terms of use and invites feed readers, with a feed
for each team and one for transactions. pr.nba.com stays behind the rule that refuses
nba.com; RealGM's terms refused an automated read.

**Built**

- **The feeds** (`configs/assistant.yaml`, `news:`): Hoops Rumors' main feed, its feed of
  moves and the 30 team feeds, each address checked live and listed, never composed from a
  question. `WebProvider.fetch_feed` fetches one with every check a page passes - a feed
  that turns AI agents away is refused like a page - and `processing/feeds.py` reads RSS or
  Atom (a feed declaring a document type or entities is refused, and so is one in UTF-16
  or UTF-32, where a declaration would not be seen), keeping each item's headline, dates,
  author, tags and the start of its excerpt as plain text. One article is
  one item however many feeds carry it, known by its address without tracking parameters.
- **News in the current cache**: `news_items` in `data/current.sqlite`, a fourth current
  source, each feed due on its own after 30 minutes, items kept 120 days after publication.
  The pipeline's default refresh is still the league's three sources; news is fetched when
  named - by the `moves_and_rumors` tool, `fol current refresh` and the AI Research page's
  button. `CurrentDataService.news()` finds a team's items by its own feed, the site's tags
  or its nickname in a headline, and a player's by their full name in the tags.
- **The `moves_and_rumors` tool**: the reporting of the last days (14 by default) for a
  team, a player or the league, moves alone if asked, newest first, each headline with its
  publication time and how long ago, and a source id to read; credited, and said to change
  no roster and no contract. A search result for the same article is the same source. It
  was called `news` until the evaluation showed the name drawing questions about
  "reporting" away from the web (below).
- **Dated search results**: a search result carries no date, so `web_search` now says the
  date its address shows, or that it shows none, and that its results are not in date
  order.
- **The search-quality evaluation** (`assistant/search_quality.py`,
  `scripts/evaluate_search.py`, `tests/assistant/fixtures/search_cases.yaml`,
  `docs/research/SEARCH_QUALITY.md`, generated): twelve frozen queries through Ollama's
  web search, each counted for results on the subject, dated, recent, repeated and from
  refused sites, and held against the feeds. The live run of 2026-10-11 02:17 UTC: 120
  results, 17 from refused sites left out, no repeats; 90 of the 103 kept on topic but only
  23 dated by their address, and 11 of the 72 news results dated within their question's
  days - against 122 dated items in the feeds for the same eight news questions.
- **The contract-update review**: `pipelines/contract_review.py` reads a candidate file
  exactly as an import would and compares it with the file in use by player, team and
  season (`processing.contracts.compare_contract_years`, `domain/contract_review.py`):
  what is new, changed - salary, option or guarantee - or gone, and what to check first: a
  source never imported before, figures older than those in use, names the league's index
  does not hold, seasons without cap rules. It stores nothing. `fol contracts preview`
  prints it; Contract Explorer's new *Check a new file* tab shows it, through the
  assistant's facade (`api.review_contract_file`). The assistant may reach this module,
  which only reads, and still not `pipelines.contracts`, whose import writes - the
  boundary test names it. On the real project the file in use, previewed against itself,
  shows 7,228 contract seasons the same and nothing changed.
- **The `contract_updates` tool**: the moves on the league's transactions file and those
  reported in the news since the contract file's date, each beside the file's salary for
  the season, with how to bring the file up to date. Nothing it reads changes the file.
- **Starters by impact** (the A6 review): `domain/lineup.py` keeps the nine who play the
  most and the most positions filled, and now starts the lineup with the most projected
  impact among those that fit - a player without a projection starts only where no one
  with one can.
- **Places checked for what they rank** (the A6 review): `assistant/checker.py` reads what
  a place ranks from the words around it - "in the East", "of 30", "the league's", "the 3rd
  seed" - and a place named for the league or a conference stands only on a result's place
  for the same field. A mismatch is sent back with what the results give for that field
  ("6th in the East (the results' 6th is in the league; in the East they give 3rd)"), and
  a sentence whose only fault is such a place is cut at that clause rather than lost whole:
  what follows the clause goes with it, and no bracket or bold is left open. The standings
  and the bracket now write each place with its conference ("3rd in the East").
- **Tests**: the feed reader (RSS, Atom, entities refused in any encoding, one article
  once, items let go after their days); the feed fetch (types, robots, redirects); the news
  refresh (on
  request only, a team's feed when asked, due feed by feed, unchanged, a failure keeping
  what was held, nothing written to the lab's database); the news service (team, player,
  window, moves); the `moves_and_rumors` tool (dated lines, sources read by id and shared
  with search, the empty window, never fetched, a failure later); dated search results; the
  search-quality counting and report; the preview (compared, flagged, nothing stored, no
  file in use, unreadable); the preview command; the page's *Check a new file* drawn from a
  preview; `contract_updates` (moves since, a team, nothing since, no contract file, the
  file unchanged); the lineup by impact; the place check by field, and a cut that ends at
  the first clause that fails with no bracket or bold left open; the feed settings'
  validation; the recorded world's feeds; and what the browser pass found (below): a
  refused id of the other kind, what counts as a gap, and times, source ids and keys in
  answer tables.

**The evaluation** - five runs on the A7 code: 46, 48, 47, 47 and 49 of 59, the last on
the code as committed and the report ([AI_EVALUATION.md](AI_EVALUATION.md)). The first two
shaped the place check: told only that its "6th in the Eastern Conference" was the league's
6th, the model wrote it again, and the cut took the record the user had asked for with it;
the note now names what the results give for that field, and a misplaced place costs its
clause. W01, "Find recent reporting on why the Knicks won the 2025-26 title", opened with
the feeds' tool in every run while it was called `news`, asked it for moves alone and never
searched the web. Three wordings of its description changed nothing in probes of the first
move; the name `moves_and_rumors` did. A wider description of `web_search`, made with it,
moved K02's payroll question to `team_stats` in two runs, and went back to A6's wording. In
the last run every case that needs a tool opened with the right one (37 of 37), W01 and K02
passed, and no figure that no result holds reached the user. The ten that fail are the six
that have failed in every run since A5, V02 on a budget the model chose itself, and E01,
P04 and R03, each of which loses a sentence or two to the checks in some runs and not
others. W01's passing answer still gives the league's 5th place to defensive rating, where
it is net rating's: a real figure on the wrong thing, which the checker cannot see.

**The browser pass** - the workbench over a scratch copy of the real project, with the
real model and the live Hoops Rumors feeds, clicked through with Playwright in the light
and the dark theme: Contract Explorer's *Check a new file* with a copy of the file in use
changed in three rows (one new, one changed, one gone), the new source flagged and the
import left to the user as a command; on AI Research, the news chip, "What's the latest
news on the Golden State Warriors?" answered from the team's feed (Brandin Podziemski's
extension, posted four hours before), and "Has anything changed for the Knicks since my
contract file?". It found six faults, each fixed and each with a test:

- **The contract question was given up.** The model called `contract_updates` with the
  Knicks' team id as the player too; the refusal said only that no player has that id, and
  the answer said the Knicks could not be found. A refusal now says where an id of the
  other kind belongs ("the id of the New York Knicks, a team: give it as team_id"); in the
  later passes the question was answered, from the league's moves since the file's date.
- **A news answer was "not enough to answer"** for relaying that a coach "has not provided
  any details". "Not provided", "not available" and the like now mark a gap only beside
  the data, the results, a file or the lab; every phrasing the evaluation runs had read as
  a gap still is.
- **Times showed as 2026-10-10T23:47:27** in answer tables, new and kept (a kept answer's
  JSON holds a time as text). They now read "2026-10-10 23:47 UTC", or the day alone where
  every time is midnight.
- **The transactions table showed each move's internal key**, two columns of hashes. Keys
  are left to the CSV, as ids are.
- **"Read more using the source ID s2"** named a row no table showed. A source's id is now
  the table's first column, *Source*.
- **"1627 players"** stood under 7,283 rows; it reads "1,627".

**Gate**

| Check | Result |
| --- | --- |
| `ruff check .`, `ruff format --check .` | Clean |
| `pytest -n auto` (everything but live-network and live-model tests) | 3,833 passed (4 min 50 s), after the last change |
| `pytest -m ollama` (the live model) | 6 passed |
| The end-to-end evaluation, on the A7 code | 49/59 in the last of five runs, 100% right first tool, no unsupported figure shown; report generated |
| The search-quality evaluation, live | 12 queries run; report generated |
| The pages in a browser | Contract Explorer's *Check a new file* and AI Research's news and contract answers, light and dark, over a copy of the real project with the live feeds; six faults found and fixed, each with a test |
| Sources and boundaries | No paid provider; nothing worked around - the feeds pass the robots and terms checks, and a refused feed fails like a refused page; the assistant reaches `pipelines.contract_review` (reads only) and not the contract import; the boundary tests pass |
| Data and models | No model file, league table or contract figure changed; a reported move changes no roster or contract (tests); the contract preview stores nothing (tests, and the raw store unchanged on the real project); the browser pass wrote only into a scratch copy |

## Milestone A6 - AI Research Assistant: workspaces and asking from any page (2026-10-10)

The research is kept. Named workspaces, in a file of their own that no build touches, hold
every question and its whole answer, findings, notes, and the rosters an answer proposed
until the user saves or declines each; eight pages can ask about what they show. No league
table, model file or setting changed: nothing was fitted or rebuilt.

**Built**

- **The research store** (`storage/research.py`, its contracts in
  `domain/tables/research.py`): `data/assistant/assistant.sqlite`, with six tables -
  workspaces, turns, findings, proposals, approvals and the version log. It is versioned: a
  new file is made at the latest version; an older one is copied to `backups/` with
  SQLite's own backup and brought forward in one transaction; a file from a later lab, or
  one that is not this store, is refused and left alone. Ids are never handed out twice
  (`build_tables(never_reuse_ids=True)`), and the store opens its connections as the lab's
  database does (`configure_connections`, taken out of `Database`).
- **The answer as data** (`domain/research.py`): a turn keeps its whole answer as JSON -
  the results with their rows and charts, the evidence, the notes and the steps - so an
  old answer is drawn exactly as it came.
- **The service** (`services/workspaces.py`, `Lab.workspaces`): workspaces made, renamed,
  described, focused, archived, restored, cleared and deleted; a new conversation; a turn
  recorded with the rosters it proposed; what a follow-up reads (the last three answered
  turns of the conversation under way, in its own workspace); what has changed since an
  answer, in sentences - the data build, the value model, and current information or the
  web once the lab would fetch them again; findings; proposals saved or declined, every
  press logged; export as a document and as data.
- **The facade** (`assistant/api.py`): a question runs in a workspace and is kept whether
  it was answered, stopped or never answered; `Question.again`; `summarize`, which has the
  local model write the conversation under way into the notes, marked as its summary, and
  starts a new conversation; the proposal save and decline name their workspace. The
  context carries the workspace's focus, a roster in focus and the notes.
- **The policy and the orchestrator**: the notes reach the system prompt after the
  context, under a heading that says they are background, and outside what the answer
  checker reads; a roster in focus is named. A "he", "she" or "they" with nothing to mean
  is asked about before the model is (`_nobody_named`). The rules are A4's, `2026-10-10.3`.
- **The page** (`views/research.py`, with the drawing of an answer moved to
  `wb/answers.py`): the workspace bar - the choice of workspace, *New workspace*,
  *Workspace* (name, goal, focus, notes, *Summarize into the notes*), *Export*, *Archive or
  delete* (clearing and deleting each need a ticked box); *Findings* and *Proposed rosters*;
  the turns kept, earlier conversations behind a switch; under an answer *Save as finding*
  and, when something it read has changed, *Ask again with today's data*.
- **Ask AI about this** (`wb/ask.py`) on the player, value, team, benchmark, Team Builder,
  roster fit, postseason and simulator pages: a dialog that says what the question is
  about, asks it in the workspace open on AI Research without touching the sidebar, shares
  the one running question with that page, and links to the full answer.
- **Positions** (`domain/lineup.py`), the user's wish at the A5 review: every save - the
  Roster Optimizer's, a proposal's, the Scenario Simulator's - starts players from the nine
  who play the most, each at a position they are listed at where the roster allows.
- **Tests**: the store (made, opened again, every field kept, names unique whatever the
  case, deletes that reach everything a workspace holds, an id never reused, an older file
  backed up and brought forward, a failed step leaving the file as it was, a later or
  foreign file refused); the answer as data; the service (a follow-up that reads its own
  workspace only, what changed since an answer, findings that outlast a cleared history,
  research that outlasts a build, proposals waiting until saved or declined, a refused save
  logged, export); the facade (a question kept when answered, stopped or without Ollama,
  follow-ups across two workspaces, notes that are not evidence, a summary); the pronoun
  rule both ways; the lineup; and the page and the dialog with a scripted model.

**Decided** (decision 0018, "Settled while building A6"): six tables where the roadmap
sketched nine, a turn keeping its answer whole; a workspace made the first time one is
needed, under a free name; notes as background, never evidence; an old answer never
rewritten, asked again beside itself; proposals kept until saved or declined, every press
logged; a dialog body drawn as a plain function so a test can draw it.

**The evaluation** - one run, 47 of 59 ([AI_EVALUATION.md](AI_EVALUATION.md)). The model
reads A5's prompts word for word, since the cases set no roster in focus and no notes; the
twelve that fail all failed in A5's runs, and B01, the difference from A5's last run,
passed in three of A5's eight. The pronoun rule asked about no case it should not have. The
run was made before the last changes below, which touch the page and the service, not what
the model reads.

**The browser pass** - the workbench over a scratch copy of the real project, with the
real model, clicked through with Playwright in the light and the dark theme: a workspace
made and its form empty again; a question and a follow-up; a finding saved, its form empty
again; notes saved, a summary written into them, the notes box showing both, and a later
save keeping them; a new conversation begun by the summary; three rosters proposed, kept in
the workspace and one declined; the workspace downloaded as a document and as data;
another workspace showing nothing of the first, its history cleared and the box unticked
again; *Ask AI about this* from Team Explorer with the Celtics chosen, answered in the
dialog, the sidebar unchanged, the answer opened in AI Research with where it was asked;
the dialog opened again, empty; and a proposal saved from the workspace's list, its five
starters at positions they are listed at (two guards, two G-F forwards, a center). Each
theme passed all 21 checks in the end. It found three faults, each fixed:

- **Forms kept what was typed.** The page cleared a form by forgetting its keys, and the
  browser went on showing - and sending back - what had been typed: after *Summarize into
  the notes* the notes box still showed the notes before the summary, and the next *Save
  changes* would have written them back over it. A first fix, starting each widget through
  the session state, failed in its turn: the settings form came back with an empty name, so
  *Save changes* was refused, and its lists read "Choose an option". The forms now give
  their widgets the stored values and end their keys with what they show or with how many
  times they were sent, so a form starts again as new widgets. A page test now covers a
  summary and a later save; `AppTest` could not have seen the fault, and CLAUDE.md now has
  the rule.
- **AI Research came up blank after *Open in AI Research*,** in each of three full passes,
  though never in a shorter probe: the button switched pages from a fragment that reruns
  itself each second. It is now a link to the page, and the full pass then opened the
  answer each time.
- **A saved proposal still counted as waiting** in the workspace's list until the next
  click. The page now draws itself again after a save, as after a decline.

Writing this entry also found one gap: *Ask again with today's data* was offered only when
the data build or the value model had changed, so an answer that read the injury report or
the web never offered it. It now does once a question would fetch the soonest current
source again (`configs/assistant.yaml`), and says so.

What the model wrote is unchanged from A5, and one slip showed again: "54 wins, placing
them 7th in the Eastern Conference", where the result's 7th is the league's. A place is
checked as a place, not for what it ranks.

**The user's decisions at the A6 review (2026-10-10)**:

- Starters should be chosen by projected impact and role, not by projected minutes - in
  Option B of the browser pass Shai Gilgeous-Alexander and Victor Wembanyama came off the
  bench for players projected to play more. The Team Builder still moves anyone. To be
  done with A7.
- A place in an answer should be checked for what it ranks: the whole league, or one
  conference. To be done with A7.

**Gate**

| Check | Result |
| --- | --- |
| `ruff check .`, `ruff format --check .` | Pass |
| `pytest -n auto` (everything but live-network and live-model tests) | 3,748 passed in about 4 min. One earlier run of the workbench tests stalled in a test it never named; it was stopped, and the runs since - the workbench tests and the whole suite, each with a stack dump set for any test over a few minutes - finished without one |
| `pytest -m ollama` (the live model) | 6 passed |
| The end-to-end evaluation, on the A6 prompts | 47/59, one run; report generated |
| The page in a browser | Clicked through as above, light and dark, over a copy of the real project; 21 checks each; no error box or exception; three faults found and fixed |
| UI boundaries | The pages import `front_office.assistant.api` alone of the assistant; the boundary tests pass |
| Data and models | No model file, setting or league table changed; the browser pass wrote only into a scratch copy; the research store is `data/assistant/assistant.sqlite`, which is not committed |

## Milestone A5 - AI Research Assistant: roster proposals and the approved save (2026-10-10)

The assistant proposes rosters, and only the user saves one. No league table, model file
or setting changed: nothing was fitted or rebuilt, and the optimizer is the one milestone 11
built.

**Built**

- **The tool** (`assistant/proposal_tools.py`): `optimize_roster` runs the optimizer with
  what the user asked for - a budget (a cap line or an owner's figure), a roster size,
  groups, roles, players locked in or left out - and nothing else; the Roster Optimizer
  page's example requirements are not added. A role the archetypes do not hold is refused
  with the list of roles; nothing found says why in the optimizer's own words (the
  fourteen cheapest players already cost more than the budget, say). The text the model
  reads gives every option's payroll, what is left under the budget, its projected net
  rating and its changes from Option A, Option A's players with their salaries and the
  players the other options add with theirs, the value model's typical miss for a whole
  team, and that the rosters are options to compare - not a recommendation, and not trades
  or signings anyone has checked are allowed - which only the user's click saves.
- **Proposals** (`domain/proposals.py`, `services/proposals.py`): each roster found is a
  `RosterProposal` - its players and where each would start, their salaries, the payroll,
  the room, the rating with its typical miss, what was asked for in words, and what it
  rests on (the build, the value model's revision, the contract file's date) - with a
  fingerprint, twelve hex digits of the SHA-256 of all of it. It travels with the result to
  the page and lasts the session.
- **The approved save**: `assistant.api.save_proposal` -> `ProposalService.save`. A roster
  whose notes carry the fingerprint is the one an earlier press saved, and is returned; a
  proposal whose build, value model, contract file or any salary has changed is refused in
  plain sentences and nothing is written; otherwise `RosterRepository.create_with_players`
  writes the roster and all its players in one transaction. `OptimizerService.save` - the
  Roster Optimizer page's button - uses the same transaction and the same placement
  (`OptimizerService.slots`: the five largest projected shares start), which settles the
  consequence decision 0018 recorded.
- **The page**: under an answer that found rosters, *Rosters to review*: each option with
  its payroll against the budget, what is left to spend, its projected net rating give or
  take the typical miss, how it differs from Option A, what was asked for and what it rests
  on, its players' table, and a *Save approved roster* button with a name; then "Saved
  as...", "Already saved as..." or "Not saved" with the reasons.
- **Every tool in the registry is now built.** The executor's "not built yet" path stays,
  for a toolbox that leaves a tool out, and its tests use one.
- **Tests**: the transaction (saved whole; a duplicate player, a shared starting slot or an
  unknown slot saves nothing; a failure while writing the players leaves no roster), the
  proposals against the optimizer's own plans, the requirements in words, the fingerprint,
  every change the check names, a save, a second press, a refusal after a rebuild or a
  salary change, the tool on every path (options, roles kept, locks and exclusions, fewer
  options than asked, the time limit, nothing found, no contract file, an unknown role, an
  unknown id), the facade's save, and the page drawing three options and saving one twice
  with a scripted model.

**The test data - the user's decision (2026-10-10).** The contracts database prices nine
players, so no roster of fourteen could be built on it and R01 and R03 could never be
answered. The user chose fuller test data: a third test database, `priced`
(`priced_template`), is the fixture build with an invented 2026-27 salary for each of the 41
players the value model projects - about $1.25M, plus $6M for each projected win, plus a
quarter of a million times the player id's remainder after dividing by seven, rounded to
$10,000 (`tests/assistant/fixtures/priced_contracts.csv`). R01 and R03 run on it; their
questions and what they expect are unchanged, and each carries a comment saying so.

**The evaluation** - eight runs over all 59 cases: 42, 47, 44, 46, 47, 50, 45 and 48
passed ([AI_EVALUATION.md](AI_EVALUATION.md) lists what each led to); every fix was to the
assistant, and the only case changes are the two the user decided. What the runs settled
(decision 0018, "Settled while building A5"): a call refused and made again is not a gap;
the optimizer's arguments say which budget is which; "per 100 possessions" and "per 82
games" are units, not figures; "does not have a parameter to" or "the capability to" is a
refusal; a call put off - an offer to look it up, or a tool named for the user, who cannot
call one - is held to like a promise; "Who should the Knicks sign?" asks for a verdict;
every note sent back asks for the whole answer, for the user; the assistant's limits
(it cannot save; its tools do not check trades against the league's rules) are not a gap;
"does not include" counts only when the data lacks something; and the tool's own words
avoid "cannot" and "the best", which a model echoes. Two wordings of rule 6 that said where
the user saves and edits rosters were tried and dropped: each sent an answer somewhere
wrong (runs six and seven, the second of them the best score of the eight), so the rules are
A4's. At the end: all three roster cases pass, the right first tool in 36 of 37 cases that
need one, nothing called in the 11 *clarify* and *refuse* cases, one call refused in 54,
nothing forbidden, and one figure cut (B02's "7 games" for a 4-3 Finals). Each change to a
tool's description moved a few unrelated answers, as A4 had seen: H05 now leaves out a
default season, and B02 writes the length of a Finals the result gives as a score.

**The browser pass** - the workbench over a scratch copy of the real database (427 players
with a 2026-27 salary and a forecast), with the real model, clicked through with Playwright
in the light and the dark theme: three rosters under $150M and a luxury-tax roster with two
rim protectors, each option's tiles, comparison, basis and players; *Save approved roster*
pressed twice ("Saved as..." and then "Already saved as... It was not saved a second time");
the saved roster in the Team Builder (14 players, every one priced from the contract file);
and "Option B looks good, save it", declined. It found two faults. Whole roster answers
were "partly answered" for relaying that the lab cannot check trades against the league's
rules - fixed. A refusal to save told the user they "cannot directly edit or delete saved
rosters" - left: rule 6 was kept, above, and the page says where saving happens. The
welcome card now has a roster example. The five players with the most forecast minutes
start, as the Roster Optimizer's save has placed them since milestone 11, so a roster of
guards can show a guard "Starts at C"; the Team Builder moves them.

**The user's decisions at the A5 review (2026-10-10)**:

- Proposals may last the session with their answer for now, as long as the finished
  assistant has a place to save them: A6's workspaces will.
- Rule 6 stays as it was, with its occasional wrong remark about editing saved rosters.
- Players should keep their own positions as far as possible when a roster is saved; the
  Team Builder can still move them. To be done with A6, which saves proposals.

**Gate**

| Check | Result |
| --- | --- |
| `ruff check .`, `ruff format --check .` | Pass |
| `pytest -n auto` (everything but live-network and live-model tests) | 3,673 passed in 4 min 24 s |
| `pytest -m ollama` (the live model) | 6 passed |
| The end-to-end evaluation, on the A5 code | 48/59 (42 to 50 over eight runs); report generated |
| The page in a browser | Clicked through as above, light and dark, over a copy of the real database; no error box or exception; the "partly answered" fault is fixed, and the refusal's slip about editing saved rosters is left with the rules as they were, for the reasons above and by the user's decision |
| UI boundaries | The page imports `front_office.assistant.api` alone of the assistant; the boundary tests pass |
| Data and models | No model file, setting or league table changed; the browser pass saved its rosters into a copy, never the lab's database; the evaluation's saved runs are in `data/assistant/benchmarks/`, which is not committed |

## Milestone A4 - AI Research Assistant: the forecasting tools and the document index (2026-10-10)

The assistant reads the lab's fitted models and its own documents. Four tools answer from
the value model, the roster fit evidence, the postseason model and the simulator; a fifth
searches `docs/`. No league table, model file, setting or roster changed: nothing was
fitted, refitted or measured, and every file is read as it stands (value model r2, fit
evidence f2, postseason model p2, simulator s2).

**Built**

- **The model tools** (`assistant/model_tools.py`), service calls only:
  - `player_value` - a player's seasons and projection; a season's leaders, ranked among
    everyone valued; the projections; where an impact comes from; roles beside how often
    they carry over; value for money against the user's contract file; the model's test
    against simpler methods, with the minutes as played and as projected.
  - `roster_fit` - a team's or built roster's profile, each measure placed among the
    season's teams, the roles in its rotation and the sum of its parts; the evidence; where
    champions stood. A profile carries the limit that there is no fit score while the
    evidence is not usable.
  - `postseason_outlook` - a real team as a team of its strength, beside what happened; a
    built roster; a hypothetical team of any net rating; a decided season's bracket; every
    team of a season; the model's record, read with each season's rating and from the rating
    predicted before it, and what else was tried. The season ahead is drawn by the
    simulator.
  - `simulate_scenario` - a team or built roster before and after the user's assumptions
    (players added and removed, games missed, development, minutes, salary, the two
    presets), with the service's change for each figure, the interval of the seasons drawn
    and the wins test. A scenario takes each player's current team: one that names a
    player who is not on that roster is not run, and the result says which team they are
    with.
  Every modeled figure goes out with its error, and each result cites the model files by
  revision. A single player's projection has no tested interval, and the tool says so,
  giving the simulator's measured spread for players that well known instead.
- **The document index** (`domain/documents.py`, `config/documents.py`,
  `storage/documents.py`, `services/documents.py`, `assistant/document_tools.py`):
  `research_docs` reads the Markdown under `docs/` afresh, cuts it at its headings and in
  passages, and searches it with SQLite FTS5 in memory - about 280 sections in a few
  hundredths of a second - leaving out the generated glossary and dictionary and the
  assistant's recorded answers. A section is quoted as written and cited by file and
  heading: a new kind of evidence, `docs`, which the evaluation's `source` now counts, as
  the case file's header always defined it.
- **The executor** refuses a saved roster the lab does not hold, listing those it does,
  and checks the players a scenario assumes about; it runs every handler that needs only
  the lab by default (`toolbox.LAB_HANDLERS`).
- **The page**: the Modeled and Your assumption tags in its header; a chance before and
  after drawn on a chance's own axis; intervals with a reference line; the lab's documents
  and the model files in the evidence; the new tools' rows as the model read them, with the
  figures behind them in each chart's export. The context tells the model which season the
  models project.
- **Tests**: the section splitter and passages, the search (stems, one hit per section,
  common words, no search syntax), the loader (and the repository's own documents), the
  service, every view of every tool against the services' own figures, the executor's
  roster and assumption checks, the scenario before and after, the season ahead, the page
  drawing a scenario, the rules, the repeated-sentence guard, the verdict note.

**The evaluation** - eight runs over the 56 cases A4 makes runnable: 42, 45, 44, 45, 45 and
44 passed before the review, 43 and 46 after the user's decisions
([AI_EVALUATION.md](AI_EVALUATION.md) lists what each led to); every fix was to the
assistant, and the only case changes are the two the user decided (below). What the runs
settled (decision 0018, "Settled while building A4"): how the lab works comes from its
documents or a model's evidence, never memory (rule 12); a call means what it can only
mean - a team view with a rating and no team is a team of that strength, the season ahead
is the simulator's, a stray player id or argument is dropped rather than refused; the tools
give the changes and say what every range is; a question asking for a verdict is qualified
with a note; a chance word may rest on the lab's documents; a share or chance without its
interval is sent back once and otherwise noted; a sentence said again is cut; a refusal may
have a word in the middle ("does not currently support"); a metric is found however it is
written; the tool descriptions say what each view is for, and that the transactions tool
answers roster changes. At the end: the right first tool in 34 of 35 cases that need one,
nothing called in the 11 *clarify* and *refuse* cases, one call refused in 52, nothing
forbidden, the only figures cut five that I01 invented, a quick answer in 4.6 seconds at the
median and none late. During the third and fourth runs the machine's GPU was shared with a
game, which slowed those answers; the final runs were not held up by it.

**The user's decisions at the A4 review (2026-10-10)** - two cases rested on what the lab's
data or models do not hold; the user decided both, and each case carries a comment saying
so:

- **S01** asks what happens to the Celtics' 2026-27 season if Jaylen Brown misses 30 games.
  The fixture's 2026-27 rosters - real league responses - have him traded to Philadelphia
  on 2026-07-06. The user decided that a question about the season ahead, or naming no
  season, takes each player's current team, so this is an error; looking back at 2025-26
  should be answered from that season's figures. `simulate_scenario` now refuses a scenario
  that removes, or assumes something of, a player not on that roster, saying which team
  they are with, and the case expects *insufficient* with the build cited (was *supported*,
  citing the model and an interval), its frozen fact being Brown's current team.
- **P04** asks for the model's projection of Derrick White and cited an interval. The value
  model is tested on teams, so there is no tested interval for one player's projection; the
  tool gives how far projections of players known that well have typically missed. The
  case now cites the model alone (was the model and an interval), and freezes that typical
  miss as a fact, read through a new service method, `SimulatorService.projection_miss`,
  which the tool uses too.
- **Plain words**: the user wants simple, easy language on screen wherever possible. The
  tools' texts, the notes and the AI Research page were rewritten in plainer words, and rule
  13 (rules `2026-10-10.3`) asks the model for the same, and to call a player "they".

**The browser pass** - the workbench over a scratch copy of the database (with the docs
folder beside it) and the real model, clicked through with Playwright in the light and the
dark theme: the Celtics' chances with their interval chart and table, a projection, a fit
description that declines a score, the optimizer explained from its decision, a scenario
before and after, a team of +5.0 net rating, and the Brown scenario with its note. It found
one fault: the fit profile's percentile axis read "Percentile (higher is better)", which is
wrong for fit measures; it now names the season's teams, as the Roster Fit page does.
After the user's decisions the page was looked at again in both themes: the plainer words,
S01's question answered with "Not enough to answer" and where Brown is, a projection, and
a verdict question with its note. The model still writes "he" for a player now and then,
though rule 13 asks for "they".

**Gate**

| Check | Result |
| --- | --- |
| `ruff check .`, `ruff format --check .` | Pass |
| `pytest -n auto` (everything but live-network and live-model tests) | 3,616 passed in 4 min 15 s |
| `pytest -m ollama` (the live model) | 6 passed |
| The end-to-end evaluation, on the A4 code | 46/56 (42 to 46 over eight runs); report generated |
| The page in a browser | Clicked through as above, light and dark, before and after the user's decisions; no error box or exception; the one fault found is fixed and checked again in both themes |
| UI boundaries | The page imports `front_office.assistant.api` alone; the boundary tests pass |
| Data and models | No model file or setting changed; the browser pass ran over a copy; the evaluation's saved runs are in `data/assistant/benchmarks/`, which is not committed |

## Milestone A3 - AI Research Assistant: the AI Research page (2026-10-10)

The workbench asks. A new page in a new Ask group puts the assistant on screen: whether
it can answer, a question in Quick or Deep mode, its steps as they come and a way to stop
it, and every answer with what it rests on. No league table, model, setting or roster
changed; nothing was refitted; the answer machinery of A2 is unchanged but for what the
browser pass found.

**Built**

- **The facade** (`assistant/api.py`): `start` answers a question in a background
  `Job` - its own thread and its own `Lab`, its steps readable while it runs, a stop taken
  at the next step that keeps what was gathered, and the answer or the reason there is
  none; `history` carries the last three answered turns; `status` says whether web search
  is set up; `refresh_current` fetches by hand; `connect` and `tools_for` are where tests
  put a scripted model and recorded tools.
- **The page** (`apps/workbench/wb/views/research.py`): badges for the assistant, web
  search and each current source; Quick or Deep; *New conversation*; *Fetch current
  information*; the conversation, the session's only; for each answer its kind (supported,
  qualified, not enough to answer, a question back, declined), its text, its notes and
  limits, the kinds of number it rests on, each result in a tab with the chart its tool
  chose and its rows in the catalogs' labels and formats with a CSV, the evidence with
  every date, and how it was answered. A question back is answered by a click, which asks
  again with the name settled. While a question runs, a fragment shows its steps and a
  Stop button.
- **Charts chosen by the tools** (`domain.assistant.Chart`, `assistant/lab_tools.py`): a
  team's net rating and a player's points by season, a player's percentiles, players
  compared, every team's net rating, a benchmark's shares with their 95% intervals. The
  page draws them with `wb/charts.py` and declines one the house rules refuse.
- **A "Reported" tag** beside measured, derived, estimate, modeled and your assumption:
  the league's transactions and injury report, and pages on the web.
- **Tests**: the facade's job (answered, stopped, offline, history, context); the page with
  a scripted model (offline state, an answer with its tabs, chart and evidence, a question
  back and the choice, a question stopped while under way, an answer that never came, a new
  conversation and a refresh); each tool's chart; the page in every page test and in the
  sweep (27 steps). Every UI test keeps the assistant offline unless it scripts a model.

**The browser pass** - the workbench served over a scratch project with the real model,
the user's search key and the live current sources, clicked through with Playwright in the
light and the dark theme. It found what no test could, and each was fixed:

- After the user chose Jaylen Brown, the model, told "Brown" is Jaylen Brown, looked
  "Brown" up again and asked which one. The question the model reads now names him in
  full; the page keeps the user's words.
- A model wrote "2018-19: +4.3 (6th in the league)" from a table with no ranks, and the
  checker let "6th" stand on another figure near 6. A place now stands only on a place.
- Result tables showed `team_id`, `win_pct` and 0.6829; they now use the catalogs' labels
  and formats and leave ids to the CSV. A tab's title was repeated under it; the controls
  sat out of line.

- A benchmark's bands printed as 5.000000 and 0.793451: a figure no catalog describes is
  now written without a tail of zeros.

**Decisions** - decision 0018's "Settled while building A3": a question runs in the
background; the tool chooses the chart, not the model (a change from the specification,
which had the model ask); opening the page fetches nothing; the conversation is the
session's; outside text is shown as written. The user accepted both departures from the
specification on 2026-10-10, and asked for their example key file to become the template:
`.env.example`, the variable with no value and two lines on its use, checked to hold no
key before it was committed.

**Gate**

| Check | Result |
| --- | --- |
| `ruff check .`, `ruff format --check .` | Pass |
| `pytest -n auto` (everything but live-network and live-model tests) | 3,536 passed in 5 min 4 s |
| `pytest -m ollama` (the live model) | 6 passed |
| The end-to-end evaluation, on the A3 code | 39/42, the same three model misses as A2; report generated |
| The page in a browser | Clicked through twice with Playwright, light and dark, on a scratch copy of the database with the real model, the user's search key and the live current sources: asking, a question back and the choice, a chart, Deep mode and Stop (with a live web search), the evidence, a new conversation, a fetch by hand. No error box or exception on the page; every fault found is listed above and fixed. A screenshot is in the README. |
| UI boundaries | The page imports `front_office.assistant.api` alone; the boundary tests pass |
| Data | Nothing in the real `data/` was written: the browser pass ran over a copy |

## Milestone A2 - AI Research Assistant: tools, evidence, current data, the web (2026-10-09)

The assistant answers: names resolved by code, the lab's data through typed tools, current
games, transactions and the injury report, the web through the user's own search key and
a guarded page fetch, and every answer checked before it is shown. Nothing reaches the
workbench yet (A3). No league table, model, setting or roster changed; nothing was
refitted.

**Built**

- **Names first** (`services/entities.py`, `assistant/names.py`): seasons, years, players
  and teams found in the question against the lab's own name tables, a franchise by the
  name it had that season. An ambiguous name is asked about and the model is not called; a
  year names a season only when it can ("the 2026 playoffs" are 2025-26's, "the 2026
  draft" names none).
- **The read tools** (`assistant/lab_tools.py`): `resolve_entities`, `data_status`,
  `player_stats`, `compare_players`, `team_stats`, `league_context`,
  `historical_benchmarks`, `metric_definition`, `contract_info` - service calls written as
  the workbench writes them, each with its evidence (the build, NBA.com's credit, the
  contract file's date). An empty read of the lab carries the build too.
- **The loop** (`assistant/executor.py`, `orchestrator.py`, `toolbox.py`): ids the lab does
  not hold refused before anything runs; each mode's calls, seconds, context and web
  budget; results quoted to the model as data; a model that says "let me check" and stops,
  or cites a result it never fetched, asked once to call.
- **The checker** (`assistant/checker.py`): every figure must be in what the model was
  given at the written precision (dates and years are labels); a chance where no result is
  one, a verdict, a claim to have saved something and a citation of nothing are caught
  too. Sent back once, then cut with the sentence. The outcome reads the results and the
  words.
- **Current information** (`domain/tables/current.py`, `providers/nba_current.py`,
  `processing/current.py`, `storage/current.py`, `pipelines/current.py`,
  `services/current.py`, `assistant/current_tools.py`; `fol current refresh`, `fol current
  status`): the season's game logs through the existing ingest, the league's
  player-movement file, and the latest injury report read from its PDF with `pypdf`, into
  `data/current.sqlite` beside the lab's database, each source fetched only when its
  interval has passed and every attempt logged. A source checked and found empty is a
  dated, qualified answer; "not on the report" is never "healthy"; moves after the build
  are flagged.
- **The web** (`providers/web.py`, `processing/web.py`, `pipelines/web.py`,
  `assistant/web_tools.py`): Ollama's web search with the user's key from
  `FOL_OLLAMA_API_KEY` (environment or `.env`), refused sites left out; pages read by id
  only - a search result or a pasted link - after the address, redirect, connection,
  robots (for AI agents too), size and type checks.
- **The evaluation** (`assistant/evaluation.score_answer`, `scripts/evaluate_answers.py`,
  `tests/assistant/recorded.py`, [ASSISTANT_ANSWERS.md](research/ASSISTANT_ANSWERS.md)):
  whole answers to the 42 cases A2's tools can answer, in a recorded world dated the case
  file's day; an end-to-end smoke test in the `ollama` marker.
- The data dictionary lists the current tables; `pypdf` is confined to `processing`;
  `pipelines.web` joins the assistant's reach (decision 0018's A2 section says why); the
  test suite's environment never carries the search key.

**The evaluation** - six runs, 29, 34, 36, 37, 38 and 39 of 42 passed; every fix was to
the assistant, none to a case ([AI_EVALUATION.md](AI_EVALUATION.md) lists them run by
run). At the end: the right first tool in 22 of the 23 cases that need one, nothing called
in all 10 clarify and refuse cases, every call valid, nothing forbidden, no figure cut, a
quick answer in 3.3 seconds at the median. The three still failing are the model's: a
routing choice (E03), a view (N04), and a refusal of Spotrac that does not go on to
answer from the lab's contract file (K03).

**Live checks** (in a scratch project, never the real `data/`)

- `fol current refresh`: the season's game logs (none yet: the 2026-27 regular season had
  not started), the player-movement file (9,943 lines, 10 repeats kept once, the newest
  2026-10-07), the injury report (none published in the preseason). The parser read the
  report of 2026-04-17 8:30 PM line for line earlier in the milestone (29 lines over two
  pages); that file is not committed.
- The page fetch: Wikipedia read (published 2002, updated 2026-10-02 - both now shown);
  ESPN and AP refused by their robots rules for AI agents (ChatGPT-User, Claude-User);
  Basketball Reference refused by name; `localhost` refused.
- Ollama's web search, with the key the user put in `.env` (only its presence was
  checked): five results in 0.9 s; RotoWire's page read. Then two whole answers with the
  real model, current sources and web: the Knicks' injuries (qualified - no report in the
  preseason, with its source and "not the same as healthy"), and the Knicks' preseason in
  the press (search, then the first result read by its id, then an answer citing it).
  Three searches in all.
- The live answers found four faults the recorded world had not: an icon's `<title>`
  joined a page's title; the model asked `read_source` for "r1", a result's id; the
  checker read a numbered list's markers as figures and sent a good answer back; and the
  model answered the repair note itself ("Therefore, they cannot be cited..."). Each has
  a fix and a test (AI_EVALUATION.md), and the second live answer came out right.

**Decisions** - recorded in decision 0018's "Settled while building A2": the cache file
of its own; an absence a source confirms is a qualified answer; the lab's own page fetch
rather than Ollama's; nba.com refused to the fetch; `pipelines.web` in the assistant's
reach; the language, citation and promise checks; how a year names a season; and, by the
user on 2026-10-09, robots rules read for AI agents too, though they shut ESPN and AP out.

**Found on the way**

- Shell heredocs mangle backslashes, as CLAUDE.md warns: twice a `"\n"` became a line
  break and once `\b` became a backspace character in a regular expression; all were
  found and rewritten with the editor.
- The fixture's real game logs serve as a season still to be played only once their
  payload's own season is moved too: the raw store checks a snapshot's echo against where
  it is filed.
- The robots rules for AI agents shut out ESPN and AP: the assistant can show their
  search snippets but cannot read their pages. The user chose to keep the rule.
- The user's `.env.exmample` (an example file, misspelt) is not git-ignored; it holds only
  the empty placeholder, checked without printing any value, and is left out of the
  commit for the user to rename or drop.

**Gate**

| Check | Result |
| --- | --- |
| `ruff check .`, `ruff format --check .` | Pass |
| `pytest -n auto` (everything but live-network and live-model tests) | 3,499 passed in 4 min 4 s |
| `pytest -m ollama` (the live model) | 6 passed, three of them whole answers in the recorded world |
| The end-to-end evaluation | 39/42 on the final run; report generated |
| Data quality | The current tables have contracts and pass `conform_frame`; the data dictionary lists them (`fol dictionary --write`); the build is untouched |
| Network in the test suite | None: fakes for the league's files, stats.nba.com, the web and Ollama; the search key is removed from every test's environment |
| Live web search | Checked: three searches; Wikipedia, RotoWire and a Substack newsletter read; two whole answers (above) |
| UI | Not affected (the page is A3) |

## Milestone A1 - AI Research Assistant: the local model and its benchmark (2026-10-09)

The assistant's first code: a local model it can trust to stay local, the layer it lives
in, the typed tools it may ask for, and a measured choice of model on this machine's GPU.
No tool runs yet and nothing reaches the workbench; no league data, model or roster
changed.

**Built**

- `configs/assistant.yaml`, validated by `domain/assistant.py` and loaded by
  `config/assistant.py`: Ollama's loopback address, the default and fallback models, and
  for Quick and Deep the context length, thinking and output limit. An address off this
  machine, a cloud model or an unknown field (a key) is refused.
- `providers/ollama.py`: Ollama's HTTP interface through `requests`. Loopback only;
  refuses a model named as a cloud model or listed as remote; sends the context length
  with every request; streams an answer and puts it back together with Ollama's counts and
  timings and the time to the first token; reads capabilities, licences and where a loaded
  model sits in memory.
- The `assistant` layer: `tools.py` (the registry - 20 tools, each with a Pydantic
  arguments model, a permission class and the milestone that builds it; enumerations read
  from the lab, not written twice; schemas flattened for small models), `policy.py` (ten
  versioned rules and the context the model reads), `routing.py` (the first move, checked,
  with one repair; tool results quoted as data), `evaluation.py` (the cases typed and
  scored), `api.py` (whether the assistant can answer, and what to do if not).
- Boundary rules: the `assistant` layer in `LAYER_RULES` and `ARCHITECTURE.md`; the
  workbench may import `front_office.assistant.api` alone; the assistant may use only
  `providers.ollama`, `providers.web` and `pipelines.current` of those layers.
- `scripts/benchmark_ollama.py` and its generated report,
  [ASSISTANT_MODELS.md](research/ASSISTANT_MODELS.md). A `pytest -m ollama` marker for the
  tests that need the real model, deselected by default.

**The benchmark** (59 cases, each in its own mode, 8,192-token context, every model cold
first; then 12 cases at 4,096). Verdicts as re-scored after the user widened P01 and W01
(below); the moves are the run's own.

| Model | Passed | Right tool when needed | Quick median | Deep median | On the GPU |
| --- | --- | --- | --- | --- | --- |
| `qwen3:8b` | 46/59 | 32/37 | 2.2 s | 14.9 s | 5.76 GB, none in RAM |
| `qwen3:4b-instruct` | 41/59 | 25/37 | 1.5 s | 2.2 s | 3.61 GB |
| `qwen2.5:7b` | 38/59 | 28/37 | 1.9 s | 4.5 s | 4.78 GB |
| `qwen3:4b` | 21/59 | 13/37 | 20.2 s | 62.2 s | 3.61 GB |

**Decisions**

- **Default `qwen3:8b`.** The most first moves right, no forbidden call, nothing cut off,
  wholly on the GPU at 8,192 tokens (7.4 of 8.0 GB in use with the desktop's 1.6), a quick
  first move in about two seconds.
- **Fallback `qwen3:4b-instruct`.** Next best, every call valid at the first try, the
  fastest, half the memory - for when the desktop needs the GPU.
- **Not `qwen3:4b`.** The tag is now Qwen3-4B-Thinking-2507: it thinks whatever it is
  told, so 36 of 59 first moves ran out of room at Quick's 1,024-token limit, at about 20
  seconds each.
- **Not `qwen2.5:7b`.** It followed the instructions planted in a page (W03): it called
  the optimizer with the planted budget of 999 million.
- **8,192 tokens in both modes.** The rules and the twenty tool definitions take about
  2,600 tokens; 4,096 left `qwen3:8b` 10 of 12 right but little room to think, and 16K
  would push it into system memory beside the desktop.

**What the model gets wrong** - A2's work, recorded in [AI_EVALUATION.md](AI_EVALUATION.md):
ambiguous names (0 or 1 of 4 for every model: the pre-pass will answer them before the
model is asked), ids the context does not hold (`team_id: 1` for the Bulls), methodology
questions without `research_docs`, the optimizer's budget mode, an extra field repeated on
repair, postseason views. No model meets the 95% routing gate alone.

**Two cases widened, by the user's decision** - questioned after the results were seen,
set out for review, and widened by the user on 2026-10-09: P01 now also accepts the
`season_odds` view, which gives the same Celtics figures as the expected `team` view
(checked on the fixture database); W01 now also accepts `resolve_entities`, since its
context does not resolve the Knicks. The rule for changing a case says so now (the case
file's header, AI_EVALUATION.md, CLAUDE.md), each widened case carries a comment, and
`judge_choice` and `passes` in `assistant/evaluation.py` let the benchmark judge a saved
run again (`--rescore`) without asking the models again. Re-scored, `qwen3:8b` went from
44 to 46 of 59; no other verdict changed. A0's commit keeps the cases as first frozen.

**Found on the way**

- The first background download of the models died with the network; the second hung
  after one model and was stopped; pulled one at a time, all four arrived (Apache-2.0
  each, as Ollama reports).
- The boundary test reads any literal over 9,999,999 as a cap figure, nanoseconds per
  second included; it is written `1_000**3`, with a comment.
- `qwen3:4b-instruct` lists a thinking capability, and its template renders the tools in
  about 650 more tokens than the others.
- Ollama on this machine runs with cloud enabled (`OLLAMA_NO_CLOUD` unset); the adapter
  refuses remote models regardless. Setting it is the user's choice.

**Gate**

| Check | Result |
| --- | --- |
| `ruff check .`, `ruff format --check .` | Pass |
| `pytest -n auto` (everything but live-network and live-model tests) | 3,181 passed in 3 min 44 s. The run before it had one failure, `tests/ui/test_optimizer_page.py::TestThePage::test_submitting_the_form_runs_the_request_as_set`, a page A1 does not touch; it passed alone and in the full rerun, and its cause was not captured. |
| `pytest -m ollama` (the live model) | 3 passed |
| The benchmark on the RTX 4060 | Done; report generated |
| Ollama stopped | The facade returns "Ollama is not running at http://127.0.0.1:11434. Start the Ollama app (or run: ollama serve)..." (tested with a stopped transport) |
| Cloud dependency | None: loopback only, remote models refused, no key field |
| UI | Not affected (no page yet) |

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
