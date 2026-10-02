# 0008 - The workbench: a thin interface that displays and never computes

Date: 2026-10-01. Status: accepted.

## Context

Version 1 of the roadmap asks for a clean front-office workspace in Streamlit with seven
pages, persistent global filters, headline figures at the top of each page, a visible
separation of measured statistics, modeled estimates and user assumptions, interactive
charts with static export, data freshness on screen, and advanced settings out of the
way. Its engineering rules add that analytics own every calculation and the interface
must not recalculate a metric.

## Decision

**The interface lives outside the package and may import two layers.** `apps/workbench`
imports `front_office.services` and `front_office.domain` and nothing else from the
lab; `streamlit` and `plotly` are imported nowhere but there. Both rules are tests.

**It computes nothing.** A page sorts, filters, formats and draws. Anything that needs
arithmetic on data comes from a service: ranks and percentiles, league averages and
their change from the season before, payroll totals and room under each line, roster
indicators, correlations. Where a page needed a number the services did not yet give,
the service gained it (team percentiles, season-over-season changes, a season's salary
totals) rather than the page working it out. Axis padding and label placement are
layout, and stay in the interface.

**One frame, seven pages.** `app.py` draws the navigation, the global filters and the
data status; a page draws itself for whatever the filters say. The filters - season,
phase, team, player, comparison window - sit in the sidebar and live in the session, so
a choice holds from page to page. A click on a table row sets the same filters.

**A click acts once.** A table keeps a row selected for as long as it keeps its key,
and a row left selected would go on overruling whatever is chosen in the sidebar
afterwards. A clickable table therefore takes its key from `state.table_key`, which
changes with every choice: the click sets the filter, and the table returns with
nothing selected. On the Player Explorer a newly chosen player opens the profile tab,
wherever the choice was made; after that the tabs are the reader's.

**A widget is never written to after it is drawn.** Streamlit refuses it. A value
that has to change a widget - the subject after a click, the roster just created - is
parked in the session and applied at the top of the next run.

**Results are cached per build.** Every cached call takes the build id first, so a
rebuild in another process is picked up on the next run and nothing stale survives it.
Rosters are the user's and are never cached.

**Charts come from one module that knows nothing about Streamlit or basketball.**
`wb/charts.py` turns a frame and a palette into a figure. The house rules are the
module's, not each page's:

- one scale per chart, never two;
- thin marks: 2px lines, bars no thicker than 24px with a rounded data end, markers of
  at least 8px ringed in the surface colour;
- solid hairline gridlines; nothing dashed;
- text in ink, never in a series colour;
- no legend for one series, always one for several;
- colour by the job it does: one hue for a single series, the accent against gray when
  one thing is the subject, two poles for either side of a baseline, fixed categorical
  slots for distinct series - at most three in a scatter and four in a line chart,
  enforced with an error rather than a fourth colour.

**The palette is checked by arithmetic.** `wb/theme.py` holds one palette stepped for a
light and for a dark surface. Tests measure it: neighbouring series differ by at least
15 for full colour vision and 8 under simulated protanopia and deuteranopia (OKLab
distance x 100, Machado 2009 simulation), every scatter pairing likewise, and marks and
text meet their contrast floors. The page theme in `.streamlit/config.toml` states the
same colours, and a test fails if the two drift apart.

**Nothing is reachable only by hovering.** Every chart has a table view of the same
values with a CSV export, an HTML export that keeps it interactive, and a toolbar
button that saves a static image at twice screen size. No extra dependency is needed
for any of them.

**Where a number comes from is on the page.** Each page carries tags - measured,
derived, estimate, your assumption - with what each means. A metric's column heading
explains it and says whether the league measured it or the lab derived it. Ratings over
a span of games are marked with a tag, an "≈" on every figure and heading, and a
sentence saying what the estimate rests on. A salary the user typed is labelled as
theirs on its own row. No modeled value exists in this version, and the glossary says
so.

**Missing is said, not hidden.** A page with nothing to show says why and what to do:
no player detail for old seasons, no contract file, no games in a span. A missing value
in a table is a dash, never a zero.

**Like is drawn beside like.** A form chart over trailing games starts at the first span
that holds the full number of games. The shorter spans before it average fewer games -
the first is a single game - and drawn on the same line they read as form and set the
scale. The analytics return them when asked; the charts ask for full spans only, and say
so when a player or team has not played enough games for one. A percentile is written
from 1st to 99th.

**No judgement is offered.** The Team Builder prices a roster and describes its players;
it does not rank, recommend or project. The history chart picks champions out of every
team-season and states, on the page, that it describes and does not predict.

**The workbench is local.** It listens on `localhost` only, sends no usage statistics,
and is started with `fol ui`.

## Consequences

- A formula changed in analytics changes every page that shows it, and no page can
  disagree with another.
- Adding a page means a service method, a view module, and an entry in `app.py`.
- The pages are tested without a browser (Streamlit's `AppTest`) against a database
  built from the fixtures, and the figures they show are compared with what the
  services return. What a page looks like still needs eyes: the milestone gate records
  a screenshot review in both themes.
- A sweep (`tests/ui/test_sweep.py`) puts every control on every page through every
  value it offers and presses every button, and fails on any exception. It finds
  crashes; it cannot tell whether a page did the right thing.
- `AppTest` can neither click a table row nor edit a table cell. A row click is imitated
  in the tests, and the function that saves table edits is tested directly; the real
  journeys - choosing by row, then changing the sidebar; creating, filling, editing and
  deleting a roster - are clicked through in a browser at the gate. That is how both
  defects of this kind were found, and neither a page test nor the sweep would have
  shown the first.
- Static image export goes through the chart toolbar. A server-side export would need
  a headless browser as a dependency, and was left out.
