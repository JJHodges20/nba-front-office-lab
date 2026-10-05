# 0014 - Postseason chances come from a series model carried through the bracket, and a season model for a team before its season

Date: 2026-10-05. Status: accepted.

## Context

Version 6 of the roadmap asks for playoff-round and championship probabilities, and warns
about them more than about anything else: one champion a season makes a single classifier
vulnerable to class imbalance and overfitting; the model must be evaluated out of sample
and calibrated so that a displayed probability means what it says; and nothing predictive
may be shown before that. Decision 0009 kept the benchmarks as history for the same
reason, and left the forecast to this milestone.

The lab holds thirty seasons of every team's regular season and of every playoff game and
series, and - since milestone 9 - the value model's impact for every player of those
seasons. Two questions a front office asks are not the same question. Given the sixteen
teams in a bracket, how likely is each to win each round? And for a team whose season has
not been played - a roster being built - how likely is each stage of the postseason?

## Decision

### Two inputs, both known before a playoff game is played

A team is described by its regular-season **net rating**, as the league publishes it, and
its **top-player quality**: the mean impact, by the value model, of the three players with
the highest impact who finished the regular season with the team - the players a playoff
rotation leans on. Both are known when the playoffs begin, and both are things the lab can
say about a roster before a season: the sum of the parts is a net rating, and the three
best projected impacts are the second input.

### The series model: one game, carried through the format

The log-odds that the home side wins a playoff game are a home advantage plus a weight
per point of the gap in net rating plus a weight per point of the gap in top-player
quality, fitted by maximum likelihood to every playoff game on record (2,440 games,
1996-97 to 2025-26). On neutral ground - the 2020 bubble - the home advantage is nothing.

A series is the best of five or seven such games in a stated home pattern (2-2-1-1-1;
2-2-1 for the first round through 2001-02; 2-3-2 for the Finals through 2012-13), so its
probability follows by enumerating how the series can go. Set the sixteen teams in their
bracket and every team's chance of every round follows exactly: its chance of being there
one round earlier times its chance against whoever comes through the other side, summed
over who that might be. Home court in a matchup not yet fixed goes by the league's main
tie-breaks: record, head-to-head, seed within a conference, then net rating.

The model is fitted on games rather than series because there are five times as many of
them, and the format then costs nothing: a best-of-five first round and a 2-3-2 Finals
are the same game model in a different sequence.

### The season model: the roadmap's hierarchy

For a team before the bracket is known, the chance of each stage is a chain of conditional
steps - making the playoffs, for any team; winning a round, for a playoff team; the
conference finals, for a team that won a round; the Finals; the title - each a logistic in
the same two inputs, fitted on the teams that reached the stage before. The chance of a
stage is the steps up to it multiplied together, so the stages nest as they must, and the
thirty champions on record never carry a model of their own: that is the answer to the
roadmap's class-imbalance warning. The alternative, one classifier per stage fitted on
every team, was tried and is clearly worse.

### How it was tested

Every test is an expanding window: each season from 2006-07 on is scored with parameters
fitted to the seasons before it alone. The series model is scored on its 300 series;
carried through each season's actual bracket before a game was played, on where every one
of 320 playoff teams got to; and the season model on 600 team-seasons. Two scores - log
loss, the average surprise at what happened, and Brier - with a calibration slope
(outcomes regressed on the model's log-odds; 1 is a model whose chances mean what they
say) and reliability tables, predicted against observed in bands of predicted probability
with Wilson intervals. Intervals on the parameters, and on any probability the services
show, come from refitting on 2,000 resamples of whole seasons - the teams of one season
are not independent - and the file keeps 200 of the resampled parameter sets so that any
probability can carry its interval.

What revision 1 found:

| What was scored | Out of sample | Against |
| --- | --- | --- |
| Series | log loss 0.539; the favourite won 220 of 300 | 0.598 giving every series the home-court side's past rate; 0.693 a coin flip |
| Bracket: winning a round | 0.460, calibration slope 1.01 | 0.492 by seed |
| Bracket: the conference finals | 0.424 | 0.705 by seed; 0.562 coin flips |
| Bracket: the Finals | 0.288 | 0.457 by seed; 0.377 coin flips |
| Bracket: the title | 0.159; the title favourite won 8 of 20 | 0.163 by seed; 0.234 coin flips |
| Season model: making the playoffs | 0.250 | 0.691 the base rate |
| Season model: the title | 0.091 | 0.146 the base rate |

