# 0013 - The optimizer maximises the sum of the parts under two budgets and returns several rosters

Date: 2026-10-04. Status: accepted.

## Context

Version 5 of the roadmap is the first optimisation stage: the user sets a payroll budget
and roster requirements and the engine searches for strong rosters that satisfy them. Its
example asks for two primary creators, four reliable shooters, two strong perimeter
defenders, a rim protector and a backup center under $165M with a projected net rating of
at least +5; its objective is "Projected Team Quality + Roster Fit + Contract Value"
subject to salary, roster, role, position and cap-rule constraints; and it asks for
locks, exclusions, age and salary limits, a choice of payroll line, and several distinct
solutions rather than one, "because optimization weights are assumptions".

Two earlier decisions settle most of the objective. The value model (0010) is the lab's
only tested estimate of what a player adds, and its projections for the season ahead are
what a roster is built from. The fit evidence (0012) found that no fit measure, alone or
together, predicts beyond the players' impacts added up, so there is no validated "Roster
Fit" term to maximise. And contract value, under a payroll budget, is what the budget
constraint buys: maximising quality per dollar of a fixed budget is maximising quality.

## Decision

### The objective is the sum of the parts

A roster's projected net rating is five slots of replacement level plus what each player
adds above replacement for the share of a season's minutes the player is projected to
play - the value model's projection, each player taken alone. That is what the optimizer
maximises, with the value model's out-of-sample error (about three points of net rating
for a real team) attached to every figure it shows. Among rosters that project alike it
prefers the cheaper, by a weight so small it never trades a real difference.

Fit enters as requirements: at least so many players who fill each role, by the
archetype rules of the latest season, and so many by position group. A front office may
want two creators and a rim protector whatever the evidence says about prediction; the
optimizer honours that and scores none of it.

### Two budgets bind

The payroll may not exceed the line chosen: the salary cap, the luxury tax line, either
apron, or an owner's figure; it may be required to reach the minimum team salary as well.
And the players' projected minutes may not exceed a season's by more than a little
(a tenth, by default): fifteen players who each expect to play most of every game are not
a roster anyone can play, and the quality the model projects for them assumes the
minutes they are projected. Where a roster's minutes do run over, everyone plays a little
less and the rating shown is scaled down to say so.

The other constraints are the roadmap's: roster size within the season's limits, locked
players held, excluded players left out, age and salary limits applied to the pool, and
an optional least projected rating - which, when nothing reaches it, is dropped with a
plain statement of the best that could be reached rather than an empty answer.

### Several rosters, each distinct

The search is an integer programme, solved exactly (HiGHS, through SciPy). After each
roster is found, a cut forbids any roster sharing more than all but a few of its players
(three by default), and the search runs again, so the rosters come back best first and
each is the best of what remains. The comparison across them - what changes, what it
costs, what it projects - is the point; one roster alone would invite the reading the
roadmap warns against.

### Where the pool comes from

The pool is every player with a projection for the season ahead and a salary for that
season on file. Salaries come only from the user's contract file (0004); a player without
one cannot be placed, and the page says how many projected players that leaves out. Roles
and groups come from the latest season played. Rosters are built for the season the
value model looks ahead to, from the roles of the season before it, and for no other.

### What comes out, and where it goes

Each roster: its players with salary, projection and roles; the payroll against the
season's lines; the room under the budget; the share of a season its minutes cover; the
roles and groups it holds; and what it swaps against the first. A roster can be saved into
the Team Builder, where the five largest projected shares start in slots that suit their
groups, and the Roster Fit page will describe it like any other. (Amended at A6, at the
user's wish: the starters are chosen from the nine who play the most, each at a position
they are listed at where the roster allows - `domain/lineup.py`, decision 0018. Amended
again at A7, also at the user's wish: of the lineups that fit, the one with the most
projected impact starts, not the one that plays the most.)

## Alternatives considered

- **Roster Fit in the objective**, as the roadmap's formula has it. Rejected by the
  evidence of 0012: on 510 team-seasons the measures add nothing beyond the sum of the
  parts and together make its predictions worse. If lineup data is ingested later and a
  measure earns its place, the correction the fit service applies would carry into the
  objective without a change of design.
- **Contract value in the objective.** Under a fixed budget it is double counting; the
  surplus of a roster's contracts is a fact to report, and the Player Value page reports
  it where a market line can be read off the contracts on file.
- **A heuristic search** (greedy, local improvement). Faster to write, not exact, and
  silent about why nothing was found. The exact programme reports infeasibility and its
  diagnoses name the requirement that cannot be met.
- **A single minutes model** that redistributes playing time among the chosen players.
  That is a lineup model the lab does not have; the linear minutes budget with a stated
  slack keeps the arithmetic honest without pretending to one.

## Consequences

- The optimizer can be no better than the value model's projections, and says so with
  the model's error on every figure. It presents estimates, several of them, never a
  recommendation.
- Without a contract file there is no pool. The page says what it needs; the demo lab
  and the tests use invented salaries, labelled as such.
- Requirements are the user's. The roadmap's example is the form's starting point, not
  a finding; nothing "needs" two creators.
- The projection, the roles and the cap rules are versioned elsewhere; the optimizer
  reads whatever the build and the files hold and names the seasons it builds for.
