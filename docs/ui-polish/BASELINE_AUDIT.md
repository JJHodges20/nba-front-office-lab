# UI polish P0 - baseline audit

The first phase of the *Dark Forest UI Modernization* roadmap
(`NBA_Front_Office_Lab_UI_Polish_Roadmap.md`, the owner's planning document, not yet in the
repository): what the workbench is today, measured and photographed, before anything
changes. **Audit only: no application code,
configuration, data or git state was changed.** The one addition to the repository is
this folder; the screenshots and a disposable copy of the data are in the git-ignored
`data/ui-polish/`. The proposed tokens are in [DESIGN_SYSTEM.md](DESIGN_SYSTEM.md).

## 1. Audit context

| | |
| --- | --- |
| Date | 2026-10-11 |
| Branch / commit | `main` at `aec99fd` (the A9 release, committed by the owner); working tree clean. No branch was made: an audit leaves git alone. P1 should start on a branch, `ui-polish` (section 11). |
| Read | `CLAUDE.md`, `README.md`, `docs/ARCHITECTURE.md`, `docs/WORKBENCH.md`, `docs/decisions/0008-workbench.md`, the assistant's decision and specification, `.streamlit/config.toml`, `apps/workbench/` (frame, `wb/` modules, the 14 views), `tests/ui/`, and the roadmap's two documents. |
| Method | Two read-only inventories of the code (pages; styling and UI tests), the theme tests' arithmetic run on proposed colours, four throwaway Streamlit apps to learn how this version chooses a theme, and a browser pass over a disposable copy of the real data. |
| Environment | Windows 11, Python 3.14.6, Streamlit 1.64.0, Plotly 7.1.0, pandas 3.0.6, Playwright 1.63.0 (browser checks only). Windows set to light mode for apps. |
| Entry point | `fol ui` runs `python -m streamlit run apps/workbench/app.py --server.port <port>` from the project root (`cwd`, `FOL_HOME`). Streamlit finds `.streamlit/config.toml` through the working directory, so the theme applies only when started this way. |

## 2. How this checkout differs from the roadmap's snapshot

The roadmap was written against an earlier export. In this checkout:

- **Fourteen pages in six groups**, not thirteen in five: *Ask* holds **AI Research**
  (`/research`, `wb/views/research.py`), between Forecast and System.
- **The contextual assistant exists**: *Ask AI about this* (`wb/ask.py`), a modal
  `st.dialog` (width "large") on nine pages - Winning Benchmarks, Player Explorer,
  Player Value, Team Explorer, Team Builder, Roster Fit, Postseason Outlook, Scenario
  Simulator, and the research page itself has the full form. It asks in the workspace open
  on AI Research and shares its one running question (`state.AI_JOB`).
- **Answers are drawn by one module**, `wb/answers.py`, wherever they appear: outcome tag,
  text, notes, rosters and experiments to review, result tabs with charts and rows,
  evidence, "how it was answered".
- **Persistent research**: `data/assistant/assistant.sqlite` holds workspaces, every
  question and answer, findings, proposals and each press; proposals are saved only by
  the user's click; a damaged file is set aside on request (A9).
- **Tests added since**: `test_research_page.py` (27), `test_ask_dialog.py` (5), and page
  tests for Player Value, Roster Fit, Roster Optimizer, Postseason Outlook and Scenario
  Simulator. `tests/ui` now has 18 files.
- **No custom CSS anywhere**, and no hard-coded colour outside `wb/theme.py`: all styling
  is `config.toml`, the Plotly layout in `wb/charts.py`, and Streamlit badges. That makes a
  native-theme approach realistic.

## 3. Baseline evidence

