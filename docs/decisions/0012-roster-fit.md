# 0012 - Roster fit is described, placed among real teams, and tested beyond the sum of the parts

Date: 2026-10-04. Status: accepted.

## Context

Version 4 of the roadmap asks: "Do these players actually make sense together?" It wants
a roster judged on complementary skills, missing roles and redundancy "rather than
treating a roster as the sum of independent player ratings", and lists six areas of fit
questions - offense, defense, the possession battle, structure, depth and usage. Version
5 then means to put "Roster Fit" into an optimiser's objective beside projected quality
and contract value, and to constrain rosters by role counts.

By the end of milestone 9 the lab has, for every player-season since 1996-97, a season
line, the value model's estimate of impact, and the roles filled by rule. A roster's
fit can be *described* from those. Whether the description says anything that the
players' impacts added up do not is a different question, and the roadmap's standing
caution applies in full: a fit score would be a composite, its weights would be opinions
unless the data chose them, and nothing may enter an objective before it has been
validated out of sample. The literature on lineup synergy from box scores gives small
effects that are hard to tell from noise; the lab had to find out for itself.

## Decision

### A roster is described by measures in the roadmap's six areas

Thirty-two measures (`domain/fit.py`), each one answer to one of the roadmap's
questions from what the lab can see: role counts in the rotation (creators, spacers,
perimeter defenders, switchable wings, rim protectors), minutes-weighted averages of the
players' rates (three-point attempts and regressed accuracy, free-throw rate, assist
percentage, steals, blocks, rebound and turnover percentage, height), shares of the
minutes by guards, wings, big men and two-position players, the bench's impact and
roles, how much rests on one player, what the players' usage rates add up to with five
on the floor and what the three highest add up to - and the sums of the parts: the
players' impacts added up for the minutes given, as what the season showed and as
projected going in.

Every measure weighs a player by the minutes played for the roster: a real team's players
by the minutes they played for it, a built roster's by the minutes they played in the
roster's statistics season. Roles are counted among the rotation, the ten players with
the most minutes, and the bench is the sixth to tenth - conventions, written down. A
player with no statistics to profile counts toward `unprofiled_share` and nothing else.
The definitions live in the domain so that the table that stores them, the catalog that
labels them and the code that computes them all read off one list.

### Every real team-season is profiled, and a roster is placed among them

`team_fit_profiles` holds every team-season's profile, rebuilt by every build after the
value and archetype tables, since it rests on both. A built roster, or a real team, is
profiled with the same code and set beside the teams of its own season as a percentile
and a rank - within the season, so that eras compare, and as a description: no measure
has a threshold, and the direction that is "better" is stated only where it is
unambiguous. Two quality checks hold the profiles to the league's own arithmetic: a real
team's usage rates add up to five players' worth, and its players cover its minutes.

### Whether fit adds anything is tested the way the value model was

The value model's test predicted every team-season from 2006-07 on from its players,
each taken alone, and recorded what every prediction missed. Fit would show in those
misses, if it shows anywhere. So each measure was computed from the players'
*previous-season* profiles, weighted by the minutes they then played for the team - what
a front office knew when it assembled the roster, with nothing of the season predicted
leaking in - and asked, one season at a time with only earlier seasons to learn from,
whether it explained the misses. Then all the measures together, and the combined
correction with each area left out. Corrections are least squares with an intercept on
standardised measures; intervals come from resampling whole seasons. The sums of the
parts are not candidates: they are what fit is measured beyond.

The evidence is a file (`configs/models/roster_fit.json`) gathered by `fol fit test
--write` under a specification people edit (`configs/models/roster_fit.yaml`), stamped
with the value model and the role rules it was measured against; the services read it
and the pages say when it is behind what the database holds. A correction is applied to
a roster's sum of parts only if the measures together leave the value model's
predictions missing by clearly less.

### What the evidence says, and what follows from it

On 510 team-seasons, 2009-10 to 2025-26, the value model's predictions missed by 2.96
points of net rating. No measure, on its own, left them missing by clearly less: every
change in error lies within ±0.02 of zero and none is distinguishable from nothing.
Steals, perimeter defenders and assist percentage have coefficients clear of zero when
fitted on every season at once (+0.34, +0.32 and +0.22 points per standard deviation),
and what they explain in one season does not carry to the next. All the measures
together leave the predictions missing by *more* - 3.14 against 2.96, clearly - which is
what fitting many weights to few seasons does when there is nothing to find; the
correction is better without every area it was tried without.

So **no fit correction is applied to rosters**. The Roster Fit page shows a roster's
profile as description and its sum of parts as the estimate, and says so in those words.
For version 5 the consequence is direct: "Roster Fit" does not enter the optimiser's
objective as a validated term. Role coverage can constrain rosters, because a front
office may want two creators and a rim protector whatever the evidence; it does not
score them.

Where the champions' rosters stood is reported too, as history: all thirty champions were
in the top third of their season on the sum of the parts, and two in three on floor
spacers, assist percentage, rebounding, the bench's impact and the top three's usage.
That is what strong rosters have looked like, not a recipe, and the test above is what
says whether any of it matters beyond the parts.

### Where it lives

`domain/fit.py` (the measures), `domain/fit_model.py` (the specification and the
evidence), `domain/tables/fit.py` (`team_fit_profiles`), `modeling/fit/profile.py`
(profiles), `modeling/fit/evidence.py` (the test), `pipelines/fit.py` (the table in a
build; the evidence on request), two quality checks, `services/fit.py` (`FitService`:
a team or a built roster profiled and placed, the coverage of roles, the sum of parts,
the champions), `services/fit_report.py` and `fol fit report --write`
(`docs/research/ROSTER_FIT.md`), `fol fit test` and `fol fit show`, and the **Roster
Fit** page.

## Alternatives considered

- **A fit score with chosen weights.** The roadmap's own caution rules it out, and the
  evidence shows what such weights would have been worth out of sample: less than
  nothing.
- **Same-season profiles for the test.** A team that shot well had a good offense; a
  measure read off the season predicted is partly the outcome. Previous-season profiles
  cost a little information and keep the question honest.
- **Lineup data.** Which five played together, and how those fives did, is the direct
  way to ask about fit. It needs tracking-era endpoints, recent seasons only, and a
  fetch the lab has not taken on; it remains the obvious next step if fit is to be
  measured rather than described.
- **Fewer measures in the combined test.** With 27 measures the combined correction
  overfits; a chosen few would overfit less. But choosing them after looking is the
  thing the test exists to prevent, and the measures alone already answer the question.

## Consequences

- Fit is a description with a stated reference: a roster's measures and where they stand
  among the season's teams. Nothing on the page scores a roster.
- The sum of the parts is the estimate of a roster, with the value model's error, and the
  optimiser of milestone 11 can use it; role coverage can constrain, not score.
- The evidence is versioned and regenerated like the value model: a new value model or a
  change to the roles calls for `fol fit test --write`, and the page says so.
- If lineup data is ingested later, the same test applies to any measure built from it,
  and a measure that earns its place would turn the correction on without a change of
  design.
