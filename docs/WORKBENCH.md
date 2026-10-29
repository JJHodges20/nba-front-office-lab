# The Workbench

The workbench is the lab's interface: fourteen pages over the database, opened in your
browser.

```powershell
.\.venv\Scripts\fol.exe ui            # starts it and opens http://localhost:8501
.\.venv\Scripts\fol.exe ui --port 8600 --no-browser
```

It runs on your machine only and reads the database `fol build` produced. If there is
no data yet it says so and tells you to run `fol refresh`. Stop it with Ctrl+C.

## Signing in

Nothing opens without a sign-in ([decision 0020](decisions/0020-workbench-sign-in.md)).

- **The sign-in page:** *Sign in* with a name and a password, or *Register* first: a name of
  3 to 32 letters, digits, dots, hyphens or underscores, and a password of at least 8
  characters. The password is kept only as a hash.
- **One account for everything:** it is the same account as the lab's API, so it works on
  *Ask the Docs* and at the API's `/docs` page too. When the API is running as you sign in,
  *Ask the Docs* opens already signed in.
- **How long it lasts:** a sign-in lasts an hour, as an API token does; after that the
  workbench asks again. A new browser tab, or an address typed in, asks again too. An address
  you open while signed out takes you to its page once you sign in.
- **Signing out:** *Sign out*, in the sidebar above the data status, forgets everything the
  session held, the sidebar's choices included.
- **What is shared:** your questions to *Ask the Docs* are yours alone. The rosters, research
  workspaces and data belong to the project, shared by everyone who signs in on this computer.

## The frame

**Navigation** is the bar across the top, in six groups: League, Explore, Build,
Forecast, Ask and System - open a group to see its pages. On a phone the groups are in
the sidebar instead. **Filters** are in the sidebar, always in view, and a choice you make
on one page still holds on the next. Each page reads the filters it can use: the League Overview, the
explorers and the Analytics Lab read them all; Player Value reads the season, the team
and the player; the Contract Explorer and the Scenario Simulator read the team; Roster
Fit and Postseason Outlook read the season and the team; Winning Benchmarks chooses its
own seasons; and the Team Builder, the Roster Optimizer and Data Health read none.

| Filter | What it does |
| --- | --- |
| Season | Any season with team data, newest first. |
| Phase | Regular season or playoffs. |
| Team | Makes one team the subject. Clear it for the whole league. |
| Player | Makes one player the subject. Offered for seasons with player statistics. |
| Comparison window | The full season, the last 5, 10 or 20 games, or a date range. |

Selecting a row in a table of teams or players sets the same filters: tick the box at
the left of the row. The tick clears again once the choice is made; the sidebar shows
who is chosen, and is where to change or clear it. In the Player Explorer a newly
chosen player opens the Profile tab.

**Data status** is at the foot of the sidebar on every page: whether the league data is up
to date and whether a contract file has been supplied - hover over either for the
details, and a line under it says what to do when something needs doing - which build is
on screen, and a link to Data Health, where all of it is in full. Under it, **All pages**
lists every page in its group, folded until you open it. On a phone the sidebar starts
closed: the arrows at the top left open it.

**Dark or light.** The workbench is designed dark - near-black with a forest-green accent
for buttons, selected tabs and links - and has a matching light theme. It starts in your
computer's own setting. To choose, open the menu at the top right (the three dots) and
pick *Dark*, *Light* or *System*: your browser remembers the choice, through restarts, until
its site data is cleared. Another browser, a private window or another port starts from
the computer's setting again. Charts keep their own colours in both themes; green is never
used for data. Just after you switch, a chart may keep the old theme's colours until your
next click on the page.

**With the keyboard.** Tab moves through the sidebar, then the top bar, then the page, and
the control in focus is ringed in green. Type in a dropdown to narrow it and press Enter
to choose; the arrow keys move between tabs; Space ticks a box; Enter presses a button or
downloads a file; Escape closes the *Ask AI about this* dialog. To go to another page, Tab
to **All pages** at the foot of the sidebar, press Enter to open it, Tab to the page and press
Enter. (Enter also opens a group in the top bar, but its pages come last in the order - after
everything on the page.) A page's address works too - `/players`, `/teams`, `/research` and
so on, as the address bar shows each page - and opens it afresh, with the sidebar's choices
cleared.

## Reading a page

- **Headline figures** sit in tiles across the top of a page; in a narrow window or on a
  phone they wrap onto more rows.
