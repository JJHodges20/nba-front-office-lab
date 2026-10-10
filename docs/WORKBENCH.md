# The Workbench

The workbench is the lab's interface: fourteen pages over the database, opened in your
browser.

```powershell
.\.venv\Scripts\fol.exe ui            # starts it and opens http://localhost:8501
.\.venv\Scripts\fol.exe ui --port 8600 --no-browser
```

It runs on your machine only and reads the database `fol build` produced. If there is
no data yet it says so and tells you to run `fol refresh`. Stop it with Ctrl+C.

## The frame

**Navigation** is at the top of the sidebar, in six groups: League, Explore, Build,
Forecast, Ask and System. **Filters** are below it, and a choice you make on one page still
holds on the next. Each page reads the filters it can use: the League Overview, the
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

**Data status** is at the foot of the sidebar on every page: when the league data was
last fetched, whether a contract file has been supplied, and which build is on screen.

## Reading a page

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
file. For a static image use the camera button that appears at the chart's top right;
it saves a PNG at twice screen size.

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
file, see [CONTRACT_DATA.md](CONTRACT_DATA.md).

**Analytics Lab.** Any two metrics against each other, for players or teams, with how
strongly they move together. How one metric is spread. The metric glossary.

**Team Builder.** Rosters you assemble by hand. For each: payroll, share of the cap,
room under each line, how the roster stands against the roster limits, and what its
players add up to beside the league. Change a slot or type a salary of your own
directly in the table. It describes a roster; it does not rank or recommend players, and
its pooled figures are not a projection of how the players would play together.

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
on this machine (through Ollama) answers from the lab's tools - its statistics, its models'
files as later milestones add them, the contract file, this season's games, the league's
transactions and injury report fetched since the build, and pages on the web - and every
figure in an answer is checked against what the tools returned before you see it.

- *Above the conversation*: whether the assistant can answer (and, when it cannot, what to
  do: start Ollama, or pull the model), whether web search is set up, and how fresh each
  current source is. *Fetch current information* fetches what is due by hand; a question
  fetches what it needs anyway.
- *Quick or Deep*: Quick for one fact or one comparison, Deep for a longer look - more
  tool calls, more time, the model thinking first. A question under way shows its steps
  as they come, and *Stop* ends it at the next step, keeping what was gathered.
- *Each answer* opens with its kind: supported, qualified (part answered; what is missing,
  limited or estimated is said), not enough to answer, a question back, or declined. A
  name with several readings - two players called Brown, a year that could be either
  season - is asked about before anything runs; choose one and the question is asked
  again with it. Under the answer: notes and limits, the kinds of number it rests on, each
  result's rows with the chart its tool chose and a CSV, the evidence (every source with
  its address and its dates: published, effective, fetched), and how it was answered
  (each step, the model, the rules' version, the time).
- *Names and sidebar*: names, seasons and teams are read from the question; the sidebar's
  season and team stand in where it names none. A link pasted into a question can be read.

The conversation lasts until the tab is closed or reloaded, and nothing is saved. Web
search needs your own Ollama account's key, in the project's `.env` file as
`FOL_OLLAMA_API_KEY` (copy `.env.example` to `.env` and fill it in); without it the page
says so, and pasted links are still read. Some
sites ask AI agents not to read their pages, and the assistant does as they ask. Why it is
built this way: [decisions/0018-ai-research-assistant.md](decisions/0018-ai-research-assistant.md);
how it is measured: [AI_EVALUATION.md](AI_EVALUATION.md).

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
never one answer. The AI Research assistant cannot yet use the value model, roster fit,
the postseason model or the simulator, or keep a conversation past the session; those come
with the assistant's later milestones.
