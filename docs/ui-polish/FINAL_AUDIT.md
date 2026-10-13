# UI polish: final audit (P8)

**Status: 2026-10-12, branch `ui-polish`.** The Dark Forest polish of the workbench, phases
P0 to P8, measured against the baseline in [BASELINE_AUDIT.md](BASELINE_AUDIT.md). The design
as it now stands is [DESIGN_SYSTEM.md](DESIGN_SYSTEM.md); what to check before the branch is
merged is [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md).

| Phase | Commit | State |
| --- | --- | --- |
| P0 audit, P1 tokens | `759e8c3` | pushed |
| P2 the frame | `5a7fb0c` | pushed |
| P3 shared components | `8354d68` | pushed |
| P4 charts | `9fb68fe` | pushed |
| P5 League and Explore pages | `4b4d40e` | committed on this computer |
| P6 Build, Forecast and System pages | `fd3a1cb` | committed on this computer |
| P7 the assistant's surfaces | `37bde33` | committed on this computer |
| P8 accessibility and this audit | the commit that adds this file | committed on this computer |

Nothing has been pushed past P4, and nothing goes to `main` without the owner.

## 1. What changed, from P0

- **The look** (P1): a near-black canvas with a trace of forest green in every neutral, and a
  forest-green brand for actions, selection and links - never for data. White on the brand
  reads at 4.56:1 in the dark theme and 6.47:1 in the light (it was 3.64 on the old blue).
  Both themes are kept; the app follows the computer until Dark or Light is chosen in its
  menu (decision D1).
- **The frame** (P2): the six page groups are menus across a top bar, so the season, phase,
  team, player and comparison window stay in view in the sidebar; about 80px more of every
  page shows on a desktop; one form for errors, warnings, successes and notes.
- **Shared parts** (P3): headline tiles wrap instead of being cut off; every tag word has one
  icon and one colour; long choice rows became dropdowns where they were cut; every delete
  and clear asks for a tick first.
- **Charts** (P4): read on any screen, in either theme - cap lines on three rows, long axis
  titles on two lines, names kept on the chart, crowded dates slanted; the light theme's
  three faint series and its tick labels darker.
- **Pages** (P5, P6): each of the thirteen pages reviewed whole, every tab, with and without
  a team and a player chosen and in the oldest season. Among what was found and fixed: the
  chance curve's 95% band, never drawn since it was built; three empty tabs on Roster Fit;
  cut controls and tiles at 1024px; table views headed with column names such as
  `team_name`.
- **The assistant** (P7): the conversation starts about 200px higher; a running question
  shows a spinner, not a tick; an answer names the kinds of source it read; each proposed
  roster says waiting, saved or declined; a figure appears once in an answer's rows; code
  is no longer the green of a good state; folds and popovers stay open while the page
  changes around them.
- **Accessibility** (P8): measured in section 5; two findings for the owner (F31, F32).

## 2. What did not change

- **Navigation**: the same fourteen pages, in the same six groups and order, under the same
  names and addresses (`/players`, `/research`, ...). Only where the menu sits moved (D4).
- **Every figure, model and data source.** No calculation, metric, fitted model, model file,
  data table, salary, roster or stored research record was changed by the polish. The
  page tests compare what a page shows with what its service returns, as before.
- **What the user decides**: rosters and experiments are kept only by the user's click; a
  decline saves nothing; every proposal waits in its workspace. Checked live in P6 and P7 on
  throwaway copies of the data.
- **The tests**: none weakened, none removed. The suite grew from 3,950 at P0 to 3,983 at P7
  as each phase added its own (see the development log).