- **Tags under the title** say what kinds of number the page holds.
  *Measured*: published by the league and shown unchanged. *Derived*: computed by the
  lab with a stated formula. *Estimate*: estimated by the lab. *Modeled*: produced by a
  model fitted to the lab's own data and tested on seasons it had not seen - an estimate
  with error, never a count. *Your assumption*: something you entered.
- **Hover a column heading or a figure's question mark** for what a metric is and where
  it comes from. Every definition is also in the Analytics Lab's glossary and in
  [METRICS.md](METRICS.md).
- **"≈" marks an estimate.** Over a full regular season, ratings and pace are the
  league's published figures. Over anything shorter - a window of games, the playoffs,
  one game - the league publishes none, so the lab estimates possessions from box
  scores. Over a whole season that estimate is within about a quarter of a rating point
  of the published figure; over a handful of games it is noisier.
- **A dash means missing**, never zero.
- **Percentiles always read "higher is better"**: for turnovers, fouls and defensive
  rating a high percentile means few or low. They run from 1st to 99th, and compare
  players who cleared a minimum of games and minutes, shown on the page and adjustable
  under *Comparison settings*.

## Charts

Hover for exact values. Under every chart, *Table view and export* shows the same
values as a table and offers them as CSV, and the chart itself as an interactive HTML
file - which loads Plotly's script from its website when you open it, so it needs an
internet connection to draw. For a static image use the camera button that appears at the
chart's top right; it saves a PNG at twice screen size.

A *form* chart shows a metric over the trailing 5, 10 or 20 games. Its line starts at
the first date on which that many games had been played, so every point is an average
of the same number of games. With fewer games than that it says so instead.

## The pages

**League Overview.** League averages for the season with their change from the season
before; standings; every team's offense against its defense; net rating; thirty seasons
of league trends; the playoff bracket and every champion with where it ranked.

**Winning Benchmarks.** What the teams that reached each stage of the postseason
looked like, over the seasons you choose: all of them, the last five or ten, the modern
era, the Play-In era, or any span. Pick the stage - made the playoffs, won a series,
reached the conference finals or the Finals, won the championship - and read:

- *How far teams went*: of the teams in each band of wins, net rating or seed, the
  share that got that far, of every team or only of those that had already reached an
  earlier stage. The line through each column is the 95% interval for the share; under
  each band is the number of teams in it. A band is a way of grouping, not a
  threshold: change its width and see.
- *What they looked like*: where those teams ranked in the league in their own season,
  metric by metric, and the spread of their record, ratings and seed, with the teams
  at the extremes named.
- *What separates them*: for each metric, how often a team that got there had the
  better value than a team of the same season that did not. 50% is a coin flip.
- *The field*: any two metrics for every team-season, with those teams picked out.
- *Team-seasons*: the rows it all rests on, for export.

It is history, not a forecast: nothing on the page is the chance that a team does
something this season. The same research as a document is
[research/BENCHMARKS.md](research/BENCHMARKS.md).

**Player Explorer.** Every player of a season by category of metric. A player's profile:
percentile bars, form over trailing games, every season, game log, on/off ratings,
contract. Up to three players side by side. For a whole regular season the *Value*
columns carry the value model's impact and wins above replacement beside the statistics,
and the *Role* column names the main role a player fills by the rules on the Player
Value page - a rule, not a measurement, and empty for a player who fills none.

**Player Value.** What the value model makes of every player, and what the model rests
on. Value is estimated for whole regular seasons, so the phase and the comparison
window do not narrow this page. *The model* shows the test twice: the typical miss with
each season's minutes as played, and with the minutes projected, which is the error the
optimizer and the simulator carry.

- *Season*: everyone who played in the season chosen in the sidebar, by wins above
  replacement, impact, or impact at either end. **Impact** is the points per 100
  possessions a team's net rating gains with the player on the court, against the
  league's average minute. **Wins above replacement** is impact over a replacement
  player, for the minutes played. Select a row for that player's breakdown: where the
  impact comes from, part by part, and each season set beside what the model expected
  going into it. *Reliability* is how much of the estimate rests on the player's own
  numbers; the rest is what the model assumes of anyone used that many minutes a game.
- *Projections*: what the model expects in the season still to be played, from up to
  three seasons before it and age, with a projected share of team minutes.
