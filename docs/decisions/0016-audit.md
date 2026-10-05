# 0016 - A forecast carries the error of the test that forecast, and the audit's other rulings

Date: 2026-10-05. Status: accepted.

## Context

Milestone 14 is the roadmap's full-system audit: architecture, leakage, tests, the
workbench, documentation and performance, reviewed against the lab's own rules. The
findings are in [AUDIT.md](../AUDIT.md). Most were corrected without a decision to
record; the ones below change what a number means or how the lab is built, and the
rules that follow from them are now in `CLAUDE.md`.

## Decisions

### The error a forecast carries is the one measured with the minutes projected

The value model's out-of-sample test gave the model each season's minutes as played,
and reported a miss of 3.01 points of net rating. The lab's forecasts - the optimizer's
rosters, the simulator's seasons, the chances read for a roster - project minutes as
well as impacts, so that figure flattered them. The model is now tested a second time
with the minutes projected by the minutes model fitted on earlier seasons, replacement
level standing in for whatever those shares leave of the five on the floor, and who
played for whom still taken from the season (a forecast knows a roster): 3.63 points,
the projected minutes covering 87% of the floor. Both figures are in the model file and
on the Player Value page; the optimizer, the simulator and the postseason model's
before-the-season reading carry 3.63. The first test stays, as the measure of the rating
alone, and the comparisons with simpler methods are made on it, since every method is
given the same minutes there.

### The season model is also scored as a forecast reads it

The season model was evaluated on each team's actual regular-season net rating and top
players, while the pages read it for a roster before a season. The fit now also scores
it from the rating the value model predicted for each team-season before it was played,
averaged over that prediction's error by the same quadrature the service uses, with the
top-player quality typical of such a rating, the steps and the typical quality fitted
on earlier seasons. Making the playoffs scores 0.517 in log loss read that way against
0.250 from the season played and 0.691 for the base rate; the title 0.112 against 0.091
and 0.146. Every stage beats its base rate; the gap between the two readings is the
price of forecasting, and it is shown beside the chances rather than hidden in the
better figure. What is not done: refitting the value weights inside each postseason
window to keep top-player quality out of sample, measured at +0.003 log loss.

### Fitted files are refitted in order, and each names the others

A refit of the value model changes the model version the build applies, which the
postseason model and the simulator record and the workbench checks. The order is value
fit, build, postseason fit, simulator measurement, fit evidence, then the research
documents; the research headers say so. A workbench status is cached on the build id
and on the model files' last-changed stamps, so a refit is seen without a rebuild or a
restart.

### The lab remembers what it reads within one answer

Services read fresh so that a rebuild in another process is seen at once, and that
stays. Within one answer that reads the same tables many times over - a season drawn
for thirty teams, a scenario before and after - a service asks the lab to remember what
it reads (`Lab.remembering`), and the memory ends with the block. No cache is shared
across answers in the services; pages cache on the build id as before.

### A value-for-money line is fitted on request, and that is allowed

`services/value.py` fits the line of salary against wins when the Value for money tab
opens. It is a description of the contract file the user supplied, recomputed when the
file changes, with its fit shown; nothing is projected from it and no other figure
depends on it. The rule that nothing is fitted on a page or in a service refers to the
models whose estimates the lab carries forward, and this is not one of them.

### Tables decided against are not planned

`model_predictions` and `simulation_results` from the roadmap's data model are removed
from the planned tables: chances are computed on request from the model file (0014),
and a scenario is kept as a roster (0015). Lineups stay listed as deferred, with no
milestone.

## Consequences

- The simulator's intervals widened to the honest error and now hold the wins that
  happened 51%, 81% and 96% of the time for the 50%, 80% and 95% intervals.
- The optimizer's rosters state 3.63 as their error, and the Roster Fit page keeps 3.01
  for a team-season whose minutes were played.
- Every model file is at revision 2, fitted against the others' revision 2, and every
  research document is regenerated from build 14.
- During a season, the optimizer's and the simulator's pools keep the players who have
  already appeared in it, with their projections.
