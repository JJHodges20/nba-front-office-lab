# 0007 - Team metrics: published for a season, estimated and calibrated for a span

Date: 2026-10-01. Status: accepted.

## Context

The roadmap's team analytics are efficiency, point differential, pace and historical
outcomes, and it warns that raw scoring from different eras is not comparable without
league-relative context.

For a whole regular season the league publishes each team's possessions, pace and
ratings, counted from play-by-play. For anything shorter - the last ten games, a month,
a playoff run, one game - it publishes only box scores. The workbench needs both: the
season table, and form over a span.

## Decision

**A season's ratings are the league's.** Offensive, defensive and net rating and pace in
the season table are the published figures, passed through unchanged and tagged
`measured`. The lab does not recompute them.

**League-relative ratings carry the era adjustment.** Relative offensive rating is a
team's rating minus the league's average offensive rating that season; relative
defensive rating is the league average minus the team's defensive rating, so positive
is good for both. The league average is pooled - all points over all possessions - not
the mean of thirty team ratings. A 105 offense was average in 1996-97 and would be the
league's worst in 2025-26; the relative figure says so, the raw one does not.

**The four factors use the textbook definitions.** Effective field goal percentage,
turnovers per possession, offensive rebounds over offensive rebounds plus opponent
defensive rebounds, free throw attempts per field goal attempt - at both ends. Turnover
rate and assist percentage reproduce the league's published team figures to three
decimals in every fixture season. The league's team rebound percentage is a different
quantity (three to five points higher, not reproducible from box totals); the lab's is
the four-factors one and its description says so.

**A span of games uses estimated possessions, calibrated to the season.** Possessions
for a game are the mean of the two teams' box-score estimates
(`FGA + 0.44 x FTA - OREB + TOV`): both teams have, within one, the same number of
possessions, so averaging halves the noise. The estimate is then multiplied by a
per-season factor: the league's counted possessions that season divided by its
estimated possessions.

The evidence, over all 892 team-seasons since 1996-97, comparing a full season of
estimates with the league's counted figure:

| Estimator | Bias | Mean abs. error | Worst | Offensive rating: mean error (worst) |
| --- | --- | --- | --- | --- |
| Own box score | +1.57% | 1.57% | 3.21% | 1.65 (3.66) |
| Mean of own and opponent | +1.57% | 1.57% | 2.59% | 1.65 (2.93) |
| Mean, with the 1.07 offensive-rebound adjustment | -1.04% | 1.04% | 2.52% | 1.11 (2.54) |
| Own box score, calibrated per season | 0.00% | 0.32% | 1.39% | 0.35 (1.60) |
| **Mean of own and opponent, calibrated per season** | **0.00%** | **0.20%** | **0.86%** | **0.22 (0.94)** |
| Mean with the 1.07 adjustment, calibrated per season | 0.00% | 0.17% | 0.80% | 0.19 (0.79) |

With the chosen estimator a season's estimated offensive rating is within 0.22 of the
published one on average (worst 0.94) and net rating within 0.13 (worst 0.68). Net
rating is the robust one: the same possessions divide both the points scored and the
points allowed, so their error largely cancels.

The 1.07-adjusted variant, once calibrated, is closer still by 0.03 rating points on
average. It was not chosen: it needs a second empirical constant and more inputs for a
gain smaller than the noise of a ten-game span, and the simple formula is the one
already defined in `formulas.py` and explained in the glossary. The comparison is
recorded here so the choice can be revisited with the numbers in hand.

The calibration factor has stayed between 0.982 and 0.989 for thirty seasons, so it is
a stable property of how the league counts possessions, not a fitted model.

**An estimate is labelled as one.** In any view built from a span of games the service
lists the metrics that rest on estimated possessions (`estimated`: ratings, pace and
both turnover rates), and league-relative ratings are absent rather than approximated.

**Standings follow the league's order.** Conference rank is the league's published
rank, which already applies its tie-breakers and, in older seasons, its seeding of
division winners. Games behind is measured from the first-placed team.

**Outcomes are stated, not judged.** Each team-season carries how it ended - champion,
the round it lost in, the play-in, or missed the playoffs - derived from game results.
The history table holds every team-season with its ratings, their league ranks and that
outcome. It is the dataset benchmark research starts from; milestone 6 draws no
threshold or conclusion from it.

## Consequences

- The same team can show a slightly different rating in the season table (published)
  and in a full-season span (estimated). The difference is the estimator's error, which
  the tests bound.
- The calibration needs the season's league totals, so a span in a season with no
  team-season rows has no ratings.
- A single game's rating is noisy by nature; the game log shows it, but comparisons
  should use spans.
- Team opponent totals in the season table come from a different league endpoint than
  the game logs; rebound percentages built from the two differ in the fourth decimal.
