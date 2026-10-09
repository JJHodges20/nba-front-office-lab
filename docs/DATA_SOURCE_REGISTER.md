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
| Ollama (local) and its model library | The AI research assistant's language model | A local program on the loopback address; models pulled once | In use from A1 (see [The AI research assistant](#the-ai-research-assistant)) |
| stats.nba.com player movement file | Transactions, for the assistant | Public JSON file, no key | Planned for A2 |
| NBA official injury report | Injury status, for the assistant | Public PDF files | Planned for A2 |
| Ollama web search | General web search, for the assistant | API on the user's free account | Planned for A2 |
| ESPN and Yahoo NBA feeds; Wikipedia's API; links the user pastes | Reporting and background, for the assistant | Public RSS, public API, single pages | Planned for A2 |
| cdn.nba.com live data; www.nba.com pages; SearXNG's default engines | - | - | Not used: see [The AI research assistant](#the-ai-research-assistant) |

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
  this machine on 2026-10-01, and again on 2026-10-09 with one request (`CommonTeamYears`,
  45 rows) while nba_api's issue #696 reported the endpoints blocked elsewhere since about
  2026-10-07.
- The NBA's terms of use (nba.com/termsofuse, updated 2026-07-13, read 2026-10-09) cover
  the league's statistics wherever they are hosted. Section 9 allows their use for
  "private, non-commercial purposes" with "a prominent attribution to NBA.com"; bars any
  product presenting a "live, near-live, or other real-time or archived play-by-play
  account"; and bars a service that "features a database... of comprehensive, regularly
  updated statistics" without the league's consent. The lab is private, local and
  non-commercial; whether that last clause reaches a personal database is unclear, and is
  recorded here as open. The assistant credits NBA.com on every answer that uses league
  statistics and fetches no play-by-play.
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

Sending salary rows to the assistant's language model is a new use of the file. HoopsHype's
terms page refused an automated read on 2026-10-09 (HTTP 402); the user read the terms
and allowed it the same day. The model runs on this machine, and nothing is sent anywhere
or used to train anything.

| File in the dataset | What the lab does with it |
| --- | --- |
| `player_salaries.csv` | Imported. `scripts/convert_salary_dataset.py` rewrites it into the lab's long layout (the site's player and team ids dropped, the two-way and option flags carried, the four cases of one player listed twice for the same team and season added up, 38 spellings written as the league's index writes them, 15 ambiguous names given the league's id, one camp signing the index does not hold left out); `fol contracts import` matched 7,229 of its 7,283 rows and left out 54 names the league's player index does not hold, camp signings who never appeared in a game, worth $10.6M of $49.97B over twelve seasons. The source label and the as-of date (2026-07-07) are stored on every contract row. |
| `team_payrolls.csv` | Not imported; the lab computes payrolls from its own contract tables. Used as a cross-check: all 360 team-seasons present, 311 equal to the dollar, the rest short by exactly the rows left out. |
| `cap_tax_aprons.csv`, `max_salaries.csv` | Not imported. For 2024-25 to 2026-27 every figure equals the lab's `configs/seasons/` files. The dataset's figures for 2015-16 to 2023-24 are not transcribed: a rules file also needs the payroll floor, the exceptions and the roster limits from a cited source, and there was one apron before the 2023 CBA, which the rules schema does not yet allow. Recorded as open. |
| `min_salaries.csv`, `rookie_scale.csv`, `two_way.csv` | Not imported: the rules schema has no field for a minimum salary, the rookie scale or the two-way salary. |
| `salary_benchmarks.csv`, `payroll_by_roster_rank.csv`, `payrolls.csv`, `champion_payrolls.csv`, `top_contracts.csv` | Not imported: the lab derives what it shows from its own tables, and `figures_to_reverify.csv` lists figures the dataset's author flags for a recheck. |
| `cap_projections.csv`, `french_players.csv` | Not imported: a mechanical cap path is not a league figure, and the lab has no nationality field. |

## The AI research assistant

Audited at milestone A0, 2026-10-09, for [decision 0018](decisions/0018-ai-research-assistant.md).
Every source is re-verified when the milestone that first uses it begins.

| Source | Use | Finding |
| --- | --- | --- |
| Ollama, on this machine | Runs the language model | Listens on 127.0.0.1:11434 only (checked). Cloud models answer through the same local interface once signed in and are billed beyond a free allowance; cloud is on by default (`OLLAMA_NO_CLOUD` unset here). The lab's adapter refuses any host but the loopback address and any model Ollama marks as remote. |
| Model weights from the Ollama library | `qwen3:4b`, `qwen3:8b`, `qwen3:4b-instruct`, `qwen2.5:7b` | Each reports the Apache License 2.0 through Ollama (read at A1, 2026-10-09). Pulled once; nothing is sent back. |
| stats.nba.com league game logs | Completed games of the season in progress | The existing source and provider, refetched more often for the current season. Terms as above: private, non-commercial, credited to NBA.com. |
| stats.nba.com player movement (`/js/data/playermovement/NBA_Player_Movement.json`) | Transactions | Public and undocumented; carries the league's player and team ids. Same terms. No robots.txt is published for the host. |
| Official injury report (official.nba.com, PDF files) | Injury status with the report's time | Personal download allowed; "no portion... may be duplicated, redistributed or manipulated". The page's robots rules allow it; the PDF host's could not be read. Published about every 15 minutes in season. Needs `pypdf`. |
| Ollama web search | General web search | Free account, no card; the free allowance is unpublished and measured at A2. Queries leave the machine. The key is read from the environment by the web provider alone. |
| ESPN and Yahoo NBA RSS feeds | Headlines and links | Allowed on their terms: shown unmodified, credited, linked to the full article. |
| Wikipedia's API | Background | Allowed with an identifying User-Agent, 200 requests a minute; text CC BY-SA. |
| Links the user pastes | Evidence | Fetched once each after the address, redirect, robots, size and type checks; no paywall or bot-check workarounds. |
| cdn.nba.com live data | - | Not used: its firewall refuses clients that do not imitate a browser, and the terms bar play-by-play products. |
| www.nba.com pages | - | Not used: robots.txt shuts out AI agents (ChatGPT-User, ClaudeBot, PerplexityBot and others). |
| SearXNG with its default engines; DuckDuckGo scraping libraries | - | Not used: in 2026 they imitate browsers, switch user agents and solve bot checks to reach engines that do not offer an API. |
| Google Custom Search, Bing Search APIs | - | Not available: closed to new customers (ends 2027-01-01) and retired (2025-08-11). |
| Brave Search API, Exa, Tavily | - | Not chosen: Brave requires a card; Exa's terms were not checked; Tavily may keep and train on queries. |
| Sports Reference sites | - | Refused: their terms bar using site data "for purposes of training, fine-tuning, prompting, or instructing artificial intelligence models" (§5, updated 2023-05-19). |
| Spotrac | - | Refused: automated requests are refused (HTTP 402 and 403). |
