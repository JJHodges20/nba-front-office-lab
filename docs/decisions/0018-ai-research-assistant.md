# 0018 - An AI research assistant: an outer layer, a local model, typed tools

Date: 2026-10-09. Status: accepted.

## Context

The user wants to ask the lab questions in plain language and get back grounded answers:
the lab's own figures, current information (completed games, injuries, transactions),
public reporting, the existing forecasts, roster proposals and saved research. The
specification is the user's *NBA Front Office Lab AI Research Assistant* roadmap; the
audit that led here is milestone A0's entry in the development log.

Four things constrain it:

- **No paid service.** The language model runs on this machine through Ollama (an RTX 4060
  with 8 GB of video memory); no paid LLM, search or data API.
- **Nothing the workbench can reach touches the network.** The workbench imports only
  `services` and `domain` (decision 0008), and no layer beneath them may reach a provider.
  An assistant needs the network twice: for the local model's HTTP interface, and for
  current information and the web.
- **The lab's rules stand.** One formula per metric, models fitted only on request,
  frequencies kept apart from chances, fit as description (decision 0012), salaries only
  from a file the user supplies (decision 0004), the boundary tests.
- **Text from outside is data.** A web page, a feed or a document may contain
  instructions; none may steer the assistant.

## Decision

**One new layer, outermost: `assistant`.** It sits beside `interfaces`, above everything
else, and nothing beneath it imports it. It may import `domain`, `config`, `services`,
`providers` and `pipelines` - and of those last two only named modules: `providers.ollama`
and `providers.web`, and `pipelines.current`. So the assistant cannot reach the
stats.nba.com ingest, a build, a fit, a model file or a contract import. The workbench
may import `assistant`, through `front_office.assistant.api` alone. All three
restrictions are tests. The assistant joins `pipelines`, `services` and `interfaces` as a
layer that loads settings (amending decision 0001). Third-party libraries stay where they
are: `requests` in `providers`, `sqlite3` in `storage`, `yaml` in `config`.

**The model is local, and the code makes sure of it.** `providers/ollama.py` talks to
Ollama's HTTP interface on the loopback address and refuses any other host. It refuses a
model Ollama marks as remote (`remote_model`, `remote_host`) or whose tag names the cloud,
because a signed-in Ollama serves cloud models through the same local interface and bills
for them. It sets the context length on every request rather than inherit Ollama's
default. `configs/assistant.yaml` has no field for a key. The user is advised to set
`OLLAMA_NO_CLOUD=1` as well.

**Three kinds of data in three files.** The lab's database is unchanged: rebuilt by
`fol build`, read by the services (decision 0005). Current information - this season's
game logs, the injury report, transactions - is a cache in `data/current.sqlite`, filled
by `pipelines.current` and rebuildable from the raw store, where its snapshots also go so
that the next `fol build` reuses them. The user's research - workspaces, conversations,
evidence, proposals, approvals - lives in `data/assistant/assistant.sqlite`: never dropped,
migrated by version with a backup first, untouched by `fol build`.

**Tools are typed and allowlisted, and none of them writes.** The model chooses from a
registry of tools, each with a Pydantic model for its arguments; the executor validates,
checks the tool's permission class and limits, and calls the services. The classes are
`read`, `compute` (an optimizer or simulator run kept in memory), `net` (current data and
the web, which may fill a cache) and `draft` (a proposal stored for review). There is no
write class. Saving a roster is the user's own click on a reviewed proposal, checked
against its fingerprint and stored in one transaction. The model is never given table
reads, SQL, code, a shell, files, a URL it composed, a fit, a build, an import, a roster
edit or a setting.

**Every figure comes from a tool.** A result carries its provenance (the metric catalogs'
tags), the build, the model revision, the contract file's date and the source's dates. The
answer is checked: a number in its text must match a cited result as displayed, or the
answer is repaired or cut back and labelled. Tables and charts are drawn from the results,
never from the model's text; a chart is a typed specification the workbench's own chart
builders draw. Outcomes are *supported*, *qualified* or *insufficient*, or a question back
to the user.

**Sources, as audited on 2026-10-09** (`docs/DATA_SOURCE_REGISTER.md`):

- Completed games come from stats.nba.com's league game logs for the season in progress,
  through the existing provider - reachable from this machine on 2026-10-09 despite an
  upstream report of blocking. Transactions from stats.nba.com's player-movement file. The
  NBA's terms allow private, non-commercial use with a prominent credit to NBA.com, which
  every answer that uses league statistics carries.
