# 0004 - Contract data comes from a file the user supplies

Date: 2026-10-01. Status: accepted. Revisit if a licensed contract feed is adopted.

## Context

The roadmap names Basketball Reference as an example public source of contracts and
requires that automated-use permissions be checked before a scraper is built. That check
was done on 2026-10-01.

**Basketball Reference** (Sports Reference LLC, Terms of Use last updated May 19, 2023):

- §5(i) forbids automated access "in a manner that adversely impacts site performance or
  access". `robots.txt` does not disallow the contracts pages and asks for a three-second
  crawl delay, so a slow, single-page fetch would not breach this clause on its own.
- §5(j) forbids using site data "to create any database, archive, or other data store
  that competes with or constitutes a material substitute for the services or data
  stores offered on the Site".
- §5(k) forbids copying or using site data "for purposes of training, fine-tuning,
  prompting, or instructing artificial intelligence models or technologies in any
  manner", including "supporting machine learning methods used to predict, classify,
  label, or score inputs into the models".

§5(k) is decisive. This project's later stages feed salaries into value scores, an
optimiser and probability models, which is the use it prohibits.

**Other sources considered:**

- Spotrac refuses automated requests outright (HTTP 403).
- The BALLDONTLIE API offers player and team contract endpoints only on its paid
  top tier.
- stats.nba.com publishes no salary data.

No free source was found whose terms allow collecting contract data automatically for
this use.

## Decision

The lab does not scrape contract data from any site. Contract data enters through a file
the user supplies, in a documented CSV format (`docs/CONTRACT_DATA.md`), from a source
the user is entitled to use. The user states the source at import and it is stored with
the data.

The file is treated like any other provider response: read unchanged by an adapter
(`providers/contract_file.py`), kept in the raw store, and normalised by a pure function
(`processing/contracts.py`). A different source later - a licensed feed, for example -
is one more adapter producing the same two tables.

## Consequences

- The lab ships with no contract data. Until a file is imported, everything involving
  salary or payroll is unavailable and the build says so.
- Responsibility for the terms of the contract figures rests with whoever supplies them.
  Figures taken from a site with terms like §5(k) above may not be used in the lab's
  modeling stages.
- `fol contracts template` lists every rostered player so that filling in salaries is
  data entry rather than data wrangling.
- The roadmap's contract fields are covered where a salary table can supply them:
  salary, cap share, options, guarantee level, total guaranteed, years remaining, first
  and last season. A contract's signing date and its seasons before the first one listed
  are not, because salary tables do not carry them.
