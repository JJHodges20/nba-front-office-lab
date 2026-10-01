# 0006 - Metrics: computed once, validated against the league, labelled by origin

Date: 2026-10-01. Status: accepted.

## Context

The roadmap requires that analytics own every calculation, that the interface never
recalculates a metric, and that measured statistics stay visibly apart from modeled
estimates. Player metrics come from two places: some can be computed from box-score
totals, others only from play-by-play, which the lab does not have.

## Decision

**One formula module.** `analytics/formulas.py` defines each basketball formula exactly
once. Everything else - the player table, a span of games, later the value engine and
optimiser - calls those functions.

**A missing rate is missing.** A rate whose denominator is zero or absent is NaN, never
zero and never infinite. A player who has taken no shots has no shooting percentage.

**Derived versus measured.**

- *Derived* metrics (true shooting, effective field goal percentage, turnover
  percentage, per-36 and per-100 rates, and so on) are computed by the lab from totals.
- *Measured* metrics (usage, assist and rebound percentages, on-court ratings, PIE) are
  the league's own, counted from play-by-play. They are passed through unchanged. The
  lab does not approximate them: a home-made number shown beside the league's would
  cast doubt on both.

Every metric carries a `MetricSpec` (`domain/metrics.py`) with its label, description,
display format, provenance and which direction is better, so a screen can label and
format it without knowing how it was produced.

**Validated against the league, not just against ourselves.** The league publishes
effective field goal percentage, true shooting percentage, assist-to-turnover ratio and
offensive rating next to the totals they come from. Tests apply the lab's formulas to
those totals and require the league's figure, to the published precision, for every team
and player in the fixture data. On the full store the agreement holds for all thirty
teams in the three seasons checked and for 477 players.

**Where the league defines something differently, the lab says so.** The comparison
turned up three such cases:

| Metric | The league's figure | The lab's choice |
| --- | --- | --- |
| Team turnover rate | Turnovers per possession | Same, for teams |
| Player turnover rate | Turnovers per 100 plays, counting assists as plays | TOV / (FGA + 0.44 x FTA + TOV), the more common definition; described as such |
| Team rebound percentage | Higher than OREB / (OREB + opponent DREB) by three to five points; its definition cannot be reproduced from box totals | The standard four-factors definition, stated in the metric's description |

**Estimated possessions are an estimate.** `FGA + 0.44 x FTA - OREB + TOV` runs one to
three percent away from the league's counted possessions. The lab uses counted
possessions wherever they exist and the estimate only for spans of games that have none.

**Comparisons are made within a qualified group.** Percentiles and ranks are computed
among players who meet a minimum of games and minutes. The thresholds are the analyst's
choice and are shown wherever a percentile is shown. Percentiles are oriented so that
higher always means better, including for turnovers, fouls and defensive rating.

**Pooling, not averaging.** A group's rate is computed from its pooled totals. The mean
of players' percentages weights a ten-shot season like a thousand-shot one.

## Consequences

- A metric's definition lives in one function and one `MetricSpec`.
- A span of games offers box-score metrics only; league-measured ones are absent rather
  than approximated.
- On-court ratings and on/off differences describe the lineups a player was part of as
  much as the player. The descriptions say so; the value engine must not treat them as
  individual measurements.