- Injury status from the league's official injury report (PDF), read with `pypdf`.
- Not used: cdn.nba.com's live data (its firewall refuses clients that do not imitate a
  browser; the terms bar play-by-play products) and www.nba.com's pages (robots.txt shuts
  out AI agents).
- General web search through Ollama's web search API on the user's free account - no
  card; queries leave the machine; the key is read from an environment variable of the
  lab's own and used by `providers/web.py` alone, never by the local model. Chosen because
  no local, account-free search is compliant in 2026: SearXNG's default engines imitate a
  browser and solve bot checks, and Google's and Bing's APIs are closed. Its free quota is
  unpublished and is measured in A2. Beside it: ESPN and Yahoo feeds on their display
  terms, Wikipedia's API, and URLs the user pastes. Sports Reference and Spotrac are
  refused.
- Salary rows from the user's contract file may be sent to the local model. HoopsHype's
  terms could not be read by an automated fetch; the user read them and allowed it on
  2026-10-09.

**Alternatives rejected.** The assistant inside `services` would let every service reach
the network. A local HTTP server for the assistant would add a port, authentication and a
second copy of the state. Letting the workbench import `pipelines` would put a build and a
fit one call away from a page.

**Milestones A0-A9**, so as not to clash with the lab's milestones 1-14: A0 this decision,
the specification and the evaluation cases; A1 the local model and its benchmark; A2 tools,
evidence, current data and the web; A3 the AI Research page; A4 the forecasting tools; A5
roster proposals and the approved save; A6 workspaces and asking from any page; A7 wider
sources and contract-update review; A8 research proposals; A9 the release audit.

## Consequences

- The rule lands with the package, in A1: `test_every_layer_package_has_a_rule` fails
  while either exists without the other.
- The workbench gains its first path to the network, through one module, and the tests
  say which.
- The first chance to misuse a tool is closed by construction: there is no write tool, no
  free URL, no free SQL. What remains - a wrong figure in prose - is checked on every
  answer.
- The assistant's quality is measured, not asserted: `docs/AI_EVALUATION.md` and the cases
  in `tests/assistant/fixtures/cases.yaml`. A case is never edited to make a model pass.
- `OptimizerService.save` is not one transaction (a roster is created, then each player
  added in turn). A5 adds an atomic save for approved proposals.
- Ollama, the web and the NBA's sources change. Each provider is re-verified when the
  milestone that needs it begins, and the register updated.

## Settled while building A2 (2026-10-09)

- **Current information is kept in a file of its own**, `data/current.sqlite`, with a log
  of every attempt. The season's game logs go through the existing ingest, so their
  snapshots also reach the raw store and the next build; the player-movement file and the
  injury report are kept only in the cache, with their address, time and fingerprint -
  the report may not be redistributed, and neither is needed to rebuild anything.
- **An absence a source confirms is an answer, a qualified one.** No game played yet, no
  report published, no move in the window: the tool succeeds, returns nothing, and
  carries a *limit* - what an answer resting on it must say. An absence in the lab's own
  data (a season it does not hold) is a result that found nothing, and the answer is
  insufficient. A source never reached is unavailable.
- **The page fetch is the lab's own, not Ollama's.** Ollama also offers a fetch API; the
  lab fetches pages itself, so that the address checks, the robots rules for AI agents and
  the refused sites are its own code and tests, and nothing but the query leaves for
  ollama.com. Reading a page needs no key.
- **nba.com is refused to the page fetch,** whole: the league's data comes through the
  lab's providers, and www.nba.com's robots rules shut AI agents out.
- **`pipelines.web` joins the assistant's reach.** Turning a page into text is processing,
  which the assistant may not import; a pipeline composes the provider and the processing
  as everywhere else, and the boundary test names it.
- **The lab's language is checked like its figures.** A chance where no result is a chance,
  a verdict anywhere, and a claim to have saved or changed something are sent back once and
  then cut with their sentence. The end-to-end runs saw a benchmark's frequency called "a
  0% chance" (B01) and "The roster for Option B has been saved" (R02).
- **A citation must point at a result.** The model copied an earlier turn's "[table r1]"
  as "[table r2]" without calling anything (T01). A citation of a result no tool returned
  is sent back once with the tools offered, then the sentence is cut.
- **A promise is held to.** A small model sometimes writes "Let me check..." and stops; it
  is asked once to make the call.
- **The outcome reads the words as well as the results.** With nothing called, saying no
  is a refusal and anything else is insufficient. With results, an answer that says it
  cannot, or that the data lacks something, is insufficient if it states no figure and
  qualified if it does.
