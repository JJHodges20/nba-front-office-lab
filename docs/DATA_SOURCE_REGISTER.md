# Data Source Register

Every external source the lab uses or plans to use, what it is used for, and the terms
it is used under. Re-verify a source's terms and availability before depending on it for
something new.

| Source | Used for | Access | Status |
| --- | --- | --- | --- |
| NBA salary-cap announcements | Cap, tax line, aprons, minimum team salary, exceptions | Read by hand, transcribed into `configs/seasons/` | In use |
| NBA "CBA 101" | Roster limits | Read by hand, transcribed into `configs/seasons/` | In use |
| stats.nba.com (via `nba_api`) | Player, team, game, standings and advanced statistics | Public JSON endpoints, no key | In use |
| Contract file supplied by the user | Salaries, options, guarantees | CSV placed by hand, imported with `fol contracts import` and built in by `fol build` | In use: the MrBridge salary dataset, imported 2026-10-05 (see [The contract file in use](#the-contract-file-in-use)) |
| Basketball Reference | - | - | Not used: terms prohibit this project's use |
| Spotrac | - | - | Not used: refuses automated requests |
| BALLDONTLIE API | - | - | Not used: contracts are on its paid tier only |

## Salary-cap figures

Season cap figures are announced by the league on June 30 and take effect July 1. Each
file in `configs/seasons/` cites the pages its figures were taken from and the date they
were retrieved.

| Season | Source | Verified |
| --- | --- | --- |
| 2026-27 | Hoops Rumors, "Salary Cap, Tax Line Set For 2026/27 NBA Season" (reporting the NBA release) | 2026-10-01 |
| 2025-26 | NBA press release; Hoops Rumors for the bi-annual exception and maximum salaries | 2026-10-01 |
| 2024-25 | NBA press release; Hoops Rumors for the bi-annual exception and maximum salaries | 2026-10-01 |

The 2026-27 figures match the four reference values quoted in the roadmap. Automated
tests cross-check each season's internal consistency: the minimum team salary is 90% of
the cap, and maximum salaries are 25%, 30% and 35% of it.

## stats.nba.com

- Reached through [`nba_api`](https://github.com/swar/nba_api), a community-maintained
  Python client. There is no official public API and no service-level guarantee;
  endpoints can change without notice.
- Requests need browser-style headers, which `nba_api` supplies. Verified reachable from
  this machine on 2026-10-01.
- Team advanced statistics (possessions, offensive and defensive rating) are published
  from the 1996-97 season onwards, which sets the start of the lab's team history.
- The lab throttles its requests (one every 1.2 seconds by default) and stores every
  response in the raw store, so a finished season is fetched once rather than repeatedly.
- Play-in games exist from 2019-20.
- League-wide player statistics (season totals, on-court ratings, game logs) are ingested
  for every season from `seasons.player_history_start`: eight requests a season.
  Team-by-team detail (rosters with birth dates, on/off splits) costs sixty requests a
  season, so it is kept for the current league year and the three seasons before it;
  raise `seasons.player_detail_seasons` in `configs/base.yaml` for more.

| Dataset | Endpoint | One snapshot per |
| --- | --- | --- |
| `team_years` | CommonTeamYears | (all franchises) |
| `player_index` | PlayerIndex, historical | (every player in league history) |
| `standings` | LeagueStandingsV3 | season |
| `team_season_base`, `team_season_advanced`, `team_season_opponent` | LeagueDashTeamStats | season and season type |
| `team_game_logs` | LeagueGameLog, teams | season and season type |
| `player_season_base`, `player_season_advanced`, `player_season_starters` | LeagueDashPlayerStats | season and season type |
| `player_game_logs` | LeagueGameLog, players | season and season type |
| `team_roster` | CommonTeamRoster | season and team |
| `team_on_off` | TeamPlayerOnOffSummary | season, season type and team |

Known quirks of this source, and the rule applied to each, are recorded in
[decisions/0003-source-quirks.md](decisions/0003-source-quirks.md).

## Player contracts

No free, official feed of NBA contracts exists. The roadmap names Basketball Reference
as an example of a public reference and requires that automated-use permissions be
checked before a scraper is built. The check was done on 2026-10-01 and the answer is
no; the reasoning is in
[decisions/0004-contract-data-from-user-files.md](decisions/0004-contract-data-from-user-files.md).

| Source | Checked | Finding |
| --- | --- | --- |
| Basketball Reference | Terms of Use (updated 2023-05-19), `robots.txt`, data-use and bot-traffic pages | Terms forbid building a substitute data store (§5j) and forbid using site data to prompt or train AI models or to support machine-learning methods that predict, classify, label or score (§5k). The lab's value, optimiser and probability stages would do exactly that. |
| Spotrac | Site response | Automated requests are refused (HTTP 403). |
| BALLDONTLIE API | Published tiers | Player and team contract endpoints are available only on the paid top tier. |
| stats.nba.com | Endpoints | Publishes no salary data. |

Contract data therefore comes from a CSV the user supplies from a source they are
entitled to use. The format is described in [CONTRACT_DATA.md](CONTRACT_DATA.md). The
user states the source at import, and that statement is stored on every contract row
(`contracts.source_label`, `contracts.as_of_date`).

Whoever supplies the figures is responsible for the terms they came under. Figures taken
from a site whose terms resemble §5(k) above may not be used in the lab's modeling
stages.

## The contract file in use

On 2026-10-05 the user supplied MrBridge's dataset *NBA Salary Cap & Contracts
2016-2026* (mr-bridge.com; its README is kept with the files under
`data/imports/nba-salary-cap-contracts-2016-2026/`). Its salaries are HoopsHype's public
salaries data in a snapshot dated 2026-07-07; its README states the dataset is "provided
for research and educational use" and that "underlying rights to the source data belong
to their respective owners". The lab did not check HoopsHype's own terms: under
[decision 0004](decisions/0004-contract-data-from-user-files.md) that responsibility
rests with whoever supplies the file.

| File in the dataset | What the lab does with it |
| --- | --- |
| `player_salaries.csv` | Imported. `scripts/convert_salary_dataset.py` rewrites it into the lab's long layout (the site's player and team ids dropped, the two-way and option flags carried, the four cases of one player listed twice for the same team and season added up, 38 spellings written as the league's index writes them, 15 ambiguous names given the league's id, one camp signing the index does not hold left out); `fol contracts import` matched 7,229 of its 7,283 rows and left out 54 names the league's player index does not hold, camp signings who never appeared in a game, worth $10.6M of $49.97B over twelve seasons. The source label and the as-of date (2026-07-07) are stored on every contract row. |
| `team_payrolls.csv` | Not imported; the lab computes payrolls from its own contract tables. Used as a cross-check: all 360 team-seasons present, 311 equal to the dollar, the rest short by exactly the rows left out. |
| `cap_tax_aprons.csv`, `max_salaries.csv` | Not imported. For 2024-25 to 2026-27 every figure equals the lab's `configs/seasons/` files. The dataset's figures for 2015-16 to 2023-24 are not transcribed: a rules file also needs the payroll floor, the exceptions and the roster limits from a cited source, and there was one apron before the 2023 CBA, which the rules schema does not yet allow. Recorded as open. |
| `min_salaries.csv`, `rookie_scale.csv`, `two_way.csv` | Not imported: the rules schema has no field for a minimum salary, the rookie scale or the two-way salary. |
| `salary_benchmarks.csv`, `payroll_by_roster_rank.csv`, `payrolls.csv`, `champion_payrolls.csv`, `top_contracts.csv` | Not imported: the lab derives what it shows from its own tables, and `figures_to_reverify.csv` lists figures the dataset's author flags for a recheck. |
| `cap_projections.csv`, `french_players.csv` | Not imported: a mechanical cap path is not a league figure, and the lab has no nationality field. |
