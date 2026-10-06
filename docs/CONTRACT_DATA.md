# Contract Data

The lab does not download player contracts. No free source permits collecting them
automatically for this kind of project (see [the source register](DATA_SOURCE_REGISTER.md)),
so salaries come from a file **you** supply, from a source you are entitled to use.

Until a contract file is imported, statistics work as normal and anything involving
salary or payroll is shown as unavailable. The file in use is the MrBridge salary
dataset, converted by a script in the repository; see
[the last section](#converting-the-mrbridge-salary-dataset).

## Quick start

```powershell
.\.venv\Scripts\fol.exe contracts template
```

writes `data\imports\contract_template.csv`: one row for every player on a roster today,
with player id, name and team filled in and the salary columns empty (`--output` names
another file; `--seasons` sets how many seasons of salary columns it carries, six by
default). Fill in what you have, then:

```powershell
.\.venv\Scripts\fol.exe contracts import data\imports\contract_template.csv --source "where the figures came from"
.\.venv\Scripts\fol.exe build
```

The import validates the file and stores it; the build rebuilds the database with the
contracts in it, which is what every salary view reads. `fol check` validates the file
against the rest of the data without writing anything.

`--source` is required and is stored with the data, so every salary in the lab can say
where it came from. `--as-of 2026-10-01` records the date the figures were current; it
defaults to today.

You do not have to use the template. Any CSV in one of the two layouts below works.

## Layouts

The file is CSV, saved as UTF-8 (in Excel: *CSV UTF-8 (Comma delimited)*). Column names
are not case-sensitive.

### Wide: one row per player, one column per season

```csv
player,team,2026-27,2027-28,2028-29,guaranteed
Pat Example,BOS,"$30,000,000","$32,400,000 PO",,"$62,400,000"
Sam Sample,NYK,2500000 NG,,,
```

### Long: one row per player per season

```csv
player,team,season,salary,option,guarantee
Pat Example,BOS,2026-27,30000000,,full
Pat Example,BOS,2027-28,32400000,player,
```

## Columns

| Column | Required | Meaning |
| --- | --- | --- |
| `player` | one of `player` / `player_id` | Player name. Accents, punctuation and suffixes such as Jr. do not affect matching. |
| `player_id` | one of `player` / `player_id` | The league's player id (stats.nba.com's), never another site's. When present it decides the match and the name is ignored. |
| `team` | no | Abbreviation (`BOS`), full name or nickname. Blank means no team. |
| `type` | no | `standard` (default) or `two-way`. |
| `status` | no | `active` (default) or `dead` for salary still owed to a waived player. |
| `guaranteed` | no | Total guaranteed money, as a dollar amount. |
| `notes` | no | Ignored. |
| season columns, e.g. `2026-27` | wide layout | Salary for that season. Blank means no salary. |
| `season`, `salary` | long layout | Season label and salary. |
| `option`, `guarantee` | long layout, optional | See markers below. |

A column the lab does not recognise rejects the file, so a typing slip in a header is
caught rather than silently ignored. Seasons are written with both years: `2026-27`,
not `2026-2027` or `2026`.

## Amounts and markers

Amounts are whole dollars: `30000000`, `$30,000,000`, `30.5M` or `850K`.

In the wide layout a salary may be followed by markers, with or without parentheses:

| Marker | Meaning |
| --- | --- |
| `PO` | Player option |
| `TO` | Team option |
| `ETO` | Early termination option |
| `G` | Fully guaranteed |
| `PG` | Partially guaranteed |
| `NG` | Not guaranteed |

For example `$32,400,000 (PO)` or `2500000 TO NG`. In the long layout the `option`
column takes `player`, `team` or `early termination`, and `guarantee` takes `full`,
`partial` or `none`.

## What the import does

1. **Validates the whole file first.** An unknown column, an unreadable amount or the
   same player listed twice for one team, season and kind of contract rejects the file,
   and nothing is stored. The message names the line and column. A player who changed
   teams within a season may be listed under each team, with what each owed; a two-way
   contract converted to a standard one is two contracts with the same team.