- **A year names a season only when it can.** "The 2026 playoffs" are 2025-26's; "the 2026
  draft" names no season. Only a year that could be either season is asked about.
- **Robots rules are read for AI agents, and kept.** Checked live, ESPN's and AP's rules
  turn away ChatGPT-User and Claude-User, so their pages are not read - only their search
  snippets show. Judging pages as the lab's own agent alone would read them; the user chose
  on 2026-10-09 to keep honouring the sites' stated wishes.

## Settled while building A3 (2026-10-10)

The user accepted the two departures from the specification below - the tool choosing
the chart, and nothing fetched on opening the page - on 2026-10-10.

- **A question runs in the background.** `assistant.api.start` returns a job: a thread
  with its own connection to the lab (so the pages go on reading theirs, and nothing the
  job remembers leaks into them), its steps readable as they come, and a stop that is
  taken at the next step and keeps what was gathered. The page looks in once a second
  through a fragment and takes the answer in when the job is done. Streamlit stops a
  script when its page is clicked, so a stop button on a blocking call could only have
  thrown the work away.
- **The tool chooses the chart, not the model.** The specification had the model ask for a
  chart by kind, result and columns. A small local model already misses some tool
  choices, and a chart request would spend a call from Quick's three. Each tool attaches
  the chart its own rows call for - a line of a team's or a player's seasons, percentile
  bars, comparison dots, every team's net rating, a benchmark's shares with their 95%
  intervals - and the page draws it with the workbench's builders and house rules,
  declining (with a note) one that would break them. Nothing in a chart is computed.
- **Current information is fetched by questions and by hand, not on opening the page.**
  The specification had the workbench check every source once a session at launch: up to
  a dozen requests and a quarter of a minute before the page drew. A question fetches
  what it needs when it is due, the page shows each source's state, and a button fetches
  what is due by hand.
- **The conversation is the session's.** Earlier turns carry over as text, the last three
  answered ones, so that "and in 2012-13?" follows; a chosen reading of an ambiguous name
  is asked again with the name settled. Workspaces that persist are A6's.
- **Text from outside is shown as written.** A dollar sign in an answer is a dollar sign,
  not the start of a formula; an image in an answer is left out rather than fetched; a
  page's title or a step is escaped.

## Settled while building A4 (2026-10-10)

- **Every modeled figure goes out with what the lab knows of its error, and nothing new is
  computed to supply one.** A chance carries its 95% interval from the postseason model's
  kept draws, and the season model's record on team-seasons it had not seen, read both ways
  - with each season's own rating and from the rating predicted before it (decision 0014).
  A scenario carries the interval of the seasons drawn and the wins test's coverage. A
  player's projection has no tested interval of its own: the value model is tested on
  teams. The tool says so, and gives what the lab has measured instead - how far
  projections of players that well known have missed (the simulator's bands) - and the
  value model's error on a team with the minutes projected. An interval for one player
  would be a new claim, and it would have to earn its place out of sample first.
- **Fit is a limit, not a figure.** While the fit evidence is not usable, a profile is
  description and its result carries the limit that there is no fit score and no
  correction, so an answer resting on it is qualified and says why.
- **A scenario takes each player's current team** (the user's decision at the A4 review,
  2026-10-10). A question about the season ahead, or one naming no season, means the
  rosters as they stand: a scenario that removes, or assumes something of, a player who is
  not on that team's roster is an error - nothing is simulated, and the result names the
  player, the season and the team they are with, with its id. A question looking back at a
  season already played is answered from that season's figures; the simulator only looks
  ahead. (The fixture's 2026-27 rosters have Jaylen Brown traded to Philadelphia, which is
  what S01 asks about; the case was changed to expect the error.)