- **The rules of the code**: no page writes CSS or HTML; the style rules live in one file
  (`wb/style.css`, four rules, each the owner's choice) and a test holds it to that list.

## 3. Every finding

| # | Finding (short) | Outcome |
| --- | --- | --- |
| F1 | Opened in the computer's theme | Both themes kept; choose Dark once (D1, the owner's) |
| F2 | Charts lag a theme switch | Left as is, documented (D11) |
| F3 | White on the old primary under 4.5:1 | Fixed in P1: the brand green |
| F4 | Filters below the fold | Fixed in P2: the top bar (D4, the owner's) |
| F5 | The sidebar over the page on a phone | Fixed in P2: closed on a phone |
| F6 | Tiles cut in narrow windows | Fixed in P3: tiles wrap (D8, the owner's) |
| F7 | Choice rows clipped | Fixed in P3 and P5: dropdowns, stacked controls |
| F8 | Every page started about 95px down | Fixed in P2: one style rule (D5, the owner's) |
| F9 | 660px of controls before AI Research's first answer | Fixed in P7: the first question at 411px of 900 |
| F10 | Cards drawn two ways | Kept: filled chart panels (D10, accepted) |
| F11 | Provenance tags in state colours | Kept: Modeled green (D3, the owner's) |
| F12 | One meaning, several looks | Fixed in P3: one look per tag word, tested |
| F13 | The header pattern broken twice | Fixed in P5 (Analytics Lab); Data Health kept without tags (P6) |
| F14 | Empty tabs under one note | Fixed in P6 |
| F15 | Cap-line labels crowding | Fixed in P4 |
| F16 | The light theme's weak spots | Fixed in P1 and P4 |
| F17 | The assistant reads only the sidebar's context | Open: outside the polish (D6) |
| F18 | Unthemed when started from elsewhere | Documented: start with `fol ui` (release checklist) |
| F19 | Stacked bars without a series cap | Fixed in P4 |
| F20 | The open page's group unmarked | Left: the menu and title mark it (D7, the owner's) |
| F21 | Long tile notes | Fixed in P6 |
| F22 | Phone tab rows wider than the screen | Kept: they scroll; shorter names would lose meaning |
| F23 | Chart text a phone cannot fit | Fixed in P5 |
| F24 | Controls cut only with a team or player chosen | Fixed in P5 |
| F25 | The chance band never drawn | Fixed in P6 |
| F26 | Code in the green of a good state | Fixed in P7 |
| F27 | A running question showed a tick | Fixed in P7 |
| F28 | Figures shown twice in an answer's rows | Fixed in P7 |
| F29 | The answer checker keeps a place from another measure | Open: for a later assistant milestone (the owner's call) |
| F30 | Popovers and folds closed under the user | Fixed in P7 |
| F31 | The top bar's pages are last in the keyboard's order | Open: decision D13 |
| F32 | Faint focus marks on links and menu items | Open: decision D14 |

**F31** (P8, the keyboard pass): Enter opens a top-bar menu, but its pages come at the end of
the tab order - Streamlit draws an open menu after everything else on the page - so a
keyboard user tabs through the whole page to reach them: 16 to 25 presses on the pages
tried, more on a long page. Tab from a menu moves to the next menu, and the arrow keys do
nothing. Every page can still be reached, and its address typed. Before P2 the sidebar's
page list came first.

**F32** (P8): a focused button, dropdown, box, tab or download shows a clear green ring in
both themes; a focused sidebar link (*Data Health*) or menu item shows only a background
tint, in the light theme barely different from the page, and a top-bar menu a grey outline.

## 4. Decisions

D1 to D12 are in the baseline audit, with their outcomes. Two more, from P8:

| # | Decision | Recommendation |
| --- | --- | --- |
| D13 | A keyboard path to the pages (F31) | **Add a short list of the pages for the keyboard**: a fold, *All pages*, at the foot of the sidebar under the data status, closed by default - one Tab stop until opened, the fourteen pages in their groups after. The top bar stays as it is. Or leave it, and say in the user's guide that a page can be reached by its address |
| D14 | Focus marks on links and menu items (F32) | **One more style rule**: a 2px brand-green outline on a focused link or menu item (`:focus-visible`), as buttons already have; listed in DESIGN_SYSTEM.md section 9 and held by its test. Or leave Streamlit's tint |

Still open from before: **D6** (what the assistant knows of the page it is asked from, F17)
and **F29** (the answer checker), both outside a cosmetic polish.

## 5. Accessibility, measured

**Colour**, by arithmetic (`tests/ui/test_theme.py`, both themes, in every run of the suite):
text on the cards at 7:1 or more; secondary and muted text at 4.5:1 or more, muted text on the
page too (tick labels are 12px); white on the brand at 4.5:1 or more; every chart series at
3:1 on its chart; neighbouring series apart for every reader, protanopia and deuteranopia
included; the two poles of a diverging scale read as opposites; status colours never series
colours; an uncertainty band visible yet translucent; code in the secondary ink, never green.
No state or provenance is shown by colour alone: every tag is a word and an icon too.

**The keyboard** (Chromium, both themes, 1440px, on the photo copy - P8):

| Check | Result |
| --- | --- |
| Tab order | The sidebar (collapse, the filters, the data status and its link), the top bar's six menus, then the page |
| Focus marks | A green ring on buttons, dropdowns, boxes, tabs and downloads; a background tint only on a sidebar link or menu item, a grey outline on a top-bar menu (F32) |
| A page from the top bar | Enter opens the menu; its pages come after everything on the page: 16 and 25 presses of Tab on the pages tried (F31) |
| A team in the sidebar | Typed and chosen with Enter |
| Tabs | The arrow keys move between them |
| *Ask AI about this* | Enter opens it, the focus moves into it, Escape closes it |
| A download | Enter on *Data (CSV)*: the file arrives (3,091 bytes for Team Explorer's table) |

**Screen sizes and zoom**: a scan of every page and every tab for cut-off text and controls,
a team and a player chosen, at 1440, 1366, 1024 and 390px wide - and at 1152 and 960, the
layout a 1440px window takes at 125% and 150% zoom - found nothing cut. At 960 with the
sidebar open the top bar has room for five menus: *System* folds into "1 more", Streamlit's
own overflow, and opens from there. AI Research and the dialog at both zoom sizes: nothing
under the question box, nothing wider than the window (at 150% the first question starts
below the window; the page opens at its end, by the question box).

**States**: every page and tab with nothing chosen, with a team and a player chosen, and in
the oldest season (1996-97): no error, no empty tab. In a browser too: no data at all (the
first run - what is missing, the one command to run, how long it takes) and the assistant
unreachable (*Assistant: offline*, what to do, and that everything else works), in both
themes and on a phone; a question under way, many questions in one workspace, long tables,
saving and declining rosters, a restart (P7). Covered by the page tests rather than a
browser: no contract file, no saved roster, an answer that never came, a damaged research
file.

## 6. Screenshots

All in `data/ui-polish/screenshots/` (git-ignored, from disposable copies of the data):

| Folder | What it holds |
| --- | --- |
| `p0/` | The baseline: every page at 1440x900 in both themes, the key pages at three more sizes |
| `p1/` to `p4/`, `p2-options/`, `p3-options/` | Each phase's checks and the options the owner chose from |
| `p5-before/`, `p5-after/`, `p6-before/`, `p6-after/` | Every tab of every page, whole, before and after |
| `p7-before/`, `p7-after/` | AI Research and the dialog at four sizes, and each live step |
| `p8-keyboard/`, `p8-zoom/`, `p8-states/`, `p8-final/` | The keyboard's focus marks, the zoom widths, the edge states, and every page as it ends, beside P0 |

## 7. Limitations and what is left

- **Streamlit sets the limits.** No page writes CSS or HTML, so what Streamlit cannot be told
  stays as it draws it: the avatars' indent on a phone, a dialog that is only a centred
  modal (D12), tab rows that scroll sideways on a phone (F22), a menu's place in the tab
  order (F31), the sixth menu under "1 more" at 150% zoom, a chart's colours for a moment
  after a theme switch (D11). A Streamlit
  upgrade can change any `data-testid` the four style rules hook; each rule then falls back
  to Streamlit's own look, as DESIGN_SYSTEM.md section 9 says.
- **Checked by eye, not by a tool.** Contrast and colour-blind separation are tested; the
  rest of section 5 is a browser pass on this computer (Chromium), not a screen reader or
  an automated WCAG audit.
- **The README's screenshots** (`docs/images/`) show the look before the polish. New ones
  would publish fresh views of the data when pushed: the owner's call.
- **For later milestones, not the polish**: D6 (the assistant's context), F29 (the answer
  checker), D13 and D14 if taken.
