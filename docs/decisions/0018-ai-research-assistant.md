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
