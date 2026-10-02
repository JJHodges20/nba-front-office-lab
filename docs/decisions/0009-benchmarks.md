# 0009 - Benchmarks are frequencies with their uncertainty, compared within a season

Date: 2026-10-01. Status: accepted.

## Context

Version 2 of the roadmap asks what a successful team has looked like: how the teams
that made the playoffs, won rounds, reached the Finals and won the championship
differed from the rest. It warns against the usual way of answering - "50 wins makes a
contender" - and asks for historical frequencies and conditional probabilities instead,
with era and sample size taken into account.

Three things make this harder than it looks. There is one champion a season, so thirty
seasons give thirty champions. The league scores a fifth more than it did in 1997, so
raw figures from different seasons do not compare. And the teams of one season are not
independent cases: one team's win is another's loss, and only one of them can win the
title.

## Decision

**A benchmark is a frequency, never a threshold.** The lab reports how often the past
teams in a band of some measure reached a stage, with the number of teams in the band.
A band is a way of grouping - its width can be changed on the page - and nothing in the
lab says a team "needs" a figure.

**Every share carries its interval.** The 95% Wilson score interval is shown beside
each share and drawn on each chart. Wilson, rather than the textbook plus-or-minus,
because it stays inside 0 to 1 and does not collapse when no team, or every team, in a
band reached the stage: 0 of 40 is "rare on this evidence", not "never". Where no team
below a band reached a stage the lab says how many teams that is and what long-run rate
it is still consistent with.

**Stages are nested.** Reached the postseason (playoffs or play-in), made the playoffs,
won a series, reached the conference finals, reached the Finals, won the championship.
Each contains every later one, so a frequency can be given for all teams of a band or
only for those that had already reached an earlier stage - the conditional form the
roadmap asks for.

**Three devices make seasons comparable.**

- A record is put on the scale of a full season: wins per 82 games.
- A team's standing on a metric is its league rank within its own season. Ranks are
  what profiles of "what champions looked like" are drawn in; the few measures that
  mean the same in every era - wins per 82, net rating, ratings relative to the league
  average, seed - are also given in their own units.
- What separates teams is measured inside a season and only then added up.

**Separation is concordance within a season.** For a metric and a stage: take every
pair of one team that reached the stage and one team of the same season that did not;
concordance is the share of pairs in which the first has the better value, ties
counting half. One half is a coin flip. It needs no model and no assumption about the
shape of anything, it cannot be blurred by a league that changed, and it can be asked
against the whole league or only against the teams a team had to get past. It is one
metric at a time and says nothing about cause, and the page and the report say so.

**Its interval resamples seasons, not teams.** Because the teams of a season depend on
each other, the interval is a percentile bootstrap over whole seasons, with a fixed
seed so that the same data gives the same figures. With five seasons it is wide; that
is the honest answer.

**Eras are configuration.** `configs/eras.yaml` names the spans the roadmap lists - all
seasons, the last five and ten, the modern era, the Play-In era - each with the reason
it is drawn where it is. Where "the modern era" begins is a convention and is labelled
as one. Any span of seasons can also be chosen on the page. Only seasons whose
postseason is complete are counted.

**The research is a generated document.** `fol benchmarks --write` produces
`docs/research/BENCHMARKS.md` from the database, sentences included. Run after a
refresh it says what the data now says; nothing in it is typed by hand.

**History is not applied to the present.** The page and the report describe completed
seasons. They do not place a current team in a band and call the band's frequency its
chance: that is a forecast, and forecasts wait for a model evaluated on seasons it has
not seen (milestone 12).

## What was found in the data on the way

Through 2000-01 the league's published standings leave teams with identical records on
the same place - two fifth places and no sixth. A place in those seasons is therefore
not always the seed a team played from. The published place is kept (decision 0003), a
quality check reports the nine conference standings concerned, and benchmarks by seed
carry a note.

## Consequences

- Benchmarks need no fitted model, so there is nothing to overfit and nothing to
  validate out of sample; what they claim is only what happened.
- They are deliberately weaker than a model: they do not combine metrics, and they do
  not say what a metric adds once the others are known. That is milestone 12's job.
- Nothing is said about how contenders were built or what they cost. The lab holds
  player detail for recent seasons only and no contract history. Player history has to
  be extended before the player value work that needs it (milestone 9).
- A new era is a few lines of YAML. A new measure to band by is one line in
  `services/benchmarks.py`.
