# 0010 - Player value is a fitted model that has to out-predict simpler ones

Date: 2026-10-02. Status: accepted.

## Context

Version 3 of the roadmap asks which players give the most basketball value for their
salary, lists what value is made of (offensive and defensive impact, efficiency,
creation, shooting, rebounding, ball security, availability, age, playoff performance)
and adds a warning: a composite score must be validated empirically, and weights are not
objective because they make a tidy number.

A hand-weighted composite is the easy way to build this and the wrong one. Whoever picks
the weights picks the answer. The lab has thirty seasons of every team's results and of
every player's statistics, so the weights can be asked of the data, and - more to the
point - the result can be tested on seasons it was not shown.

## Decision

### What is estimated

A player's **impact**: the points per 100 possessions a team's net rating gains with the
player on the court, against the league's average minute. Offense and defense are
estimated separately and add up to it.

### How the weights are found

A team's rating in a season is modelled as the sum of its players' estimates, each
counted for the share of the minutes the player actually played, where every estimate
is built **only from seasons before the one predicted**. The weights are the ones that
make that sum come closest to what teams then did, fitted by least squares against the
team's offensive and defensive rating relative to the league.

So the weights are chosen for one thing: describing a player in a way that carries over
to the next season, on whatever team. That is the property a front office needs of a
rating, and it is a different thing from splitting up the credit for a season already
played.

An estimate for a player entering a season is

    reliability x (weights . features)
    + (1 - reliability) x (level + slope x minutes per game)
    + age slope x (age - 27)

- **Features** are rates per 100 possessions on the court, against the league of the
  same season: fifteen of them in eight groups (scoring efficiency, creation, spacing,
  rebounding, ball security, defensive activity, the team's results with the player on
  the court, and the results of the teams played for).
- **Earlier seasons are pooled** by minutes: last season in full, the one before at
  half, the one before that at a quarter.
- **Reliability** is weighted minutes over weighted minutes plus a ballast of 750. It is
  how much of the estimate the player's own numbers can carry.
- **The rest is assumed**, and the assumption depends on minutes per game, because that
  is all that is known about a player who has barely played. Playing time is used as
  evidence only where the numbers run out.
- **A player with no earlier season** gets one fitted level.

### How it is tested

One season at a time, from 2006-07, each predicted with weights fitted to the seasons
before it. Next season's minutes are taken as given, so the test is of the ratings and
not of anyone's ability to forecast playing time. The same test is run on simpler ways
of making the prediction, and the model has to beat them: every team is average; the
team's net rating last season; that, pulled toward average; and the players'
minutes-weighted on-court net rating, plus-minus and PIE.

On 600 team-seasons the model misses a team's net rating by 3.01 points (root mean
squared), against 3.38 for PIE, 3.54 for on-court net rating, 3.97 for last season's
rating pulled toward average, and 4.92 for calling every team average. Every difference
is clear of zero under resampling.

### What is reported with it

- Every weight has a 95% interval from resampling whole seasons. Teams of one season are
  not independent, so the season is the unit that is drawn.
- Every group of features is removed in turn and the test run again. Several groups
  cannot be told apart from nothing on this evidence (spacing, rebounding, ball
  security, defensive activity): they stay in because together the box score matters
  (0.10 points of error without it), and the report says so rather than implying that
  each weight is known.
- How closely a team's impacts add up to its own net rating in the same season: a
  correlation of 0.96, with the team's net rating 1.23 times the sum. Impacts are
  cautious estimates of ability, not an account of results, and nothing forces the two
  to agree.

### Season impact, projection, wins

- **Impact** is what one season showed: that season's features, trusted by its minutes,
  centred so that the league's average minute is zero. It has parts that add up to it.
- **The projection** is what was expected going into a season. It is the estimate that
  was tested.
- **Replacement level** is measured, not assumed: the minutes-weighted impact of
  players outside their team's ten most-used. On this data, -2.32.
- **Wins** are impact over replacement, times minutes, times the wins a point of net
  rating has been worth - fitted for each season on that season and two either side,
  because the figure has drifted from about 2.6 to about 2.35.
- **Projected minutes** come from a second, plainer model: next season's share of team
  minutes from the last three and age. It is tested the same way, against assuming last
  season's share.

### A fitted model is a file; a build applies it and never fits one

`configs/models/player_value.yaml` is the specification people edit.
`configs/models/player_value.json` is the fitted model: weights, intervals, levels and
every piece of evidence above. `fol value fit --write` produces it; `fol build` applies
it.

- The same raw store and the same model file always give the same values. Weights do
  not move because a stat correction arrived overnight.
- A change of model is a change in version control, with its evidence in the diff.
- Every row in `player_value_scores` names the revision that produced it.
- A build notes when seasons have finished since the model was fitted.

### A new layer

`modeling` holds the model: pure functions over frames, importing `domain` and
`analytics`. `pipelines` may import it, to apply a fitted model during a build, and so
may `services`. Modeled tables are rebuilt with the league tables but are not league
tables: a build is never refused for emptying one.

## Tried and left out

Each was run through the same test while the model was being designed, against the
form the model had at the time. None made the prediction better by an amount that could
be told from nothing; leaving them out keeps the model no larger than the evidence
supports.

| Idea | Error with it, against without |
| --- | --- |
| Adding a season's playoff minutes to it | Worse the more they count: 3.22 counted like any others, 3.26 at eight times, against 3.21 |
| Three-point accuracy as its own feature | 3.15 against 3.14 |
| Starts and minutes per game as features for every player | 3.08 against 3.08 once minutes per game informs the unproven part |
| A better starting level for high draft picks | 3.03 against 3.02; there are too few of them |
| A ridge penalty | No change at any strength tried |
| Height | 3.22 against 3.21 |
| Position | 3.16 against 3.21, with an interval that all but reaches zero |
| A fourth earlier season | 3.01 against 3.02 |
| Ballast from 500 to 1,000; season weights from (1, 0.5) to (1, 0.7, 0.4) | All within 0.02 of each other |

## Consequences

- Nothing in the lab calls a weight the worth of a steal. The weights are what thirty
  seasons of team results can tell apart, and several are wide.
- Defense is the weak side: a box score records little of it, and the model leans on
  the team's own defensive results, shared among the players who were there. A good
  defender on a bad defensive team is underrated, and the reverse.
- The model must be fitted again when a season finishes; a build says when.
- The fixture store cannot fit a model (one season, two teams), so tests of fitting use
  an invented league with planted weights (`tests/league.py`), and builds in tests apply
  the shipped model.
- Projected minutes know nothing about injuries, depth charts or contracts.
- Role versatility is not measured: nothing ingested describes it. Playoff performance
  was tested and adds nothing to next season's results; milestone 12 asks the different
  question of whether it matters in the playoffs.

## Amended in milestone 14

The test gave the model each season's minutes as played, which no forecast has. A
second test with the minutes projected by the minutes model - 3.63 points of net rating
against 3.01 - is in the file beside the first, and the forecasts carry it; see
[0016](0016-audit.md).
