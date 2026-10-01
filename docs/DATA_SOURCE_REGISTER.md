# Data Source Register

Every external source the lab uses or plans to use, what it is used for, and the terms
it is used under. Re-verify a source's terms and availability before depending on it for
something new.

| Source | Used for | Access | Status |
| --- | --- | --- | --- |
| NBA salary-cap announcements | Cap, tax line, aprons, minimum team salary, exceptions | Read by hand, transcribed into `configs/seasons/` | In use |
| NBA "CBA 101" | Roster limits | Read by hand, transcribed into `configs/seasons/` | In use |
| stats.nba.com (via `nba_api`) | Player, team, game, standings and advanced statistics | Public JSON endpoints, no key | Planned (milestone 2) |
| Player contract data | Salaries, guarantees, options | To be decided in milestone 3 after a permissions check | Not selected |

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
- The lab throttles its requests and stores every response in the raw store, so a
  season is fetched once rather than repeatedly.

## Player contracts

No free, official feed of NBA contracts exists. The roadmap names Basketball Reference
as an example of a public reference and requires that automated-use permissions be
checked before a scraper is built. That check is part of milestone 3; until it is done
no contract source is used.