| Check | Command | Result |
| --- | --- | --- |
| Whole suite (all but live-network and live-model tests) | `.\.venv\Scripts\python.exe -m pytest -n auto` | PASS: 3,950 passed in 5 min 31 s, after the browser pass, on `aec99fd` |
| Lint and format | `ruff check .`, `ruff format --check .` | PASS: all checks passed; every file formatted |
| The assistant against the local model | `pytest -m ollama` | PASS at A9 (6 passed, three runs), on the same code; not re-run for P0 |
| Theme arithmetic | `tests/ui/test_theme.py`, and the same checks run by a script on the proposed colours | PASS today; proposed dark palette passes all nine checks ([DESIGN_SYSTEM.md](DESIGN_SYSTEM.md) section 3) |
| Browser pass, both themes | Playwright over a disposable copy of the real data (section 10) | Taken; findings below. No page raised an exception or an error box. |
| Keyboard-only, zoom 125% and 150% | - | NOT RUN at P0; part of P8 |

## 4. Page inventory

Every page draws a header (`components.header`: title, subtitle, provenance tags), and most
carry headline tiles (`components.figures`), tabs, and charts through `components.chart`
(which adds "Table view and export": the rows, a CSV and an interactive HTML). Tests: every
page is drawn for every kind of filter and without contract data (`test_pages.py`), and
every control is swept (`test_sweep.py`, whose `STARTS` must list every page).

| Group | Page | Path | Main content | Charts | Clickable tables | Ask AI | Own tests |
| --- | --- | --- | --- | --- | --- | --- | --- |
| League | League Overview | `/` | 5 tiles with sparklines; Standings / Team efficiency / League trends / Postseason | 6 | standings -> team | - | TestLeague, test_clicks |
| League | Winning Benchmarks | `/benchmarks` | own era and stage filters; 5 tiles; 5 tabs | 4 | - | yes | TestBenchmarks |
| Explore | Player Explorer | `/players` | Players / Profile (4 sub-tabs) / Compare | 3 | listing -> player | yes | TestPlayers, test_clicks |
| Explore | Player Value | `/value` | Season / Projections / Roles / Value for money / The model | 9 | season, roles -> player | yes | test_value_page (46) |
| Explore | Team Explorer | `/teams` | listing, or a team's Profile / Games / Rotation / History / Payroll | 4 | listing -> team, rotation -> player | yes | TestTeams, test_ask_dialog |
| Explore | Contract Explorer | `/contracts` | payroll season; 4 tiles; Team payrolls / Contracts / Cap rules / Check a new file | 1 | contracts -> player | - | TestContracts |
| Explore | Analytics Lab | `/lab` | Study control; Relationships / Distributions / Metric glossary | 2 | - | - | TestLab |
| Build | Team Builder | `/builder` | roster row with New roster / Manage; up to 6 tiles; cap meter; editor | 1 | - (data editor) | yes, with the roster | TestBuilder, TestRosterEdits |
| Build | Roster Fit | `/fit` | Team or Built roster; Coverage / Profile / Sum of parts / The evidence | 1 | members -> player | yes | test_fit_page (12) |
| Build | Roster Optimizer | `/optimizer` | the request form in a bordered box; results in tabs Roster 1..N | 0 | - | - | test_optimizer_page (8) |
| Forecast | Postseason Outlook | `/postseason` | Team / Built roster / Set it yourself; 5 tabs | 8 | - | yes | test_postseason_page (13) |
| Forecast | Scenario Simulator | `/simulator` | subject, "Changes" box; 5 tabs | 3 | - | yes | test_simulator_page (11) |
| Ask | AI Research | `/research` | status; workspace bar; shelves; conversation; question box | per answer | - | (the page) | test_research_page (27) |
| System | Data Health | `/health` | 5 tiles; Sources; What is missing; 6 tabs | 0 | - | - | TestHealth |

Without contract data the Contract Explorer and the Roster Optimizer change their whole
layout, and four other pages show an empty state in one tab; each is tested.

**The sidebar** holds the navigation (14 pages, 6 groups, `st.navigation(position="sidebar")`),
then *Filters* - season, phase, team, player, comparison window, dates - with their keys
(`filter_season` ... `filter_dates_<season>`), then *Data*: a state badge per source and
the build. **AI Research** stacks, top to bottom: header and 6 provenance tags; 6 status
badges; the workspace bar (select and four popovers); a caption; three shelves (Findings,
Proposed rosters, Experiment proposals); the mode and two buttons; earlier conversations;
the turns; a progress fragment polling each second with *Stop*; the question box.