- **Plain words on screen** (the user's standing wish, 2026-10-10). The tools' texts, the
  notes an answer carries and the page's own words are written for someone who is not a
  statistician, and rule 13 (rules `2026-10-10.3`) asks the model for short sentences and
  everyday words, keeping a term such as net rating or interval where it is needed.
- **A roster id is checked like a player's or a team's.** The executor refuses a saved
  roster the lab does not hold, listing those it does, before anything runs.
- **The document index is built for each search, in memory.** About three hundred sections
  index in a few hundredths of a second, so an edited document is found as it now reads and
  no index file can go stale. A section is searched in passages of whole paragraphs, so a
  long one is not found for holding every word somewhere, and returned once, with its best
  passage. The question's common words and asking verbs ("how does it decide") are left
  out, the rest are matched on their stems, and nothing in a query is read as search
  syntax. The metric glossary and the data dictionary are left out: they are generated
  from the catalogs `metric_definition` reads, and as text their tables hold the words of
  almost any question. The assistant's recorded answers are left out so that it cannot cite
  itself. A section is cited by file and heading - the `docs` kind of evidence - which is
  what the case file's `source` means by "a document path".
- **What the evaluation runs settled** (each a fix to the assistant, none to a case):
  - *How the lab works is never from memory.* Rule 12 (rules `2026-10-10.1`): how a figure
    is computed, how a tool or model decides, how a model was tested and why something was
    chosen come from `research_docs` or a model's evidence. A model had described the
    optimizer from its own imagination.
  - *A question is given the meaning it can only have.* The team view asked about "a team
    with a +5.0 net rating" and no team reads it as a team of that strength; the team view
    asked about the season ahead draws it with the simulator, as `simulate_scenario` would,
    rather than finding no season; a player id with a value view that reads no player, and
    a view or season sent to `data_status`, are dropped rather than refused. Each was a
    model's call that made the answer fail for want of a meaning that was never in doubt.
  - *A figure the services have is given, not left to arithmetic.* A scenario shows the
    service's change beside before and after; a model that subtracted for itself had the
    difference cut. Every range says what it is ("80% interval", "95% interval").
  - *A question asking for a verdict gets a qualified answer and a note.* Rule 5 forbids
    verdicts in the answer; when the question asks for one ("a real contender", "should
    sign", "the best roster"), code marks the answer qualified and says the lab gives the
    evidence instead, rather than trusting the model to say what it left out.
  - *The documents may describe chances.* A chance word in an answer must rest on a chance
    - the postseason model's or the simulator's - or on the lab's documents, which describe
    them. A frequency from the benchmarks is still never a chance.
  - *A share goes with its interval.* An answer resting on a benchmark, the postseason
    model or the simulator that states a percentage and never says "interval" is sent back
    once, with the other repairs, to give each with its interval (rule 4); if the rewrite
    still leaves them out, it stands and the page says the intervals are in the rows.
  - *An answer that loops is cut back to saying each sentence once.* A model wrote the same
    sentence until its output ran out; a sentence of forty characters or more said again is
    taken out, and the step says so.

## Settled while building A5 (2026-10-10)

- **The tool asks the optimizer only what the user asked.** `optimize_roster` starts from
  the season ahead and the roster size the season's rules give, and adds the user's budget,
  groups, roles and players locked in or left out - nothing else. The Roster Optimizer
  page's example requirements are a starting point for its form, not the lab's, and a model
  that passed them on would be answering a question nobody asked. A role the archetypes do
  not hold is refused with the list of those they do.
- **A proposal lives with its answer.** Each roster found becomes a `RosterProposal`
  (`domain/proposals.py`): its players and where each would start, their salaries from the
  contract file, the payroll and what is left under the budget, the projected net rating
  with the value model's typical miss for a whole team (3.63, with the minutes projected),
  what was asked for, and what it rests on - the build, the value model's revision, the
  contract file's date. It is kept with the answer for the session, not stored in an
  assistant database: what persists is A6's workspaces, and until then the saved roster
  itself is the record of an approval. The user accepted this at the A5 review
  (2026-10-10), on the condition that the finished assistant has a place to save proposals.
- **The approved save is one transaction, checked first.** The page's *Save approved
  roster* button calls `assistant.api.save_proposal`, which saves nothing if the data has
  been rebuilt, the value model refitted, another contract file imported or any player's
  salary changed since the proposal was made, and says which in plain sentences. Otherwise
  `RosterRepository.create_with_players` writes the roster and every player together, or
  nothing. The proposal's fingerprint - twelve hex digits of the SHA-256 of everything in
  it - goes into the roster's notes, so a second press finds the roster the first one saved
  rather than saving it twice. The Roster Optimizer page's own save now uses the same
  transaction, which settles the consequence noted above.
- **Where each player starts** is decided once, in `OptimizerService.slots`, for both
  saves: the five with the largest projected share of minutes start, each in a position
  their group prefers; everyone else is on the bench. So five guards can start, one of them
  at center. At the A5 review the user asked that players keep their own positions as far as
  possible (the Team Builder can still move them); that is A6's, which saves proposals.
- **What the model reads stays whole.** Every option's payroll, room, rating and changes
  from Option A, Option A's players with their salaries, and the players the other options
  add with theirs: four options fit the executor's 2,400 characters. The text says the
  rosters are examples that fit the budget, that no trade or signing to reach them has been
  checked, that they are options to compare rather than a recommendation, and that only
  the user's click saves one. It does not say that none is "the best": a model echoes the
  tool's words, and "the best roster" is wording an answer must not use.
- **The test data.** The contracts database prices nine players, so no roster of fourteen
  could be built there and R01 and R03 could never be answered. The user chose on
  2026-10-10 to add a third test database, `priced`: the same build with an invented
  2026-27 salary for each of the 41 players the value model projects (about $1.25M, plus
  $6M for each projected win, plus a quarter of a million times the player id's remainder
  after dividing by seven, rounded to $10,000; `tests/assistant/fixtures/priced_contracts.csv`).
  R01 and R03 run on it; their questions and what they expect are unchanged.
- **What the evaluation runs settled** (each a fix to the assistant, none to a case):
  - *A call refused and made again is not a gap.* R01's model sent an amount with the
    salary-cap mode, was told to use a custom budget, and did; R03's asked for five
    options and then four. The answers were whole, but the refused calls had made them
    "partly answered" with nothing said to be missing. A refused or failed call that the
    model makes again with a usable result no longer counts; one that found nothing still
    does.
  - *The optimizer's arguments say which budget is which*: a cap line by name, or `custom`
    with the user's amount in millions; two to four options, three unless the user says.
  - *The lab's units are not figures.* "Per 100 possessions" and "per 82 games" had been cut
    as figures no result held (S02, M03).
  - *A missing way to do something is a refusal.* With the optimizer offered, F02's model
    answered "does not have a direct parameter to add a bonus", which the refusal pattern
    now reads.
  - *A call put off is held to.* M01's model described the optimizer from memory and
    offered to look it up, or told the user to use `research_docs` or `optimize_roster` -
    in each of three runs. The user cannot call a tool. Before anything is called, in a
    reply that declines nothing, an offer to look something up or a tool named for the user
    is treated like a promise, and the model is asked once to make the call. The
    optimizer's own description says that how it chooses is in `research_docs`.
  - *The assistant's limits are not a gap.* R03's answer was whole but qualified, for
    relaying the tool's "the assistant cannot save a roster"; in the browser pass, on the
    real data, two whole roster answers were "partly answered" for "The lab cannot check
    league rules or trade feasibility". Beside results, a sentence saying the assistant
    cannot save, change, delete or refit, or that it cannot check trades or signings
    against the league's rules, no longer reads as part of the question left unanswered -
    unless the question asked about exactly that. The tool's own words now avoid "cannot"
    and "the best", which a model echoes.
  - *Rule 6 is left as it was; the page says where.* In the browser pass, declining "Option
    B looks good, save it", a model told the user they "cannot directly edit or delete saved
    rosters" - rule 6 says only what the assistant cannot do. Two wordings that also said
    what the user can do, and where, were tried: rules `2026-10-10.4` had the next run's
    model send the user to a save button "in the Team Builder", which does not exist (X03);
    `2026-10-10.5` had it answer "save it" with "You can view and manage it on the Team
    Builder page", as though the roster had been saved (R02). Each was worse than the slip it
    was meant to fix, so the rules stay at `2026-10-10.3`. Where saving happens is said by the
    page itself, right under every proposal - the caption above the options and the help in
    the save button - and the Team Builder page holds the saved rosters. "Does not have the
    capability to", from those runs, now reads as a refusal (X03).
  - *What lacks something is the data.* M03's explanation from the documents - "winning
    percentage ... does not provide the same level of insight" - read as an answer saying
    the results lack something, and with no figure in it, as nothing to answer from. "Does
    not include, provide, cover..." now counts only when the data, the results, a file, a
    report or a table is what lacks it, as in A2's "the data did not include lineups".
  - *Asking what a team should do is asking for a verdict.* "Who should the Knicks sign?"
    (V02) has words between "should" and "sign", which the answer check's verdict words
    need together; questions are now read for "should ... sign, trade, acquire, draft,
    keep or cut" as well, and the answer is qualified with the note.
  - *A note sent back asks for the whole answer, for the user.* R01's rewrite began "The
    correct figure from the tool result is $80,000 ... Here's the corrected version", as
    A2 had seen; every note now ends by asking for the answer as if for the first time,
    without mentioning the note or a correction.

## Settled while building A6 (2026-10-10)

- **The research store is a file of its own**, `data/assistant/assistant.sqlite`
  (`storage/research.py`, its contracts in `domain/tables/research.py`), as this decision
  set out: no build touches it, and a test keeps a workspace through `fol build`. It is
  versioned. `research_schema` records each version applied; a new file is made at the
  latest; an older one is first copied to `backups/` with SQLite's own backup and then
  brought forward in one transaction, so a failed step leaves it as it was; a file made by
  a later lab, or one that is not this store, is refused and left alone. An id is never
  handed out twice, because a finding names the turn it came from and a cleared history
  would otherwise give that id to a new turn.
- **Six tables where the roadmap sketched nine**: workspaces, turns, findings, proposals,
  approvals and the version log. A turn keeps its whole answer as JSON - the results, their
  rows and charts, the evidence, the notes and the steps - so the page draws an old answer
  exactly as it was; separate tables of tool runs and evidence would only be read to put
  the turn together again. A conversation is a number on the workspace and on its turns.
  The model benchmarks stay files in `data/assistant/benchmarks/`, as at A1.
- **A workspace is made the first time one is needed**, named "My research" or the first
  free variant: the control sweep archived the only workspace, and a new one of the same
  name clashed with it.
- **A follow-up reads its own workspace and nothing else**: the last three answered turns
  of the conversation under way. *New conversation* starts afresh and keeps the history;
  *Clear history* forgets the questions and answers and keeps the notes, findings and
  proposals; *Delete* removes the workspace and all it holds, but never a roster saved from
  it. Tests send questions in two workspaces and read what the model was given.
- **Notes are background, never evidence.** A workspace's notes go into the system prompt
  after the context, under a heading that says what they are; the answer checker does not
  read them, so a figure taken from the notes alone is cut. At the user's request the
  local model summarizes the conversation under way into the notes, marked as its summary,
  and a new conversation begins that reads the notes instead.
- **A workspace has a focus**: the season, phase, team and Team Builder roster its
  questions are about when they name nothing, over the sidebar's. A roster in focus reaches
  the model as "Roster in focus: name (roster_id N)".
- **A pronoun with nothing to mean is asked about, not guessed.** "He", "she" or "they" in
  a question that names no player or team, with none in focus and no earlier turn to follow,
  gets "Who do you mean by...?" without the model. A question that asks who or which has a
  subject of its own ("Who won the 2025-26 championship, and whom did they beat?" - H03
  would otherwise have been asked), and "they" beside a plural ("do teams win more when
  they...") means the plural. No frozen case is caught.
- **An old answer is never rewritten.** A turn records the data build and the value model
  revision it read; when either has changed the page says so in a sentence and offers *Ask
  again with today's data*, which asks the same question as a new turn beside the old one.
  Current information and the web change without a build, so an answer that read them
  says when, and offers the same, once a question would fetch the soonest of the current
  sources again (`configs/assistant.yaml`) - without knowing which source it read, which
  the evidence does not record.
- **Proposals have a place to be saved** - the user's condition at the A5 review. Every
  roster an answer proposes is kept in its workspace, waiting until the user saves or
  declines it, under the answer or in the workspace's list; a declined one can still be
  saved. Every press is logged: saved, found saved already, refused with the reason, or
  declined.
- **Ask AI about this** sits on the player, value, team, benchmark, Team Builder, roster
  fit, postseason and simulator pages. The dialog says what the question will be about -
  the page's player, team, season and roster - and asks it in the workspace open on the AI
  Research page. The page's choice travels with the question alone; the sidebar never
  changes. The answer comes back in the dialog in short, and in full in the workspace, a
  click away. One question runs at a time, and the dialog and the page show the same one.
  The dialog's body is a plain function, so a test can draw it inline: in a browser a
  dialog reruns alone, which the test runner cannot follow.
- **Saved players keep their positions** - the user's wish at the A5 review.
  `domain/lineup.py` chooses the starters from the nine who play the most, each at a
  position they are listed at where the roster allows, then the most minutes; every save
  uses it - the Roster Optimizer's, a proposal's and the Scenario Simulator's. A roster's
  five guards no longer start with one at center: a center starts there, and a guard with
  more minutes comes off the bench.
- **At the A6 review** (2026-10-10) the user decided that starters are chosen by projected
  impact and role rather than minutes, and that a place in an answer is checked for what it
  ranks - the league or a conference. Both are A7's.

## Settled while building A7 (2026-10-10)

- **News comes from feeds the register allows, read as a feed reader reads them.** A0
  planned ESPN's and Yahoo's feeds and Wikipedia's API. Re-checked as A7 began, ESPN, Yahoo
  and CBS Sports turn AI agents away in robots.txt, which the lab honours (the user's choice
  at A2); NBC Sports' terms bar automated tools; Wikipedia's robots.txt bars its API. Of the
  feeds that admit the lab and AI agents alike, the user chose Hoops Rumors (2026-10-10): its
  main feed, its feed of moves and the 30 team feeds, listed in `configs/assistant.yaml`
  (`news:`) and never composed from a question. NBA Communications stays behind the rule
  that refuses every nba.com host; RealGM's terms refused an automated read, and it was not
  chosen.
- **A feed passes every check a page passes** (`WebProvider.fetch_feed`) and is read by
  `processing/feeds.py`: RSS or Atom; a feed that declares a document type or entities is
  refused, and so is one with a zero byte - in UTF-16 or UTF-32 a declaration is not the
  bytes the check looks for, and XML never holds one; each item keeps the site's headline,
  dates, author, tags and the start of its
  excerpt, as plain text. The same article in several feeds is one item, known by its
  address without tracking parameters, and a search result for it is the same source.
- **News is a fourth current source** (`news_items` in `data/current.sqlite`): each feed
  due on its own after 30 minutes, a team's only when a question is about that team, items
  kept for 120 days after publication. It is fetched when asked for - by the
  `moves_and_rumors` tool, `fol current refresh` and the AI Research page's button - and
  not by default, since it reaches a site the lab does not run.
- **The feeds' tool is named for what they carry.** Called `news`, it drew W01's "Find
  recent reporting on why the Knicks won the 2025-26 title" in each of three evaluation
  runs: the model asked the feeds for moves alone and never searched the web, so the
  "reporting" it set beside the numbers was two unrelated signings. Three wordings of the
  description changed nothing once the question's names were resolved as the assistant
  resolves them. Named `moves_and_rumors`, with a description of moves and rumors, W01
  went to `web_search` in each of four first moves tried, while "the latest news on the
  Knicks", "any trade rumors" and "anything reported about" a player still reached the
  feeds, and each current-information case its own tool (scratch probes of the first
  move, 2026-10-11; the evaluation is the test). The name did the work: `web_search`'s
  description, widened with it to "reporting and analysis from any date, such as why
  something happened", moved K02's payroll question from `contract_info` to `team_stats`
  in two runs and two of three probes; back as it was, K02 went to `contract_info` and W01
  to `web_search` in three probes of three each.
- **Every item is dated.** `moves_and_rumors` gives each headline its publication time and
  how long ago it was; a search result, which carries no date, says the date its address
  shows or that it shows none. The search-quality run showed why the feeds matter: 23 of
  103 kept search results were dated by their address, while the feeds held 122 dated items
  for the same eight news questions.
- **Search quality is measured, not asserted** (`assistant/search_quality.py`,
  `scripts/evaluate_search.py`, `docs/research/SEARCH_QUALITY.md`): twelve frozen queries
  (`tests/assistant/fixtures/search_cases.yaml`), each counted for results on the subject,
  dated, recent, repeated and from refused sites, and held against the feeds. Counts, not
  thresholds.
- **The contract-update review compares, flags and stores nothing.**
  `pipelines/contract_review.py` reads a candidate contract file exactly as an import would,
  compares it with the file in use by player, team and season, and says what to check
  first: a source never imported before (its terms unchecked), figures older than those in
  use, names the league's index does not hold, seasons without cap rules. `fol contracts
  preview` and Contract Explorer's *Check a new file* reach it - the page through the
  assistant's facade - and the assistant may reach this module and not
  `pipelines.contracts`, whose import writes. Importing stays `fol contracts import`, the
  user's own command.
- **A report is never a contract figure.** `contract_updates` lists the moves on the
  league's transactions file and those reported in the news since the contract file's date,
  each beside the file's salary for the season, and says how to bring the file up to date.
  Nothing it reads changes a table, a roster or the file.
- **The user's wishes from the A6 review**: starters are chosen by projected impact among
  the lineups that fit their listed positions (`domain/lineup.py`), and a place in an
  answer is checked for what it ranks - the league or a conference - with every tool
  writing its places so ("4th of 30", "3rd in the East"). The first evaluation run showed
  how the check must work with a small model: told only that its "6th in the Eastern
  Conference" was the league's 6th, the model wrote it again; and the cut took the whole
  sentence, the record the user asked for with it. So the note now names what the results
  give for that field ("in the East they give 3rd") and asks for everything else as it
  was; and a sentence whose only fault is such a place is cut at that clause, not lost
  whole. What follows the clause goes too: the third run's E01 showed a cut that kept every
  clause standing leaving "15 wins and 67 losses, as the league was split into conferences
  at that time)" - a remark on the place taken out, with its bracket.
- **A refused id says where it belongs.** In the browser pass, asked what had changed for
  the Knicks since the contract file, the model gave the team's id as the player as well;
  told only that no player has that id, it gave up. A refusal now names an id of the other
  kind - "the id of the New York Knicks, a team" - and the field it belongs in.
- **A gap is what the data lacks, not what a story says.** "Not available", "not provided"
  and the like mark an answer as saying something is missing only beside the data, the
  results, a file or the lab: a news answer relaying that a coach "has not provided any
  details" had been called not enough to answer. Every phrasing the evaluation runs had
  read as a gap still is.
- **A reader sees what an answer names.** Answer tables write times plainly, in UTC (a
  kept answer's too, which its JSON holds as text), show a source's id - an answer names an
  article "s2" - and leave the lab's internal keys, as its ids, to the CSV.

## Settled while building A8 (2026-10-11)

- **The user's three choices.** A kept experiment proposal has its own list in each
  workspace, beside findings (`research_experiments`, version 2 of the research store); the
  assistant drafts one only when asked for an experiment or an idea to improve a model; and
  only the four models the lab tests out of sample may be its subject - player value, the
  postseason model, the simulator and the roster fit test. Archetypes are rules a person
  sets, with no test to judge a change, and are left out.
- **Two parts, kept apart.** The idea is the assistant's, in words: what it noticed, the
  hypothesis, the change to test and how the change could fail. It may hold no figure -
  `propose_experiment` refuses one, and the model is sent back to write it in words - so
  that no figure can be made up, echoed in a result and then cited as the lab's. The plan
  is the lab's (`ExperimentService.plan`): what a change must beat or keep, read from the
  model's fitted file; how it is tested and what was tried before, quoted whole from its
  decision by heading; and the rules a person wrote in `configs/experiments.yaml` - the
  split, the measure, the uncertainty test, when a change is kept, the leakage to rule out
  and the steps of the milestone that would build it. A test checks that every heading the
  rules name is still in its decision.
- **The figures are the file's, not the documents'.** The simulator's decision gives its
  intervals' coverage as 53%, 83% and 97%; its file, refitted since, says 51%, 81% and 96%.
  A proposal reads the file.
- **Leakage is written as it is.** The value model's main test takes each season's minutes
  as played, by design, so its rule is "nothing from the season predicted but what the test
  says it takes as given", and a change for forecasts must also be judged with the minutes
  projected. The simulator's noise and residual wins are measured over recent seasons the
  wins test also scores; its checklist says a change leaning on them should be checked on
  seasons they were not measured on, rather than claiming they never overlap.
- **Nothing applies a proposal.** The tool is of the `draft` class: what it drafts
  travels with the answer and is kept only by the user's press of *Keep in the workspace*,
  which writes one row to the research store and nothing else. No path leads from a
  proposal to a model file, a setting or the lab's data; the tests check the model files
  byte for byte around drafting and keeping, and the evaluation checks them around every
  question.
- **The tool list's size.** With `propose_experiment` the tools' schemas reach 14,925
  characters, past the 14,000 a test held them to; a question's whole prompt measured 3,557
  tokens of the model's 8,192, 180 of them the new tool's, so the limit is now 15,000. The
  tool's argument model has no docstring: it would be sent with every request.
- **A "they" for things stands for them.** The A6 check that asks about a pronoun with
  nothing to mean asked "Who do you mean by 'they'?" of "...whether the simulator's win
  intervals are wider than they need to be". A plural the lab talks about - intervals,
  projections, ratings, chances, models - now gives a "they" its meaning, as teams and
  players did, but only before it: "How did they do against their projections?" is still
  asked about.
- **A season is a season however its dash is written.** "2006–07" with an en dash had been
  read as the year and a figure "07", and cut as made up; the checker now reads a season
  with any dash as a label, as it reads "2006-07".
- **A refusal is a refusal however it is put.** With proposals to offer instead, the model
  refused "Refit the value model ... and save it" (I02) as "The lab does not refit models
  ... Would you like me to propose an experiment?", and a chemistry bonus (F02) as "The
  optimizer does not currently include" one; both were read as nothing to answer from.
  With nothing called, what the lab, its optimizer or a model does not refit, offer,
  support, allow or include is now a refusal - data it does not include is still missing.
  The model offers the proposal; it does not draft one unasked.
- **A refused figure is quoted.** Told only to write its idea in words, a model sent the
  same "3.01" back six times (I01), and in the browser pass another gave up and told the
  user its proposal was "rejected due to a value error". The refusal now quotes what the
  idea holds and asks for the same idea again in words, and no refusal carries Pydantic's
  "Value error" for a model to pass on.
