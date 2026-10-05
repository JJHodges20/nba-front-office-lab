# 0015 - The simulator draws seasons from tested parts and calls every assumption the user's

Date: 2026-10-05. Status: accepted.

## Context

Version 7 of the roadmap turns roster construction into a what-if laboratory: modify a
roster and compare the expected effects on payroll, team strength and postseason
outlook, with a healthy season against average availability against a high-injury one,
expected development against optimistic improvement against regression, different
minute allocations, and "thousands of Monte Carlo season simulations once the model is
mature enough". Its own caution comes first: the outputs must come from tested models,
and the interface must identify them as estimates rather than guarantees.

By milestone 12 the lab had the parts: the value model's projection of every player
into the season ahead with its out-of-sample error (0010), a roster's sum of parts as
the optimizer and the Roster Fit page compute it (0012, 0013), and the postseason
model's season steps for a team of a given strength before its bracket is known (0014).
What was missing was a way to lay a user's assumptions over a roster and to draw seasons
from all of it with the uncertainty the tests measured - and nothing more.

## Decision

### A scenario is a roster plus assumptions, and the assumptions are the user's

A scenario starts from a subject - a real team as it stands for the season ahead (the
players whose current team it is, with their projections) or a roster built in the Team
Builder - and adds the players brought in, the players sent away, and for any player
the games they are expected to miss, a development adjustment in points of impact, the
share of the team's minutes they are to play, or a salary. Two presets cover everyone
without a figure of their own: availability (as projected, a healthy season, a
high-injury season) and development (as projected, optimistic, regression). All of it is
tagged *Your assumption* on screen, and a scenario can be saved as a Team Builder roster.

### A season is drawn from parts that were tested, plus five figures measured here

Each simulated season:

1. draws every player's impact around the value model's projection, by how well the
   model knew the player - the spread of past projections' misses in the player's
   reliability band, weighted by the minutes those players went on to play;
2. draws the games every player misses from the distribution of what rotation players
   (1,000 minutes or more) have missed, shifted to where the preset or the user's figure
   puts the mean; a projected share already allows for the typical missed games, so a
   healthy season gives a player a correspondingly larger share;
3. adds the parts up for the minutes drawn - five slots of replacement level plus what
   each player adds above it, scaled down where the shares run over a season - exactly
   as the optimizer does;
4. draws the miss on a team's strength that the value model's test leaves once the
   players' own spread is taken out, so that a roster's rating spreads by the tested
   error and no more;
5. adds a season's own noise - how far a season's net rating strays from the team's
   strength, measured from the spread of game margins - to get the rating the season
   shows, and turns that into wins with the wins a point of net rating has been worth
   plus the residual wins carry around a rating;
6. reads the postseason model's season steps for the chance of each stage, with the
   interval its resampled steps give.

The five figures measured for the simulator, on the real league:

| Figure | Value | Where from |
| --- | --- | --- |
| The value model's miss on a team | 3.01 | its out-of-sample test (RMSE) |
| A season's own noise | 1.58 | the standard error of each team-season's game margins, last ten seasons |
| Miss on a team's strength | 2.56 | the first less the second, in quadrature |
| Wins per point of net rating | 2.23 | fitted for 2025-26, as the value model fits it |
| Residual wins around a rating | 3.20 | wins per 82 less what the season's rating gives, last ten seasons |

With them, the spread of projections' misses by reliability band (2.04 points for the
least-known players down to 1.12 for the best-known, with a typical direction of +1.76
down to -0.22) and the missed-games distribution of 7,656 rotation player-seasons (mean
13.5%; a quarter miss over 21% of the season).

### The field is deliberately not in it

Each roster is drawn alone, as a team of its strength entering any season: the
postseason model's season model, not its bracket. A full league simulation - thirty
rosters, a schedule, standings, a play-in and a bracket - would need a model of the
field that the lab has not tested, and would double-count luck unless the parts were
re-derived. The limitation is stated on the page and in the report; the season ahead
is drawn for every team the same way, so the thirty chances need not add up.

### The wins are tested the way everything else is

For each of the 600 team-seasons the value model predicted out of sample, 2,000 seasons
are drawn from the predicted rating with the value model's miss and the residual wins
carry, and the wins that happened are set against them. The 50%, 80% and 95% intervals
held the wins that happened 53%, 83% and 97% of the time; the median season missed by
6.0 wins on average (7.6 RMSE) against 12.5 for giving every team an even record. An
interval that holds what happened about as often as it claims is one a reader can lean
on, and the test is in the file and on the page.

### Nothing is fitted on a page

`configs/models/simulator.yaml` is the specification: the seasons the noise is measured
over, the reliability bands, the rotation threshold, the quantiles kept, the test's
draws and levels, the interval shown, the seasons drawn. `configs/models/simulator.json`
holds the measured figures with the test; `fol simulate fit --write` writes it, the
services read it, and `fol simulate report --write` writes it up with the season ahead
as drawn for every team. A build applies nothing of it.

## Consequences

- The before-and-after table the roadmap sketched exists: payroll, projected rating,
  projected wins with an interval, the chance of every stage - every figure the mean of
  thousands of seasons from the parts the lab tested, and every input a stated
  assumption.
- A roster's spread is calibrated to the value model's tested error, not to the sum of
  the players' spreads; removing a player therefore changes the mean more than the
  spread, which is what the evidence supports.
- Development presets move every player by the typical miss of players known that
  well. The least-known players' projections have run optimistic by 1.8 points; the
  "as projected" preset includes that correction, and the table on the page says so.
- The invented league now plays regular seasons from a planted game model, so the
  measurements can be checked by hand and the wins test runs on a value model fitted to
  the league. The fixture store, with one season of players, measures what it can: the
  players the value model never valued count as its least-known projections.
- A persistent store of scenarios (`simulation_results` in the roadmap's data model) is
  not kept: a scenario is a few assumptions over a roster, and the roster is what
  persists. Saving a scenario as a roster covers the use the roadmap describes; a store
  of named scenarios with their results is the next refinement if the user wants one.
- The season ahead as drawn depends on who the projections say is on each team now;
  a roster move after the last fetch is not seen until the next refresh.
