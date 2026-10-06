# 0017 - The contract file is history, split by team

Date: 2026-10-05. Status: accepted. Follows [0004](0004-contract-data-from-user-files.md).

## Context

Decision 0004 settled that contract data enters through a file the user supplies. The
import path, the checks and every salary view were built against an invented file in the
shape of `fol contracts template`: the players on today's rosters, with the seasons ahead
as columns. In that shape a player has one contract in a season, a team has fourteen or
fifteen of them, and nothing is smaller than a two-way salary.

The file the user supplied is not that shape. MrBridge's *NBA Salary Cap & Contracts
2016-2026* dataset (HoopsHype's public salaries, snapshot of 2026-07-07) lists every
salary a team paid from 2015-16 to 2026-27, one row per player per team per season:
7,288 rows, 12 seasons, with the site's own player and team ids, boolean flags for
two-way contracts and options, and a `source` column. Built in as it came, three things
the lab assumed stopped holding:

- A player who changed teams within a season is listed under each team, with what each
  owed. The check "no player is under two active contracts in one season" failed 441
  times, every one a move between teams (440) or a two-way contract converted to a
  standard one with the same team (1).
- In the file's first season, four teams had 22 to 24 standard contracts, past the
  "doubled up" ceiling of 21. A season's full list of everyone a team paid - ten-day
  contracts and mid-season moves included - is longer than a roster; the dataset's own
  payroll table counts up to 36 players for one team-season.
- Two salaries, a minimum contract prorated to a day or two, sat below the 0.02% of the
  cap that the "typing slip" floor allowed.

And the file's spellings are the site's, not the league's: 38 names the league's player
index writes differently (Patty Mills, Nic Claxton, Juancho Hernangomez, Svi
Mykhailiuk, Enes Freedom), 15 names two retired players share (Mike James, Mike
Dunleavy, Gerald Henderson), 54 camp signings who never appeared in a game and are in
no league index, and one of those whose name, suffix stripped, the lab would have handed
to a namesake.

## Decision

1. **The file is read as history, split by team.** The lab's grain was already one row
   per player per team per run of seasons; the rules around it now match. The import's
   duplicate rule and the quality check are per team, season and kind of contract: no
   team owes a player two active contracts of one kind in one season. A move between
   teams, a two-way conversion and dead money beside an active contract are all allowed.
2. **A player's own salary for a season is the sum of what the teams paid.**
   `ContractService.salaries` adds a player's active shares up and carries the option,
   guarantee and seasons remaining of the contract that runs on (the one with the most
   seasons left). Team payrolls were already sums per team and did not change.
3. **The plausibility bands describe a season's full list.** A salary is suspect below
   0.003% or above 45% of the cap; a team's first-season count is suspect below ten or
   above forty. Fewer still means an incomplete file, more a doubled-up one.
4. **The dataset is converted outside the lab, by a committed script, and the record of
   every difference lives in that script.** `scripts/convert_salary_dataset.py` drops the
   site's ids (the lab matches by name and team, and a `player_id` column means the
   league's id), carries the flags, adds up the four cases of one player listed twice
   for the same team, season and kind (a player waived and signed again, or on successive
   ten-day contracts - the lab's row is what the team owed that season), spells names as
   the league's index does, gives the league's id where a name fits two players, and
   leaves out the one row the lab would otherwise misattribute, saying why. The script
   prints what it did; the import reports what it could not match; nothing is guessed.
   The lab's own importer was not taught the dataset's layout: it would have had to treat
   a `player_id` column as the site's id for one source and the league's for every other.
5. **What the lab uses from the dataset is the salary table.** The payroll table was a
   cross-check (all 360 team-seasons present, 311 equal to the dollar, the rest short by
   exactly the rows left out). The cap, tax and apron figures equal the lab's for the three
   configured seasons; the earlier seasons are not transcribed, because a rules file also
   needs the floor, the exceptions and the roster limits from a cited source, and the
   rules schema has two aprons where the seasons before the 2023 CBA had one. The
   minimum, rookie-scale and two-way salary tables have no field in the schema. The
   derived tables (benchmarks, shares, champions, projections) are the dataset author's
   analysis, and the lab derives its own. All of this is listed in
   [DATA_SOURCE_REGISTER.md](../DATA_SOURCE_REGISTER.md).
6. **Payroll is priced by default in the league year the file was current for**: the
   season, July to June, that holds the file's as-of date, which the lab's status now
   carries. The earlier rule, the earliest priced season in the file, described a file
   that looks ahead and put a history at its oldest configured season. A file that
   starts after its date is still priced in its earliest priced season; a history that
   stops before its date, in its latest. The Team Explorer's contract-by-contract table
   starts at the season on screen for the same reason.

## Consequences

- Every salary, payroll, cap and value-for-money view and the optimizer have data:
  4,189 contracts for 1,627 players over twelve seasons, 7,229 contract seasons. Cap
  shares exist for 2024-25 to 2026-27 and are blank before that, as the import says.
- The 54 names the league's player index does not hold are $10.6M of $49.97B over twelve
  seasons; a team's payroll is short by that much where it paid one of them. The build
  notes list them.
- The two amounts on file for John Wall in 2022-23 are both under Houston in the
  dataset; the second equals that season's taxpayer mid-level exception, which another
  team paid him. The lab carries what the file states and this note records the doubt.
- Decision 0004 stands: the responsibility for the terms of the figures rests with
  whoever supplied them. The dataset's README states research and educational use; the
  lab did not check HoopsHype's own terms.
- Open: season rules for 2015-16 to 2023-24, which need the floor, the exceptions and
  the roster limits from a cited source and a schema that allows one apron before
  2023-24; payroll in the contender research now that history is in the database.
