# 0003 - Source quirks are handled explicitly and reported

Date: 2026-10-01. Status: accepted.

## Context

stats.nba.com is the league's own data, and it is very good, but thirty seasons of it
contain a handful of oddities: a cancelled game listed as if scheduled, one team-season
with fractional totals, neutral-site games with no home team, season totals that differ
slightly from summed game logs. Each forces a choice, and a choice made silently inside
a normaliser is exactly how a number stops being trustworthy.

## Decision

1. **Published season figures are canonical.** `team_seasons` and `player_seasons` store
   the totals and ratings the league publishes, so the lab's numbers match the league's.
   Game logs are a second, independent measurement and are used to cross-check.
2. **Strict by default.** A normaliser rejects anything it does not recognise. Each
   tolerated quirk is a named, narrow rule with a test built on the real response that
   exhibits it.
3. **Adjustments are reported.** When a rule changes or drops data, the normaliser adds a
   note. Notes travel with the build as `BuildIssue(severity=note)` and are shown by
   `fol check`.
4. **Glitches that are not adjusted stay visible.** A source value that contradicts
   itself but is stored as published is surfaced by a quality check at `warning`
   severity, permanently.
5. **A failure costs as little as possible.** A dataset that cannot be normalised is
   recorded as an error for its table and season; the rest of the build continues.

The rules in force:

| Quirk | Rule |
| --- | --- |
| A scheduled game with no result and zero minutes | Left out of `team_games`; noted |
| A season total that is not a whole number | Rounded; noted. Rejected if more than 5% of the column is fractional |
| Both teams listed as visitors | `is_neutral_site` true, `is_home` false for both |
| Both teams listed as home | Rejected |
| A rostered player with no on-court line | Left out of `player_on_off` |
| Playoff series identifiers | Ignored; series and rounds are derived from the games |
| Postseason outcomes before the Finals are decided | Null |
| A column the source added | Ignored |
| Equal records left on the same place in the standings (through 2000-01) | Kept as published; a check warns, and benchmarks by seed say so |
| A player's season totals a basket or a game away from the game log (46 player-seasons of 20,668, mostly before 2006-07) | Kept as published; a check warns. More than a game, or than five points or 2%, is an error |
| A player listed with the opponent in a box score (one game of 1996-97), a line with four points too many (one of 1998-99) | Kept as published; a check warns. More than ten points from the team's score is an error |
| Player minutes that do not add up to the game (about 130 box scores, most of them from 2005-06 and 2006-07) | Kept as published; a check warns. Season minutes come from the published totals, never from the logs |
| A column the source removed or renamed | Rejected, naming the column |

## Consequences

- Anyone can see every place the lab's data departs from what the source sent.
- A new quirk fails loudly the first time it appears and gets a rule, a test and a line
  in this table.
- Small disagreements between season totals and game logs are expected and tolerated up
  to 2%; beyond that a check warns.