## 5. The design as built

- **Tokens** (`wb/theme.py`): one `Palette` per theme - `plane`, `surface`, three inks,
  `grid`, `axis`, eight fixed categorical `series`, `deemphasis`, diverging poles, four
  states. `accent` is `series[0]` (blue). `.streamlit/config.toml` repeats them in
  `[theme.light]` and `[theme.dark]`; `primaryColor`, `linkColor` and `blueColor` are all the
  accent. Shared: system font stack, 15px base, headings 2rem to 0.9rem at 650/600, 8px
  radius, widget and sidebar borders.
- **Components** (`wb/components.py`): `header`, `provenance`, `tagged`, `state_badge`,
  `figures` (bordered `st.metric` tiles), `chart` (Plotly with `theme=None`, the table view
  and exports), `export`, `empty` (a bordered box with an icon and a reason), `metric_columns`,
  `table_height` (34px rows).
- **Charts** (`wb/charts.py`): 13 builders, all taking the palette; house rules in
  constants (2px lines, 18px bars in 30px rows, 10px ringed markers, solid hairline grids,
  legends only for several series, at most 3 scatter and 4 line series). Plotly's chart
  surface is the palette's `surface`.
- **Tags**: provenance (Measured blue, Derived gray, Estimate orange, Modeled green, Your
  assumption violet, Reported yellow), source states, answer outcomes, notes - every one a
  word and an icon as well as a colour.
- **Theme choice**: only `components.colors()` reads the theme, from
  `st.context.theme.type`, to colour charts. app.py never reads it.

## 6. Findings

Each finding cites the screenshot or the code that shows it. "Phase" is where the roadmap
would address it; nothing is changed by this audit.