- *Roles*: the archetypes, as rules. A player's score for a role is the weakest of their
  percentiles on the role's measures, among the players the role is open to, in that
  season - strong on one measure and ordinary on another is not the role. A player fills
  a role from its cut-off up; the cut-off is a convention, and the rules are in
  `configs/archetypes.yaml` to be read and changed. Beside each role: how many players
  it scored and how many fill it this season, and over every season on record how often
  a player who filled it filled it again the next season, against how often anyone did.
  Pick a role for who fills it, highest score first.
- *Value for money*: salaries from your contract file against the wins they pay for. The
  price of a win is read off the contracts on file - a straight line through salary and
  wins - so a surplus says a player is paid less than *those* contracts pay for the same
  wins. With few contracts on file the line is rough, and it says how many it rests on.
  The season still to be played is judged on its projection; later seasons of a contract
  are not valued.
- *The model*: how it did on seasons it had not seen, against simpler methods; what
  each part adds when it is left out; every weight with its interval; every team-season
  of the test, predicted against actual; and what the model cannot tell you.

The same as a document: [research/PLAYER_VALUE.md](research/PLAYER_VALUE.md). Why it is
built this way: [decisions/0010-player-value.md](decisions/0010-player-value.md).

**Team Explorer.** One team: record and ratings with league ranks, the four factors at
both ends, form over the season, the game log, what each player did for this team, every
season on record, and payroll against the cap lines.

**Contract Explorer.** Every salary in a season, team payrolls against the cap, tax and
aprons, and the configured cap rules with their sources. It shows the contract file in
use - the MrBridge salary dataset, every salary a team paid from 2015-16 to 2026-27,
split by team, so a player who changed teams within a season is listed under each
([DATA_SOURCE_REGISTER.md](DATA_SOURCE_REGISTER.md)); the cap columns are blank for
seasons without configured rules (before 2024-25). Payroll is priced by default in the
league year the file was current for, the one that holds its as-of date (2026-27 for
this file); the control at the top of the page picks another season. To replace the
file, see [CONTRACT_DATA.md](CONTRACT_DATA.md). The *Check a new file* tab compares a file
you are thinking of importing with the one in use - what is new, changed or gone, by
player, team and season - and says what to check first: a source never imported before,
figures older than those in use, names the league's index does not hold. It stores
nothing, and shows the import command to run yourself once the source is checked.

**Analytics Lab.** Any two metrics against each other, for players or teams, with how
strongly they move together. How one metric is spread. The metric glossary.

**Team Builder.** Rosters you assemble by hand. For each: payroll, share of the cap,
room under each line, how the roster stands against the roster limits, and what its
players add up to beside the league. Change a slot or type a salary of your own
directly in the table. *Manage* renames a roster, changes its seasons and notes, or
deletes it once you tick the box. It describes a roster; it does not rank or recommend
players, and its pooled figures are not a projection of how the players would play
together.

**Roster Fit.** Do these players make sense together? The sidebar's team, or a roster you
built, described in the roadmap's six areas of fit - offense, defense, the possession
battle, structure, depth and usage - each player weighted by minutes, and
placed among the season's real teams as a percentile and a rank. *Coverage*: who in the
rotation fills each role, who comes nearest, and what nobody fills. *Profile*: every
measure beside the league's median. *Sum of parts*: the players' impacts added up for the
minutes given, with the value model's error - the estimate of a roster - and the fit
correction, which the evidence on file supports or does not. *The evidence*: whether any
measure, alone or all together, explained what the value model's predictions missed on
seasons it had not seen; and where the champions' rosters stood. On the evidence the lab
ships none does, so nothing is added to the sum of the parts and the profile describes.
The same as a document: [research/ROSTER_FIT.md](research/ROSTER_FIT.md); why it is built
this way: [decisions/0012-roster-fit.md](decisions/0012-roster-fit.md).

