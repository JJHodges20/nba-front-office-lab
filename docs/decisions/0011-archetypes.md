# 0011 - Archetypes are rules: the weakest percentile on a role's measures, within a season

Date: 2026-10-04. Status: accepted.

## Context

Version 3 of the roadmap asks for player archetypes - primary and secondary creators,
floor spacers and movement shooters, point-of-attack defenders, switchable wings, rim
protectors, stretch bigs, connectors - so that the fit engine of version 4 can ask what a
roster covers and what it lacks. The roadmap's own list is the set of roles.

There are two ways to produce them. One is to discover groups in the data - cluster
players on a bag of statistics and name the clusters afterwards. The other is to write
the rules down. Clusters move when the data changes, cannot be read without a key, and
would be built on the same box-score measures a rule would use, with less to say for
themselves. The lab has no tracking data: it cannot see who a player guarded, whether a
shot came off movement, or who set the screen. The tracking datasets on stats.nba.com
were looked at and left out of this milestone: they begin in 2013-14, so nothing built on
them could be followed over the thirty seasons the rest of the lab covers, and they would
add a large, slow fetch for measures that would still be proxies.

## Decision

### A role is a rule in configuration

`configs/archetypes.yaml` defines every archetype: the measures a player has to be
strong on *together*, the group of players the role is open to (everyone, guards, wings,
big men, low-usage players), its own cut-off where it differs from the shared one, a
ceiling where one tier ends and the next begins (a secondary creator stops where a
primary one starts), and a note saying what the measures stand in for and what they
cannot see. The set has a version, every row of `player_archetypes` carries it, and the
rule for changing one is: edit, raise the version, rebuild. Nothing is fitted.

### The score is the weakest percentile

Within a season, and among the players the role is open to, each measure is turned into
a percentile - the share of that group the player is ahead of, ties counting half. A
player's score for the role is the *lowest* of their percentiles on its measures. Being
strong on one measure and ordinary on another is not the role; a weighted composite
would let one measure buy the other, and the weights would be somebody's opinion.

A player fills a role from its cut-off up. The shared cut-off is 67 - the top third of
the group on every measure - and the primary creator's is 85, which is about one player a
team. Both are conventions, so the score is stored beside `fills` and anything built on
roles can draw its own line. Of the roles a player fills, the one with the highest score
is the primary role; the earliest defined wins a tie. Players under 500 minutes in a
season are given no role: too little to go on.

Percentiles within a season keep eras comparable: a floor spacer of 2004 is one against
the shooters of 2004, not against those of 2025.

### The measures are what thirty seasons can see

Ten measures, all from the player's season line or the value model: usage, assist
percentage, three-point attempts per 100 possessions, three-point accuracy with 240
league-average attempts mixed in (a few hot nights do not make a shooter), steals and
blocks per 100 possessions and the two together, assists per turnover, true shooting,
and the value model's defensive impact. Groups come from the listed position and height:
guards are listed at guard; wings are listed G-F, F-G or F and stand 6'5" to 6'10"; big
men are listed at center or stand 6'11" and taller; low-usage players are the bottom 40%
of the season by usage.

The three defensive roles lean on the value model's defensive impact, because steals and
blocks alone would make a gambler a defender. So they need a fitted model: in a project
without one they score nobody, and a build note says so and says what to run.

### Nothing is fitted, so persistence is measured instead

A rule has no accuracy to test. What can be checked is whether a role is a lasting trait
of a player or a one-season accident. For each role, among the players scored for it in
two seasons running: the share of those who filled it in the first season who filled it
again in the second, set against the share of everyone scored in the second season who
filled it - what "again" would be if the role told you nothing. The figures are shown
beside every role on the page and in the research document, and they are the only
empirical statement the lab makes about a role.

On the real data (rules version 1; 2025-26 for the counts, every season on record for the
rates):

| Role | Scored | Fill it | Fill it again | Anyone does |
| --- | --- | --- | --- | --- |
| Primary Creator | 378 | 24 | 64% | 6% |
| Secondary Creator | 378 | 52 | 54% | 13% |
| Floor Spacer | 378 | 63 | 58% | 21% |
| Perimeter Defender | 199 guards | 35 | 64% | 21% |
| Switchable Wing | 135 wings | 26 | 65% | 21% |
| Rim Protector | 81 big men | 15 | 66% | 21% |
| Stretch Big | 81 big men | 13 | 49% | 12% |
| Connector | 151 low-usage | 13 | 38% | 10% |

Every role is filled again several times more often than by anyone at all. The connector
carries over least, and its note says so.

### Where it lives

The definitions and their validation are `domain/archetypes.py`, loaded by
`config/archetypes.py`. `modeling/archetypes.py` computes the measures and groups, scores
every player against every role, and measures persistence. `pipelines/value.py` adds the
`player_archetypes` table after the value table, since the defensive roles depend on it;
the table is modeled, rebuilt by every build, keyed by player, season and archetype. A
quality check (`one_primary_archetype`) holds that a player who fills any role has
exactly one primary role and that it is one of the roles filled. `ValueService` reads the
roles back (`roles`, `role_players`, `role_summary`), the Player Value page has a Roles
tab, the research document has a section, and the Player Explorer lists each player's
main role.

## Alternatives considered

- **Clustering.** Groups without names, that move with the data and cannot be read or
  argued with. The scores a rule produces are as usable by the fit engine and far easier
  to explain.
- **Tracking data.** Left out of this milestone: recent seasons only, a large fetch, and
  still proxies. A tracking-based measure can be added later as a new key with a new
  version of the rules.
- **A composite score per role.** Lets one measure buy another and needs weights nobody
  can justify. The minimum is the rule that matches the words "strong on both".
- **Fixed cut-offs in absolute units** (so many threes per 100 possessions). Not
  comparable across eras; a percentile within the season is.
- **Reading the offensive half of "switchable wing", or the screening of a "connector",
  from the data.** Not possible from box scores. Each role's note says what its
  measures stand in for rather than pretending otherwise.

## Consequences

- A role is readable and versioned, and anyone can change it by editing a file and
  rebuilding. It is a rule, not a finding, and the page says so in those words.
- Roles follow the value model: fitting it again moves the defensive roles, and a project
  with no fitted model has none of them.
- The fit engine (milestone 10) can count what a roster covers by role, with scores to
  hand, and must treat a cut-off as the convention it is.
- The persistence figures say a role is stable, not that it is right. The lab has no way
  to measure the second thing, and does not claim to.
