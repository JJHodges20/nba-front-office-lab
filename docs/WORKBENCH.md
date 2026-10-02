# The Workbench

The workbench is the lab's interface: seven pages over the database, opened in your
browser.

```powershell
.\.venv\Scripts\fol.exe ui            # starts it and opens http://localhost:8501
.\.venv\Scripts\fol.exe ui --port 8600 --no-browser
```

It runs on your machine only and reads the database `fol build` produced. If there is
no data yet it says so and tells you to run `fol refresh`. Stop it with Ctrl+C.

## The frame

**Navigation** is at the top of the sidebar. **Filters** are below it and apply to every
page; a choice you make on one page still holds on the next.

| Filter | What it does |
| --- | --- |
| Season | Any season with team data, newest first. |
| Phase | Regular season or playoffs. |
| Team | Makes one team the subject. Clear it for the whole league. |
| Player | Makes one player the subject. Offered for seasons with player detail. |
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
  lab with a stated formula. *Estimate*: estimated by the lab. *Your assumption*:
  something you entered. There are no modeled values in this version.
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

**Player Explorer.** Every player of a season by category of metric. A player's profile:
percentile bars, form over trailing games, every season, game log, on/off ratings,
contract. Up to three players side by side.

**Team Explorer.** One team: record and ratings with league ranks, the four factors at
both ends, form over the season, the game log, what each player did for this team, every
season on record, and payroll against the cap lines.

**Contract Explorer.** Every salary in a season, team payrolls against the cap, tax and
aprons, and the configured cap rules with their sources. Empty until you import a
contract file; see [CONTRACT_DATA.md](CONTRACT_DATA.md).

**Analytics Lab.** Any two metrics against each other, for players or teams, with how
strongly they move together. How one metric is spread. Every team-season since 1996-97
with champions picked out. The metric glossary.

**Team Builder.** Rosters you assemble by hand. For each: payroll, share of the cap,
room under each line, how the roster stands against the roster limits, and what its
players add up to beside the league. Change a slot or type a salary of your own
directly in the table. It describes a roster; it does not rank or recommend players, and
its pooled figures are not a projection of how the players would play together.

**Data Health.** How the last build went, the state of each source, what is missing and
what that costs, every quality check, every adjustment the build made to source data,
what is held of each dataset, and any fetch that is failing.

## What it does not do yet

No value scores, no fit analysis, no optimiser, no probabilities. Those are later
roadmap stages, and nothing in the workbench presents an estimate as a prediction.
