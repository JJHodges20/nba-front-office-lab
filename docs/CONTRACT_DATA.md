# Contract Data

The lab does not download player contracts. No free source permits collecting them
automatically for this kind of project (see [the source register](DATA_SOURCE_REGISTER.md)),
so salaries come from a file **you** supply, from a source you are entitled to use.

Until a contract file is imported, statistics work as normal and anything involving
salary or payroll is shown as unavailable.

## Quick start

```powershell
.\.venv\Scripts\fol.exe contracts template
```

writes `data\imports\contract_template.csv`: one row for every player on a roster today,
with player id, name and team filled in and the salary columns empty. Fill in what you
have, then:

```powershell
.\.venv\Scripts\fol.exe contracts import data\imports\contract_template.csv --source "where the figures came from"
.\.venv\Scripts\fol.exe check
```

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
| `player_id` | one of `player` / `player_id` | The league's player id. When present it decides the match and the name is ignored. |
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
   same player listed twice for one team and season rejects the file, and nothing is
   stored. The message names the line and column.
2. **Matches each row to a known player and team.** A row that cannot be matched is left
   out and listed. Fix the spelling, or add a `player_id` column, and import again.
   When several players share a name, the active one is preferred, then the one on the
   team named in the row.
3. **Stores the file unchanged** in the raw store, next to the league data. Importing
   again replaces what the lab uses; earlier imports are kept.
4. **Builds two tables.** `contracts` has one row per player per team per run of
   consecutive seasons. `contract_years` has one row per season, with the salary's share
   of that season's cap. A gap between seasons starts a new contract.

Salary as a share of the cap needs that season's cap. Seasons without a rules file in
`configs/seasons` - future seasons the league has not set - get a blank share.

## Checks

`fol check` then verifies that contract totals match their seasons, that no player has
two active contracts in one season, and that cap shares are consistent. It warns about
salaries that look like typing slips (outside 0.02%-45% of the cap) and about teams with
fewer than ten standard contracts in the file's first season, which usually means the
file is incomplete.
