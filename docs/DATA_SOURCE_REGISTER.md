# Data Source Register

Every external source the lab uses or plans to use, what it is used for, and the terms
it is used under. Re-verify a source's terms and availability before depending on it for
something new.

| Source | Used for | Access | Status |
| --- | --- | --- | --- |
| NBA salary-cap announcements | Cap, tax line, aprons, minimum team salary, exceptions | Read by hand, transcribed into `configs/seasons/` | In use |
| NBA "CBA 101" | Roster limits | Read by hand, transcribed into `configs/seasons/` | In use |
| stats.nba.com (via `nba_api`) | Player, team, game, standings and advanced statistics | Public JSON endpoints, no key | In use |
| Contract file supplied by the user | Salaries, options, guarantees | CSV placed by hand, imported with `fol contracts import` | In use (no file imported yet) |
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