2. **Matches each row to a known player and team.** A row that cannot be matched is left
   out and listed. Fix the spelling, or add a `player_id` column, and import again.
   When several players share a name, the active one is preferred, then the one on the
   team named in the row.
3. **Stores the file as it came** in the raw store, next to the league data (only a
   byte-order mark and the line endings are normalised). Importing again replaces what
   the lab uses; earlier imports are kept.
4. **The next `fol build` makes two tables.** `contracts` has one row per player per team per run of
   consecutive seasons. `contract_years` has one row per season, with the salary's share
   of that season's cap. A gap between seasons starts a new contract.

Salary as a share of the cap needs that season's cap. Seasons without a rules file in
`configs/seasons` - future seasons the league has not set - get a blank share.

## Checks

`fol check` verifies, without writing anything, that contract totals match their seasons,
that no team owes a player two active contracts of one kind in one season, and that cap
shares are consistent; `fol build` runs the same checks and then writes the tables. They
warn about salaries that look like typing slips (outside 0.003%-45% of the cap; a
minimum contract prorated to a day or two sits at the bottom of that band) and about
teams with fewer than ten or more than forty standard contracts in the file's first
season: fewer means the file is incomplete, more that it is doubled up. A season's full
list of everyone a team paid - ten-day contracts and mid-season moves included - runs
past thirty in a season of many injuries, which is why the band is so wide.

A player who changed teams within a season is paid by each, and the player's own salary
for the season (on the Player Explorer, the value-for-money view and in the optimizer's
pool) is the sum; the option, guarantee and seasons remaining shown are those of the
contract that runs on.

## Converting the MrBridge salary dataset

The contract file in use came from MrBridge's *NBA Salary Cap & Contracts 2016-2026*
dataset (HoopsHype's public salaries, snapshot of 2026-07-07; what the lab does with
each of its files is in [the source register](DATA_SOURCE_REGISTER.md#the-contract-file-in-use)).
Its salary table is one row per player per team per season, with the site's own ids and
flag columns, which is not a layout the import reads. `scripts/convert_salary_dataset.py`
rewrites it into the long layout above and prints what it did:

```powershell
.\.venv\Scripts\python.exe scripts\convert_salary_dataset.py data\imports\nba-salary-cap-contracts-2016-2026\player_salaries.csv data\imports\contracts_mrbridge_2026-07-07.csv
.\.venv\Scripts\fol.exe contracts import data\imports\contracts_mrbridge_2026-07-07.csv --source "MrBridge NBA Salary Cap & Contracts 2016-2026 dataset (mr-bridge.com; HoopsHype public salaries, snapshot of 2026-07-07), converted with scripts/convert_salary_dataset.py; research and educational use" --as-of 2026-07-07
.\.venv\Scripts\fol.exe build
```

On the way the script:

- leaves out the site's player and team ids (a `player_id` column means the league's
  id), and `season_year`, `notes` and `source`, which the file has no column for;
- writes the `two_way` flag as the contract type and a team or player option as the
  option; a row flagged as both stops the conversion;
- adds up the rows that list one player twice for the same team, season and kind of
  contract - a player waived and signed again, or on successive ten-day contracts -
  since the lab's row is what the team owed that season and the import would otherwise
  reject the file. Four rows in the 2026-07-07 snapshot; each is reported;
- names the Clippers as the league's team index does, spells 38 names as the league's
  player index spells them, gives the league's id to 15 names two players share, and
  leaves out one row - a camp signing the index does not hold, whose name, suffix
  stripped, the lab would hand to a namesake - saying why;
- lists the rows flagged `qualifying_offer` or `terminated`, which have no counterpart
  in the lab's file and are written like any other.

The spellings and ids live in the script and were made from the import's own
unmatched-row report; a later snapshot may need more. The 54 rows the import still
cannot match are camp signings who never appeared in a game and are in no league index;
the import lists them and leaves them out ($10.6M of $49.97B over twelve seasons). The
seasons before 2024-25 have no rules file in `configs/seasons`, so their cap shares are
blank. The record of what the file changed in the lab, and of the one figure in doubt,
is [decision 0017](decisions/0017-contract-history.md).