| # | Finding and evidence | Who it affects | Proposed correction | Phase |
| --- | --- | --- | --- | --- |
| F1 | **The app opens in the computer's theme, and this computer is in light mode.** With both `[theme.light]` and `[theme.dark]` defined, Streamlit follows the system and offers System / Light / Dark in its menu; `base = "dark"` changes nothing. A choice of Dark is remembered in that browser (`localStorage`, `stActiveTheme-/-v2`) across reloads and tabs. A dark-only `[theme]` keeps the page dark always but removes the menu choice - and then `st.context.theme.type` still reports the system's "light", so charts would be drawn with the light palette on a dark page (section 8). | The owner: today the redesign target is not what opens | Decision D1 | P1 |
| F2 | **Charts can disagree with the page after a theme change.** Charts take their colours from `st.context.theme.type`, which Streamlit documents may be wrong at first load or after a switch (issue #11920). In the experiment, after choosing Dark the app still reported "light" until a reload. With `theme=None`, a chart keeps the old palette until the next rerun. | Anyone switching themes | Verify in the workbench; if confirmed, rerun on a theme change or read the type once per run | P1 check, P4 fix |
| F3 | **White on the primary colour is below 4.5:1 today**: 3.64 in dark (`#3987e5`), 4.42 in light (`#2a78d6`) - primary buttons such as *Ask*, *Create workspace*, *Run*. | All users | The green `brand` role (DESIGN_SYSTEM section 2): 4.56 dark, 6.47 light | P1 |
| F4 | **Global filters sit below the fold.** The 14-page navigation fills the sidebar: at 1440x900 only *Season* is visible (`dark-1440x900-*.png`); at 1366x768 and 1024x768 none of the filters are (`dark-1366x768-league.png`). Changing team or player means scrolling the sidebar. | Every page, every session | Options for P2 without reordering anything: tighter navigation spacing, or `st.navigation(position="top")` - groups as top-bar menus, filters alone in the sidebar (decision D4) | P2 |
| F5 | **At phone width the sidebar opens over the page** (`initial_sidebar_state="expanded"`): every `dark-390x844-*.png` shows the navigation covering the content until it is closed (`*-sidebar-closed.png`). | Phone and narrow windows | `initial_sidebar_state="auto"` (expanded on desktop, closed on a phone) | P2 |
| F6 | **Headline tiles cut off their own numbers in narrow windows.** Five tiles a row at 1024x768 show "11...", "10...", "41...." for 114.8, 100.2, 41.5% (`dark-1024x768-league.png`). Streamlit columns do not wrap; the sidebar takes 300px. | Tablets, split screens, zoom | `figures` lays tiles in a wrapping horizontal container with a minimum width, so they flow to fewer a row | P3 |
| F7 | **Segmented controls clip their options in narrow columns**: Scenario Simulator at 1024x768 cuts "High..." and "Optimistic improvement" (`dark-1024x768-simulator.png`). | Narrow windows | Let these rows wrap or stack below a width; check every `segmented_control` in a two-column row | P3 |
| F8 | **Every page starts about 95px down** (Streamlit's default top padding; `dark-1440x900-*.png`), which with a three-line subtitle and two rows of tags pushes content below the fold - most on AI Research. | All pages, laptops most | No native setting: a small CSS helper (`.block-container` padding) only if the owner accepts one documented exception (decision D5) | P2 |
| F9 | **AI Research puts about 660px of controls before the first answer** at 1440x900 (`dark-1440x900-research.png`): subtitle, 6 provenance tags, 6 status badges, workspace bar, caption, three shelves, mode row. | The assistant's main surface | Compress without removing: shelves as one row of popovers or tabs, status as one compact row, a shorter subtitle | P7 **Done**: the three shelves one fold with a tab each, the mode and the conversation's buttons under the conversation by the question box, a two-line subtitle. The first question now starts 411px down a 1440x900 window (608 before), 451 at 1366x768 (648), 585 at 1024x768 (803, below the fold) and 754 on a phone (1,026) |
| F10 | **Cards are drawn two ways.** Tiles and empty states are bordered boxes on the page colour; charts are borderless panels filled with `surface` (`dark-1440x900-benchmarks.png`, `-builder.png`). | Visual consistency | One card treatment: charts on a bordered card, or tiles filled - chosen in P3, applied by `components.chart` and `figures` | P3/P4 |
| F11 | **Provenance tags reuse state colours.** Modeled is green (= good), Estimate orange (= serious), Reported yellow (= warning), against `theme.py`'s rule that state colours are reserved; with a green brand, "Modeled" will also read as an action. | Readers telling measured from modeled | Decision D3 | P3 |
| F12 | **One meaning, several looks**: "Note" is gray, orange or blue by page; "Out of date" is defined in four views; warnings use orange (`serious`) rather than yellow (`warning`). | Consistency | One definition each in `components.py` | P3 |
| F13 | **Header pattern broken in two places**: Analytics Lab draws its tags below its Study control and uses bare `st.metric` (`dark-1440x900-lab.png`); Data Health has no tags. | Consistency | Same header and tiles as every page | P5/P6. **P5: Analytics Lab done** - tags under the title, its three numbers a row of tiles above a full-width chart; **P6: Data Health kept without tags** - they say where basketball figures come from, and its figures are the lab's own build's |
| F14 | **Empty tabs under a "choose a team" box**: Roster Fit and Postseason Outlook with no team chosen draw their tabs with nothing in them (`dark-1440x900-fit.png`). | First-time use | Say once what to choose, and draw the tabs that work without it | P6 **Done**: on Roster Fit each tab that needs a subject says what is missing; Postseason Outlook already did (a check of every tab in three states found no other empty tab) |
| F15 | **Cap-line labels crowd**: Floor / Cap / Tax / 1st and 2nd apron sit close above the payroll charts (`dark-1440x900-contracts.png`, `-builder.png`). | Reading the cap lines | Stagger or abbreviate in `charts.meter` / `stacked_bars` | P4 |
| F16 | **The light theme's own weak spots** (untested today): three light series are below 3:1 on the light surface (`#1baf7a` 2.74, `#eda100` 2.11, `#e87ba4` 2.62); light tick labels are 3.5:1 at 12px. | Light-mode readers | Add the light series check and fix, if light stays (D1) | P1/P4 |
| F17 | **The assistant's context is the sidebar only.** The dialog asks about the sidebar's season, team and player; Team Builder alone passes its roster. A built roster chosen on Roster Fit, Postseason or the Simulator, the Simulator's own team, and Benchmarks' era and stage are not passed. Five pages have no *Ask* button (League Overview, Contract Explorer, Analytics Lab, Roster Optimizer, Data Health). | Contextual questions | Functional, not cosmetic: a separate proposal, not part of this polish unless approved (decision D6) | - |
| F18 | **The theme applies only when started from the project root** (`fol ui` does; `streamlit run` from elsewhere is unthemed). | Anyone bypassing `fol ui` | Documented in the release notes; no change proposed | - |
| F19 | `charts.stacked_bars` has no series cap (parts past the eighth slot would be dropped). | Future charts | A cap with an error, as the other builders have | P4 |
| F20 | **The top bar does not mark the open page's group** (found at P2, `p2/dark-checks-team-held.png`). Streamlit draws the six group menus alike whatever page is open; in an opened menu the open page is marked (tinted and bold, `aria-current`), and the title and the browser tab name it. A menu exists in the page only while open, so a style rule cannot mark its group. | Knowing where a page sits | The group's name above each page's title, from the shared header (decision D7) | P3 |
| F21 | **Two tiles carry more text than a tile holds** (found at P3): Scenario Simulator's *Payroll* ("was $192.7M, 5 unpriced") and Data Health's *Last build* (a full date and time) trim their note at 1366px and on a phone; the number itself shows | Laptop and phone readers | Shorter notes, with the page | P6 **Done**: the simulator says how many are unpriced under its tiles; its evidence row and Data Health's row three a row |
| F22 | **On a phone, five pages' tab rows are wider than the screen** (found at P4, once the check looked for this Streamlit's tab markup - an earlier check matched nothing): Winning Benchmarks, Postseason Outlook, Scenario Simulator, Data Health, and the evidence tabs under an answer. The row scrolls sideways, as Streamlit draws it: every tab can be reached, the last ones by swiping | Phone readers | Shorter tab names, page by page, where they do not lose meaning | P5-P7. Under an answer the tabs are kept as they are (P7): each names a result by its id and title, cut at 38 characters with the full title under it, and shorter they would no longer say which result is which |
| F23 | **Chart text a phone cannot fit** (found at P4, every chart measured at three widths): Winning Benchmarks' *How far teams went* sets fourteen two-line column labels ("40 to 45", "n = 145") that run together below about 1100px - tilted, they garbled - and two axis titles of more than fifty characters (Benchmarks' *What separates them*, Player Value's model chart) still run past a phone's chart on two lines. The table view under each chart holds every figure | Narrow windows | Shorter labels and titles, with the pages | P5. **Done**: the labels take turns on two levels (words and counts kept); the two titles shortened to 33 and 41 characters |
| F24 | **Controls and tiles that only a chosen team or player brings** (found at P5, every page and tab scanned with a team and a player chosen; the earlier scans had none chosen): at 1024px the form charts' *Trailing games* on Team Explorer and Player Explorer cut off 20; Player Value's player row cut "Wins above replacement" at every width, 1440 included; Analytics Lab's three tiles were cut in their fifth of the page at 1024px | Anyone with a team or player chosen | Fixed in P5 (development log) | P5 |
| F25 | **The chance curve's uncertainty band was never drawn** (found at P6, the chart's own SVG read in a browser): Postseason Outlook says "the band is the 95% interval", and its band - 33% to 64% at +12 net rating - had an empty fill, its edges being traces with no line; a 10% wash would have been all but invisible on the dark chart anyway | Anyone reading a chance | Edges as lines of no width; the wash a palette role, 0.25 in the dark theme (DESIGN_SYSTEM.md section 6) | P6, done |
| F26 | **Code was printed in the green of a good state** (found at P7, an answer's evidence read in a browser): left unset, Streamlit gives code its green text colour, so every file path under an answer - and a command in a Postseason Outlook tooltip - read like a link beside the real links, or like a success | Anyone reading what an answer rests on | `codeTextColor` set to the secondary ink in both themes, with a test (DESIGN_SYSTEM.md section 2) | P7, done |
| F27 | **A question under way showed a tick** (found at P7, live with the local model): a fragment draws the box with the steps again each second inside a `with` block, and leaving one marks Streamlit's status box complete - so "Quick answer under way" carried a done mark the whole time, on the page and in the dialog | Anyone waiting for an answer | The box written into without a `with` block shows a spinner; a test holds it running | P7, done |
| F28 | **A comparison's rows showed each figure twice** (found at P7, live): "fg_pct, 0.467 ... Field goal percentage ... 46.7%", and percentiles to three decimals ("99.399") | Anyone reading a comparison | A raw value and a metric's key left to the CSV where the lab's written form and the metric's name stand beside them; a percentile written as every page writes one ("99th percentile") | P7, done |
| F29 | **The answer checker keeps a place that the result holds for another measure** (found at P7, live on the throwaway copy): asked from Team Explorer which team had the best defense, the model read only the Celtics' figures and wrote that their defensive rating "ranked 1st in the league"; the result said 4th of 30, and held a "1st of 30" for points allowed. The checker took out another figure and marked the answer *Partly answered*, and the place stood | Anyone trusting a place in an answer | Not a matter for the polish: a later assistant milestone, through its evaluation (`docs/AI_EVALUATION.md`) - the owner's call | - |
| F30 | **A delete's popover closed as its box was ticked** (found at P7, in a browser): on AI Research, a finding's or an experiment's *Delete* popover closed on the tick whenever the line saying what the last action did had just gone - everything below moves up a place, and an unkeyed popover is then a new one. The box stayed ticked, so the delete took a second opening. A fold whose label holds counts closes the same way when a count changes | Anyone deleting a finding or an experiment | Every popover below that line keyed; the shelves' fold and tabs keyed, their tabs named without counts | P7, done |

What already works well, and should be kept: one header pattern, consistent tiles and
tabs, every empty state saying why and what to do, tags with words and icons, tables with
dashes for missing values, charts with their table view and exports, no exceptions or
error boxes anywhere in the pass (100 screenshots, both themes), the dialog sharing the
page's question and workspace - and fitting a phone screen well
(`light-390x844-ask-dialog.png`) - and a light theme that is already calm and legible
(`light-1440x900-*.png`), worth keeping as the compatibility theme. On a phone the tiles
stack one a row, about 215px each (`dark-390x844-league-sidebar-closed.png`); the wrapping
layout of F6 would fit two.

## 7. Behaviour that must not change, and what holds it

| Invariant | Held by |
| --- | --- |
| Numbers on every page equal the services' | `test_pages.py`, page test files, `tests/unit` |
| Global filters and their keys; clicks act once | `test_app.py`, `test_clicks.py`, `state.py` (no keys renamed) |
| Every control on every page still works | `test_sweep.py` |
| Chart house rules, table views and exports | `test_charts.py`, `test_components.py` |
| Palette arithmetic and page/chart parity | `test_theme.py` |
| Layer boundaries, offline suite | `tests/architecture` |
| One running question shared by page and dialog; answers kept and redrawn as they were | `test_research_page.py`, `test_ask_dialog.py`, `test_api.py`, `test_workspaces.py` |
| Rosters and experiments saved only by the click; a decline saves nothing | `test_research_page.py`, `test_proposals.py`, `test_workspaces.py` |
| A damaged research file is set aside, never deleted | `test_research_store.py`, `test_workspaces.py`, the page and dialog tests |
| Localhost only, no usage statistics | `test_theme.py::test_the_workbench_listens_on_this_machine_only` |

Manual smoke checks to repeat after each phase, in a browser, in both themes: change
season, team and player and move between pages; click a row in Team Explorer and Player
Explorer; build and edit a roster on a disposable copy; run the optimizer and save one
roster; run the simulator; ask a Quick question on AI Research and from the dialog, see
the evidence, stop one under way; open an old answer; export a chart and a table.

## 8. The theme experiments

Four throwaway apps (outside the repository) with the same colours, opened in a browser
set to light and then dark:

| Configuration | Light browser | Dark browser | Menu | `st.context.theme.type` |
| --- | --- | --- | --- | --- |
| `[theme.light]` + `[theme.dark]` (today's setup) | light | dark | System / Light / Dark | right |
| the same plus `base = "dark"` | light | dark | System / Light / Dark | right |
| `[theme]` only, `base = "dark"` with colours | dark | dark | no theme choice | **wrong**: "light" in a light browser |
| `[theme.dark]` only, `base = "dark"` | Streamlit's plain light | dark | System / Light / Dark | right |

Choosing *Dark* in the menu of the first: dark at once, after a reload, and in a new tab
of the same browser; the app reported "light" until the reload. Checked again for the
owner's question on 2026-10-11, with a browser profile kept on disk: Dark chosen, the
browser closed, the app restarted with its dark colours changed - and it opened dark, in
the new colours. The same browser on another port opened light: the choice is kept per
browser and per address.

## 9. Risks for the later phases

- **Streamlit-generated markup.** Any CSS must avoid hashed class names; `data-testid`
  hooks can change between Streamlit versions. Keep CSS to one helper, or none.
- **One `primaryColor`.** Selected tabs, toggles, sliders and focus borders all take it;
  a colour dark enough to be "forest" fails for these (DESIGN_SYSTEM section 2).
- **Charts are colour-checked by arithmetic.** Any series change reruns the separation
  tests; the proposal keeps the series untouched.
- **AppTest cannot see visuals.** Every phase needs the browser pass, and the pass cannot
  share the machine with a test run (CLAUDE.md).
- **The research page polls each second while a question runs.** Layout changes there
  must keep the fragment, the job and the turn-taking exactly as they are.

## 10. Screenshots

In `data/ui-polish/screenshots/p0/` (git-ignored), named `<theme>-<width>x<height>-<page>.png`:
every page at 1440x900 in dark and light; League Overview, Player Explorer, Team Builder,
Roster Optimizer, Scenario Simulator, Data Health and AI Research (its top and its latest
answer) at 1366x768, 1024x768 and 390x844 in both themes, at 390 also with the sidebar
closed; and the *Ask AI about this* dialog (from Team Explorer) at every size. Taken from a
workbench serving a disposable copy of the real data (`data/ui-polish/workbench-data`, its
research workspace renamed "Knicks research", 13 answered questions), so later phases can
be photographed on the same data. No question was asked of the model.

Not captured, for later phases: zoom at 125% and 150%, keyboard focus, a selected team or
player, an optimizer or simulator run with results, a question under way, and the light
theme's dialog states beyond the empty form.

## 11. Decisions for the owner

| # | Decision | Recommendation |
| --- | --- | --- |
| D1 | How dark becomes the default | **Keep both themes; choose *Dark* once in the menu** (remembered in the browser). Dark-only removes the light theme, the menu choice, and breaks the chart palette's theme detection (F1). **Decided by the owner, 2026-10-11, as recommended.** |
| D2 | The primary colour | **`#2f8556` dark, `#1f6b45` light**, as a new `brand` role; charts keep their blue accent. The roadmap's `#244f38` is too dark for selected controls. **Decided by the owner, 2026-10-11, as recommended.** |
| D3 | Modeled's green tag next to a green brand | Decide in P3 between a non-state hue for Modeled and leaving it. **Decided by the owner at P3: keep it green.** No badge colour is free (all seven are a provenance or a state), and the swap tried - Modeled violet, *Your assumption* in the brand green - left *Your assumption* dim on the dark page (4.29:1, under 4.5) |
| D4 | Navigation position | Keep the sidebar and tighten it, or move the groups to a top bar so the filters are always in view - same groups, labels, order and paths either way. **Decided by the owner at P2, from prototype screenshots (`data/ui-polish/screenshots/p2-options/`): the top bar.** |
| D5 | One small CSS helper | Accept one documented helper for what Streamlit cannot set (page padding, tabular numerals), or none. **Decided by the owner at P2: one small rule, the space above titles.** |
| D6 | The assistant's context (F17) | Leave out of the polish; a separate proposal if wanted |
| D7 | The open page's group (F20) | A small label with the group's name ("Explore") above each title, drawn by the shared header in P3, or leave it to the title and the menu. **Decided by the owner at P3: leave it.** Built both ways at P3 - above the title and beside it - the label must clear the top bar, which pushes every page down about 60px |
| D8 | Headline tiles in a narrow window (F6) | A second style rule set so tiles wrap as a grid, or leave them cut. **Decided by the owner at P3, from before-and-after screenshots (`data/ui-polish/screenshots/p3-options/`): let them wrap.** |
| D9 | Deletes that do not ask (found at P3) | A finding and an experiment proposal deleted on one click, where rosters and workspaces ask for a tick first. **Decided by the owner at P3: every delete asks first.** |
| D10 | Charts as outlined cards, like the tiles (F10) | **Keep the filled panel**: an outlined chart needs a see-through background, and just after a theme switch its text would then be dark on dark until the next click (F2), where today the panel keeps its old colours but stays readable. **Accepted by the owner with P4 (2026-10-12).** |
| D11 | A chart's colours just after a theme switch (F2) | **Leave as is** (P4): Streamlit does not run the page again when the theme is switched, and only a script in the page could make it; the next click redraws the charts, and the choice is remembered, so it is seen once. The user's guide says so |
| D12 | A docked assistant panel beside a page on a desktop (the roadmap's P7, task 3) | **Keep the dialog** (P7): Streamlit 1.64 offers a dialog only as a centred modal - small, medium or large - which already takes a phone's whole width; a docked panel would need HTML and CSS of the lab's own, which no page may write, or the sidebar, which holds the filters. The full experience is AI Research, one click away from any answer (*Open in AI Research*) |

## 12. P1 plan: centralized tokens

**Scope:** colours only, in their two places, with tests. No view, component or chart
builder changes; no CSS.

| File | Change |
| --- | --- |
| `apps/workbench/wb/theme.py` | Add `brand` and `link` to `Palette`; set the dark values of DESIGN_SYSTEM section 2; light keeps its neutrals and gains `brand`/`link` |
| `.streamlit/config.toml` | `[theme.dark]` and `[theme.light]`: `primaryColor` = brand, `linkColor` = link, background, secondary background, text, borders and dataframe colours from the palette; sidebar colours unchanged in role |
| `tests/ui/test_theme.py` | Parity: `primaryColor == brand`, `linkColor == link` (was accent); new: white on brand >= 4.5, brand on plane and surface >= 3, link on plane >= 4.5, both themes; every existing threshold kept |
| `docs/ui-polish/DESIGN_SYSTEM.md` | From proposed to in effect, with the measured values |
| `docs/WORKBENCH.md` | One line on choosing Dark in the menu (D1) |
| `docs/roadmap/` | A copy of the polish roadmap, as the lab keeps its source plan there - if the owner wants it in the repository |

**Verification:** `tests/ui/test_theme.py`, `test_charts.py`, `test_components.py`, then
the whole suite and `ruff`; the browser pass of section 10 repeated on the same data in
both themes, compared shot for shot with P0; a check of F2 (switch theme, watch a chart).
**Not in P1:** layout, padding, navigation, tags, charts' series, the assistant's pages.
**Rollback:** the change is three files and a document on its own branch.

Then stop for review.