**Roster Optimizer.** Several strong rosters under a budget. Set the payroll line (the
cap, the tax line, an apron, or an owner's figure), the roster size, how many players must
fill each role and each position group, anyone to lock in or leave out, an age range, a
highest salary and, if you like, a least projected rating; then ask for a number of rosters
that each differ from the others by at least so many players. Each roster is the best that
projects under all of it once the rosters before it are set aside. What is maximised is the
sum of the parts - the value model's projections added up for the minutes projected, with
replacement players filling the rest - held to two budgets: the payroll, and a season's
minutes. The value model misses a real team by about three points on seasons it had not
seen, and every figure carries that. Salaries come from your contract file, so the page
runs only once one is imported for the season ahead. Any roster can be saved into the Team
Builder, where the Roster Fit page will describe it. Nothing here is a recommendation; see
[decisions/0013-roster-optimizer.md](decisions/0013-roster-optimizer.md).

**Postseason Outlook.** How likely each stage of the playoffs is, as a model fitted to the
seasons on record and tested on seasons it had not seen estimates it. The model reads a
team by two things known before a playoff game is played: its regular-season net rating
and its *top-player quality*, the mean impact of its three best players by the value
model. Every chance is shown with its 95% interval, from refitting the model on resampled
seasons. *The model* also shows the season model read before the season - from the
rating the value model predicted for each team, averaged over its error - beside the
reading from the season played; the first is what a chance for a roster rests on.

- *A team's chances*: the sidebar's team, a roster you built, or a strength you set
  yourself, read as a team of that strength entering any season - the season model, a
  chain of steps from making the playoffs to the title. A built roster is the sum of its
  parts with the value model's error folded in. Under it, the same chance across net
  ratings, for the stage you pick.
- *Every team*: all the teams of the sidebar's season under the season model, ranked by
  the stage you pick, with what happened where the postseason is decided.
- *The bracket*: for a decided season, the sixteen playoff teams and their chances of
  every round as the model would have put them before the first game, from the regular
  season alone - the series model carried through the actual matchups - beside where each
  got to. It needs every entrant's inputs, and says who lacks them.
- *Series*: every series of the season with the chance given to the side that held home
  court, the favourite, and the result.
- *The model*: what it is and how it did on seasons it had not seen - against simpler
  methods, by round and by era, through the bracket and for every team-season - with
  reliability charts, what else was tried, and what the model cannot tell you.

The same as a document: [research/POSTSEASON.md](research/POSTSEASON.md); why it is built
this way: [decisions/0014-postseason-model.md](decisions/0014-postseason-model.md).

**Scenario Simulator.** What a change to a roster would do to its season. Start from a
real team as it stands for the season ahead (the players whose current team it is, with
the value model's projections) or from a roster you built; remove players, add anyone
with a projection, set the presets - games missed as projected, a healthy season or a
high-injury one; development as projected, optimistic or regression - and, player by
player, the games they miss, a development adjustment in points of impact, a share of
the minutes or a salary. Every one of those is your assumption, and the page says so.
Thousands of seasons are then drawn for the roster as it stands and with your changes,
from the value model's projections and the error of its test with the minutes projected,
a season's own noise, the wins a
point of rating is worth and the postseason model's season steps.

- *Before and after*: payroll, projected net rating, projected wins with an interval,
  and the chance of every stage, side by side; how the seasons drawn came out.
- *Players*: each player with the projection and the columns you can set; save the
  roster into the Team Builder.
- *Profile*: the roster's fit measures before and after, placed among the latest
  season's teams - description, as on the Roster Fit page.
- *The season ahead*: every team drawn as it stands, with nothing assumed.
- *The evidence*: the figures measured for the simulator and the wins test - how often
  the intervals of simulated wins held the wins that happened on seasons the value
  model had not seen.

The field is not in it: each roster is drawn alone, as a team of its strength entering
any season, so a trade that strengthens one team does not weaken another here. The same
as a document: [research/SIMULATOR.md](research/SIMULATOR.md); why it is built this way:
[decisions/0015-simulator.md](decisions/0015-simulator.md).

**AI Research.** Ask in plain words, and see what every answer rests on. A language model
on this machine (through Ollama) answers from the lab's tools - its statistics, its fitted
models (player value, roster fit, the postseason model and the scenario simulator), its own
documents, the contract file, this season's games, the league's transactions and injury
report fetched since the build, and pages on the web - and every figure in an answer is
checked against what the tools returned before you see it. A modeled figure comes with its
error: a chance with its 95% interval and the model's record on seasons it had not seen, a
scenario with the interval of the seasons drawn, a projection with how far projections of
players that well known have missed. Fit is described, never scored. A scenario's changes
are your assumptions, tagged as such. A scenario for the season ahead uses each player's
current team: name a player who is not on that team's roster and nothing is simulated -
the answer says which team the player is with. Questions looking back at a season already
played are answered from that season's figures.

- *Above the conversation*: whether the assistant can answer (and, when it cannot, what to
  do: start Ollama, or pull the model), whether web search is set up, and how fresh each
  current source is, the news feeds included; then the workspace, and one fold, *In this
  workspace*, that counts its findings, proposed rosters and experiment proposals, with a
  tab for each. *Below the conversation*, by the question box: Quick or Deep, *New
  conversation*, and *Fetch current information*, which fetches what is due by hand - a
  question fetches what it needs anyway. The page opens at its end, by the question box.
- *News and contracts*: recent reporting comes from Hoops Rumors' feeds - the one news site
  the lab reads directly, since the others it checked turn AI agents away or forbid
  automated reading - each headline with its date and how long ago it was; web search
  finds the rest, with the date a result's address shows where it shows one. Ask what has
  changed since your contract file, and the answer lists the moves since its date beside
  what the file holds, and how to update the file. A report never changes the lab's data,
  a roster or the contract file.
- *Experiments*: ask for an experiment that might improve one of the lab's tested models -
  player value, the postseason model, the simulator or the roster fit test - and the answer
  drafts a proposal under *Experiments to review*. The idea is the assistant's, in words,
  and untested; beside it is the lab's test, from the model's file and its decision: what a
  change must beat, how seasons are split, what is measured, the leakage to rule out, what
  was tried before, and the steps of the milestone that would build it. *Keep in the
  workspace* puts it in the workspace's *Experiment proposals*, where it can carry your
  note, and *Delete* removes it once you tick the box; *Download* gives it as a document.
  Nothing is applied: no model, setting or data changes, whatever you keep. The assistant
  drafts one only when asked.
- *Quick or Deep*: Quick for one fact or one comparison, Deep for a longer look - more
  tool calls, more time, the model thinking first. A question under way shows its steps
  as they come, and *Stop* ends it at the next step, keeping what was gathered: whatever the
  model was writing when you pressed it is not acted on.
- *Each answer* opens with its kind: supported, qualified (part answered; what is missing,
  limited or estimated is said), not enough to answer, a question back, or declined. A
  name with several readings - two players called Brown, a year that could be either
  season - is asked about before anything runs; choose one and the question is asked
  again with it. Under the answer: notes and limits, the kinds of number it rests on, each
  result's rows with the chart its tool chose and a CSV (an article or web page the answer
  names as "s2" is the row marked s2 under *Source*; times are UTC), the evidence (every
  source with its address and its dates: published, effective, fetched; each model file
  with its revision; each section of the lab's documents by file and heading - its fold
  names the kinds of source, the web included, and each source is led by an icon for its
  kind), and how it was answered (each step, the model, the rules' version, the time).
- *Names and sidebar*: names, seasons and teams are read from the question; where it names
  none, the workspace's focus stands in, then the sidebar's season and team. A "he" or
  "they" with nothing to point to is asked about. A link pasted into a question can be read.
- *Workspaces*: each piece of research has its own workspace, chosen at the top of the
  page. A workspace keeps every question and its answer as it came back - on this computer,
  apart from the lab's data, so rebuilding the data never touches it. A follow-up question
  reads only the conversation under way in its own workspace. *New conversation* starts
  afresh and keeps the earlier questions (*Show earlier conversations*). Under *Workspace*:
  its name, what you are working on, its focus (the season, phase, team and Team Builder
  roster its questions are about when they name nothing), and notes - yours, and summaries
  the assistant writes when you press *Summarize into the notes*. The assistant reads the
  notes as background, never as evidence. *Export* gives the workspace as a document to
  read or as data. *Archive or delete* puts a workspace away (restore it any time), clears
  its questions (notes, findings and rosters stay) or deletes it - each only once you tick
  the box. If the file that keeps the workspaces cannot be read - damaged, or made by a
  newer version of the lab - the page says so instead, and *Set it aside and start afresh*
  renames it beside itself (never deleting it) and starts a new one. Copies made before
  each upgrade of the file are in `data/assistant/backups/`.
- *Findings*: *Save as finding* under an answer keeps a copy of it, with your title and
  note, in the workspace's findings - it stays even if the history is cleared. *Edit*
  changes its title and note; *Delete* removes it once you tick the box.
- *Old answers*: each answer records the data build and player value model it read. When
  either has changed since, it says so, and *Ask again with today's data* asks the same
  question again beside it; the old answer is never rewritten. An answer that read recent
  games, moves, the injury report or the web offers the same once enough time has passed
  for the lab to fetch any of them again (half an hour, as the lab is set up).
- *Rosters to review*: ask for rosters - "three rosters for next season under a $150M
  budget", "a roster under the luxury tax with at least two rim protectors" - and the
  assistant runs the Roster Optimizer with what you asked for and nothing else. Each
  option found (two to four, each differing from the others by at least three players)
  appears under the answer: its payroll and what is left under the budget, its projected
  net rating with how far such forecasts typically miss, how it differs from Option A, what
  was asked for, the contract file's date, and its players with where each would start,
  their salaries and their forecasts. They are examples that fit the budget - options to
  compare, not a recommendation - and nobody has checked that the trades or signings to
  get them are allowed. Each option says first what has become of it: waiting, saved (and
  under what name) or declined. The assistant cannot
  save one. *Save approved roster* under an option saves it for the Team Builder - only
  if the data, the player value model and the salaries are the same as when it was
  proposed; otherwise it says what changed and saves nothing. A saved option says so, and
  is never saved a second time. *Decline* sets an option aside.
  Every option stays in the workspace's *Proposed rosters*, saved, declined or waiting, so
  you can come back and save one later. A saved roster's starters come from the nine
  players who play the most: each at a position they are listed at where the roster
  allows, and the best players by forecast first.
- *Ask AI about this*: the player, value, team, benchmark, Team Builder, roster fit,
  postseason and simulator pages have this button. It asks a question about what the page
  shows - its season, team, player or roster - in the workspace open here, without changing
  the sidebar. The answer comes back in short in the dialog, and in full in the workspace:
  *Open in AI Research*.

Nothing is saved to the Team Builder but a roster you approve. Web
search needs your own Ollama account's key, in the project's `.env` file as
`FOL_OLLAMA_API_KEY` (copy `.env.example` to `.env` and fill it in); without it the page
says so, and pasted links are still read. Some
sites ask AI agents not to read their pages, and the assistant does as they ask. Why it is
built this way: [decisions/0018-ai-research-assistant.md](decisions/0018-ai-research-assistant.md);
how it is measured: [AI_EVALUATION.md](AI_EVALUATION.md).

**Ask the Docs.** Questions about the lab itself - how a figure is computed, how a model was
tested, why something was chosen - answered from its own documentation, through the lab's
HTTP API (the capstone's page: [CAPSTONE.md](CAPSTONE.md)). Start the API first with
`fol api` (Docker Compose starts it for you); without it the page says so and the rest of
the workbench works as before.

- *Signed in already*: signing in to the workbench signs in to the API as well, when it is
  running. If it was not, the page asks for the same name and password once. *Sign out* here
  signs out of the whole workbench. Your questions and their answers are kept under your
  name, for you alone.
- *Build the index* the first time: the local model reads every passage of the documents,
  which took under twenty seconds on this computer's graphics card and takes longer without
  one. When the documents change, the page offers to build it again.
- *Ask the documents*: the answer comes from the five passages nearest your question,
  written by the local model, each sentence citing its passage like [2]. Every passage is
  listed under it - its document, its heading, how near it was - and opens to the words the
  model read; "(cited)" marks those the answer uses. A note says when a sentence was cut
  for a figure no passage holds, or when the answer cites nothing.
- *Your questions*: what you asked before, newest first, each with its answer and sources,
  and a delete that stays off until you tick its box. *Your account* deletes the account and
  every question in it, the same way.

The page reaches the API at `FOL_API_URL` (`http://127.0.0.1:8000` unless you set it).

**Data Health.** How the last build went, the state of each source, what is missing and
what that costs, every quality check, every adjustment the build made to source data,
what is held of each dataset, and any fetch that is failing.

## What it does not do yet

No simulation of the whole league at once: each roster is drawn alone, as a team of its
strength entering any season, so the Scenario Simulator does not say what a trade does to
the other side, and the chances of thirty teams need not add up. Trades, aging curves,
draft value and multi-year planning are the roadmap's last stage. The benchmarks give
historical frequencies, and player value is an estimate of what a player adds; the
postseason chances and the simulator's seasons are estimates with intervals from models
whose record on past seasons is a tab away, never a verdict on a team. A role is a rule
applied to a player's statistics, not a measurement of how they play, and the page says
so. Roster fit describes a roster and reports what the evidence found; it does not score
one. The optimizer's rosters are the parts added up under a budget, several of them,
never one answer. The AI Research assistant reads one news site's feeds and the web; it
does not yet propose experiments for the models, which comes with its next milestone.