Calibration slopes run from 0.73 to 1.01 through the bracket and from 0.82 to 0.98 for
the season model; the series model's is 0.78, and over the last five seasons 0.61. The
model is somewhat too sure of itself at the extremes, and more so lately. The reliability
tables say where: series given 65% to 80% were won 66% of the time; bracket cases given
under 5% happened 2.4% of the time against the 1.3% said. No recalibration is applied -
it would be a correction fitted on the same test - and the chances are shown as they are,
with that evidence beside them.

### What else was tried

| Alternative | Change in log loss (negative is better) | Kept? |
| --- | --- | --- |
| Net rating alone, series model | +0.025 [+0.011, +0.039] | top-player quality stays |
| Net rating alone, season model | +0.007 [+0.002, +0.012] per stage | stays |
| The best player instead of the top three | +0.015 [+0.005, +0.024] | the top three |
| Playoff experience: the players' playoff games over the three seasons before, by minutes | +0.000 [-0.007, +0.007]; season model -0.001 [-0.006, +0.004] | left out: cannot be told from nothing |
| One classifier per stage instead of conditional steps | +0.003 [+0.000, +0.006] per stage | the hierarchy |
| Winning percentage instead of net rating, series model | -0.014 [-0.032, +0.007] | not distinguishable |
| Winning percentage instead of net rating, season model | -0.024 [-0.034, -0.013] per stage | **left out although clearly better** |
| The gap to the conference's eighth-best net rating, added | -0.011 [-0.020, -0.002] per stage | **left out although clearly better** |

Two alternatives beat the season model on seasons already played and are left out on
purpose; the reason is the model's purpose, not its score. A record out-predicts a rating
at every stage and most at the first - log loss 0.186 against 0.250 for making the
playoffs - because the playoffs are seeded by record, and a record carries the luck of
close games and the schedule that the seeding then rewards. The season model exists to be
read for a roster before its season, when there is no record; a projected record would be
the projected net rating by another name. For the same reason the field is left out: a
team's conference and the strength of the other teams that season are not known for a
roster being built. For a season already played, the bracket carried through the actual
matchups is the right reading, and the page says so.

### A fitted model is a file; nothing fits inside a page

`configs/models/postseason.yaml` is the specification people edit: the first test season,
how many top players, the neutral postseasons, the series formats and when they changed,
the reliability bands, the resamples. `configs/models/postseason.json` is the fitted
model with its evidence. `fol playoffs fit --write` writes it; the services read it;
`fol playoffs report --write` writes it up as `docs/research/POSTSEASON.md`. The model
names the value model whose impacts made its top-player quality, and the services say
when the database was built with another.

A build does not apply this model. Unlike player value, a chance is computed on request -
for the season, the team or the roster asked about - from the file.

## Consequences

- The lab now shows a probability. It is shown with its interval, beside what happened
  where the season is decided, and with the evidence a tab away; the roadmap's standing
  caution - an estimate, never a guarantee - is on the page and in every caption.
- Top-player quality is itself an estimate, from a value model whose weights were fitted
  on every season, the test seasons included. The postseason model's test is out of
  sample for its own parameters, not for the value model's. A stricter test would refit
  the value model inside every window; it was not done, and the limitation is stated.
- Home advantage has fallen across eras (0.54 log-odds over all seasons, 0.29 in the
  play-in era) and the model is fitted to every season at once. An era-weighted fit, or a
  recalibration estimated out of sample, is the first refinement to try; either would be
  tested the same way and kept only if clear of zero.
- The play-in is not modelled; a team that reaches the bracket through it has made the
  playoffs like any other. A twenty-team postseason model would need the play-in's own
  format.
- The fixture store (two valued teams of one season) can neither fit the model nor read a
  bracket, so fitting is tested on an invented league whose playoffs are played by a
  planted game model (`tests/league.py`, `tests/postseason_reference.py`): the model has
  to find the planted home advantage and slopes again, and its bracket arithmetic is
  checked against a bracket played a hundred thousand times.
- The series model's parameters are stored to four decimals with 200 kept draws; the file
  is about 130 KB and is regenerated, not edited.

## Amended in milestone 14

The season model is also scored as a forecast reads it, from the rating the value model
predicted before each season, averaged over its error: 0.517 in log loss for making the
playoffs against 0.250 from the season played and 0.691 for the base rate, with every
stage still beating its base rate. Refitting the value weights inside each window, to
keep top-player quality out of sample, was measured at +0.003 and left; see
[0016](0016-audit.md).
