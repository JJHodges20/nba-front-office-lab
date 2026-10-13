# Forest Terminal - design system

**Status: the colours (sections 1-3) are in effect since P1 (2026-10-11)**, as the owner
decided: both themes kept, the computer's setting followed until Dark or Light is chosen
in the app's menu (the browser remembers it), and `#2f8556` / `#1f6b45` for actions. **The
frame and the style rules (sections 8-9) are in effect since P2**: the navigation in a top
bar and one style rule, both the owner's choice. **The tiles, tags and controls (sections 4,
5, 9 and 10) are in effect since P3**: tiles that wrap, one look per tag, dropdowns where
choices were cut off, and every delete asking first. **The charts (section 6, and the light
palette's changes in sections 2-3) are in effect since P4**, with P5's and P6's additions to
sections 6 and 10. **The assistant's surfaces (section 7) are in effect since P7**, with code
text in the secondary ink (section 2). The evidence behind each value is in
[BASELINE_AUDIT.md](BASELINE_AUDIT.md).

The roadmap's direction: a near-black canvas, a dark forest-green accent, balanced
density, the whole workbench in scope, navigation and behaviour unchanged. This proposal
keeps the lab's existing rules: one palette in `apps/workbench/wb/theme.py`, stated again in
`.streamlit/config.toml` and kept in step by `tests/ui/test_theme.py`; colour chosen by
the job it does; no state or provenance shown by colour alone; native Streamlit settings
before any CSS (the workbench has none today).

## 1. Principles

1. **One source of truth.** Every colour is a role in `wb/theme.py`. The page theme in
   `config.toml` repeats the roles Streamlit can take, and a test fails if the two drift.
2. **Green is for the brand and for action, not for data.** Primary buttons, selected
   controls, links and focus take the forest green. Charts keep their multi-hue categorical
   order, their blue accent and their blue-and-red poles: a loss never turns green.
3. **Native first.** Streamlit 1.64 sets the page, sidebar, widgets, tables, badges,
   headings and chart defaults from `config.toml`. What it cannot set - a raised surface, a
   focus-ring colour, a hover shade, tabular numerals, page padding - is left at Streamlit's
   derived default unless a later phase shows a real need, and then goes in one small,
   documented CSS helper, never in a page.
4. **Both themes work.** Dark is the design target; light stays a complete compatibility
   theme with the same roles (decision D1 in the audit chooses how dark becomes the default).
5. **Contrast is measured, not judged.** Every proposed value below was checked with the
   same arithmetic as the theme tests, and the new roles get tests of their own in P1.

## 2. Colour roles

"Before P1" is what shipped with A9; "P1" is in `wb/theme.py` and `.streamlit/config.toml`
now. Contrast is the WCAG ratio; "OKLab" is the theme tests' colour difference x100.

| Role (`Palette` field) | Used for | Dark before P1 | **Dark, P1** | Light before P1 | **Light, P1** |
| --- | --- | --- | --- | --- | --- |
| `plane` | Page background (`backgroundColor`) | `#0d0d0d` | **`#0a0d0b`** | `#f9f9f7` | keep |
| `surface` | Cards, sidebar, widget fills, chart backgrounds (`secondaryBackgroundColor`, sidebar `backgroundColor`) | `#1a1a19` | **`#151b17`** | `#fcfcfb` | keep |
| `ink` | Text (`textColor`), chart titles | `#ffffff` | **`#f1f5f2`** | `#0b0b0b` | keep |
| `ink_secondary` | Chart axis titles, legends; **P7**: code in text (`codeTextColor`), which Streamlit otherwise prints in the green of a good state | `#c3c2b7` | **`#a7b4a9`** | `#52514e` | keep |
| `ink_muted` | Tick labels, quiet text | `#898781` | **`#7f9084`** | `#898781` | keep; **P4: `#74726d`** (4.68:1, was 3.5) |
| `grid` | Gridlines, borders (`borderColor`, `dataframeBorderColor`) | `#2c2c2a` | **`#2a362e`** | `#e1e0d9` | keep |
| `axis` | Hover borders, reference marks | `#383835` | **`#3a4a40`** | `#c3c2b7` | keep |
| `deemphasis` | Context marks beside the subject | `#52514e` | **`#4e5e54`** | `#c3c2b7` | keep |
| **`brand`** (new) | `primaryColor`: primary buttons, selected tabs and toggles, sliders, focus | (blue `#3987e5`, = `series[0]`) | **`#2f8556`** | (blue `#2a78d6`) | **`#1f6b45`** |
| **`link`** (new) | `linkColor` | (blue `#3987e5`) | **`#79b391`** | (blue `#2a78d6`) | **`#1f6b45`** |
| `series` | Categorical chart colours, fixed order | 8 hues, blue first | keep | 8 hues, blue first | keep; **P4: the 3rd to 5th a step darker** - green `#19a472`, amber `#c28400`, pink `#e46494` (3.10, 3.10, 3.12:1; were 2.74, 2.11, 2.62) |
| `positive` / `negative` | Either side of a baseline | `#3987e5` / `#e66767` | keep | `#2a78d6` / `#e34948` | keep |
| `good` / `warning` / `serious` / `critical` | State, always with an icon and a word | `#0ca30c` `#fab219` `#ec835a` `#d03b3b` | keep | same | keep |

**Why `brand` is a new role, not a new `series[0]`.** Before P1 the tests tied
`primaryColor` to the chart accent (`series[0]`). Turning the accent green would have made
every chart's first series green and moved the one colour the series order was measured
around. A separate `brand` role keeps the charts exactly as they are. P1 changed one parity
assertion - `primaryColor == colors.brand` instead of `colors.accent` - added parity for
`linkColor`, the table colours, `grayColor` and the sidebar's second colour, and added
contrast tests for the new roles; no existing threshold was loosened.

**Why `#2f8556` and not the roadmap's `#244f38`.** Streamlit has one `primaryColor`. It
fills primary buttons under a white label, and it also draws selected tabs, toggles,
sliders and focus borders straight on the page. `#244f38` makes a superb button
(white label 9.3:1) but those controls would almost vanish on black (2.1:1, under the 3:1
that a control needs). `#2f8556` is the darkest forest green that serves both:

| Candidate | White label on it (needs 4.5) | Against the page | Against a card |
| --- | --- | --- | --- |
| Today's blue `#3987e5` | **3.64** - fails | 5.37 | 4.81 |
| Roadmap `#244f38` | 9.33 | **2.09** - fails | **1.87** - fails |
| `#316749` | 6.63 | **2.95** - fails | **2.64** - fails |
| `#2e7d52` | 5.03 | 3.88 | 3.47 |
| **`#2f8556` (proposed)** | **4.56** | **4.29** | **3.84** |
| `#348a5b` | **4.26** - fails | 4.59 | 4.11 |

So the change also fixes a weakness of the current theme: white on today's blue primary
button is 3.64:1 in dark and 4.42:1 in light, both under 4.5. In light, `#1f6b45` gives a
white label 6.47:1 and stands 6.13:1 against the page.

**What the green stays apart from.** `#2f8556` is far from the chart accent (OKLab 22.1
from blue) but near the "good" status green (12.4) and the two green chart slots (7.3, 8.0).
That is acceptable because a state always carries an icon and a word, and the brand never
appears inside a chart. The provenance tags are another matter (section 5).

**Roadmap tokens not proposed for P1.** `surface_raised #1d2620`, `forest_hover #316749`,
`focus_ring #91c9a6` and the deep `#244f38` have no Streamlit setting: Streamlit derives
hover, raised and focus shades from the roles above. They are kept here as candidates if
P2 or P3 shows a need for a small CSS helper. (`#91c9a6` would stand 10.3:1 on the page.)

## 3. Checked against the theme tests

The P1 dark palette, with the series unchanged, passes every check `tests/ui/test_theme.py`
made before P1:

| Check | Threshold | Dark before P1 | Dark, P1 |
| --- | --- | --- | --- |
| Neighbouring series, normal / colour-blind | >= 15 / >= 8 | 19.3 / 8.4 | 19.3 / 8.4 |
| First three series, every pair | >= 15 / >= 8 | 20.9 / 9.4 | 20.9 / 9.4 |
| A fourth scatter series would fail | < 15 or < 8 | 10.6 / 4.8 | 10.6 / 4.8 |
| Diverging poles on the surface | >= 3 | 4.79 / 5.39 | 4.81 / 5.41 |
| Accent / de-emphasis on the surface | >= 3 / >= 1.5 | 4.79 / 2.19 | 4.81 / 2.54 |
| Ink / secondary / muted on the surface | >= 7 / 4.5 / 3 | 17.4 / 9.7 / 4.8 | 15.9 / 8.1 / 5.2 |
| Grid < 1.5, axis < 2.0, grid < axis | | 1.24 / 1.48 | 1.39 / 1.86 |
| Every dark series on the surface | >= 3 | 3.5 to 5.7 | 3.5 to 5.7 |
| Dark surface against light surface | > 15 | 17.0 | 17.0 |

Checks P1 added, in both themes: a white label on `brand` >= 4.5; `brand` against `plane`
and `surface` >= 3; `link` against `plane` and `surface` >= 4.5; the brand is no series
colour, no state colour, and at least 15 from the chart accent; and parity of
`primaryColor`, `linkColor`, the table colours, `grayColor` and the sidebar's colours with
the palette. Status colours on the new dark surface: good 5.2, warning 9.5, serious 6.6,
critical 3.6.

Checks P4 added or tightened, in both themes: every series at least 3:1 on its chart (the
light theme's green, amber and pink were under it, finding F16); and the muted ink at least
4.5:1 on the surface and on the page. That test had allowed 3:1, calling 12px tick labels
large text, which they are not. With the three light series darker, neighbours still differ
by 18.8 (9.0 for colour-blind readers), the first three by 22.6 (9.7), and a fourth scatter
series is still unsafe (2.0), so the cap of three stands.

## 4. Type, shape and spacing

Kept from today's `config.toml`, which already fits the brief:

- **Font:** `system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif` (Segoe UI on
  Windows), 15px base; headings 2rem / 1.4 / 1.15 / 1 / 0.95 / 0.9 at weights 650 / 600.
  Charts use the same family at 13px, ticks 12px.
- **Corners:** `baseRadius = "8px"`; buttons follow it. Bars keep their 4px data end.
- **Borders:** widget and sidebar borders on, in the `grid` colour.
- **Figures:** `st.metric` tiles with a border, up to five a row; context kept to about
  twenty characters (CLAUDE.md), three a row where it is longer. **Since P3 the tiles
  wrap** (section 9): as many equal tiles as fit, at least 11rem wide in a row of five or
  more and 14rem in a row of four or fewer, so a narrow window gives fewer a row instead of
  cutting their numbers.
- **Spacing:** Streamlit's own gaps; rows of controls use `gap="small"`. The space above a
  page's title is a style rule (section 9). Tabular numerals have no native setting; P3
  found no need for them.

Looked at in P3 and kept as they are: `metricValueFontSize` (the tiles' 2.25rem numbers read
well and, wrapping, no longer get cut), `buttonRadius` (the 8px of every other corner), and
the table colours (the header on `surface` stands apart from the rows on `plane`, numbers
sit right, a missing value is a dash).

## 5. Tags: provenance, state and outcome

Every tag is a word and an icon as well as a colour (`components.py`). Today:

| Vocabulary | Members and colours |
| --- | --- |
| Provenance | Measured blue, Derived gray, Estimate orange, Modeled green, Your assumption violet, Reported yellow |
| Source state | Up to date green, Stale orange, Failing red, Not supplied gray |
| Answer outcome | Supported green, Partly answered orange, Not enough to answer gray, Question back blue, Declined gray |

Settled in P3:

- **Modeled stays green** (decision D3, the owner's, 2026-10-11). `st.badge` offers seven
  named colours and every one is already a provenance or a state, so no free hue exists.
  The one swap tried - Modeled violet, *Your assumption* in the brand green - left *Your
  assumption* dim on the dark page (the brand is 4.29:1 there, under the 4.5 small text
  needs). The word and the icon tell Modeled apart, as before.
- **One look per word.** The tags several pages use are written once in `components.py`:
  `NOTE` (blue, `info`: something to know), `CHECK` (orange, `warning`: something to look
  at, such as a rule a roster breaks), `OUT_OF_DATE` (orange, `schedule`) and `NO_ANSWER`
  (red, `error`). "Note" had been blue on two pages, orange on two and gray in the answers;
  Team Builder's broken rules are now *Check*. A test holds every tag word in the
  workbench to one icon and one colour.

## 6. Charts

Unchanged: the house rules of `wb/charts.py` (one scale, 2px lines, bars at most 24px,
ringed markers, no dashes, text in ink, legends only for several series, three scatter
and four line series at most) and the categorical order. The chart surface follows the
`surface` role, so charts took the new dark card colour with no builder change.

**In effect since P4** - every chart was photographed in both themes at 1440, 1024 and
390px, and its text measured against its own box:

- **Cap lines** (`_thresholds`): their names take turns on three rows, not two - on a phone
  *Tax* had sat on *2nd apron* - and the lines are drawn in `deemphasis`, a step above the
  gridlines they stand among (in the light theme that is the colour they had).
- **Long axis titles** take two balanced lines past 32 characters (`LONG_TITLE`): centred
  under a phone's narrow plot, six ran past the chart's edge.
- **A reference line's name** runs away from the end of the axis it sits near, so it stays
  on the chart; the same for the value a histogram marks.
- **Interval rows** leave room either side of the widest interval, as they already did
  beside a reference line: no interval ends on the chart's edge.
- **Dates** are few, level where they fit and slanted where they do not: on Team Explorer's
  form chart at 1024px three dates had printed on top of each other.
- **A histogram's** value labels sit a little lower, clear of the count axis's "0".
- **Stacked bars** refuse more parts than the palette has slots (finding F19), as the
  other builders do; a ninth part had been dropped without a word.
- **Kept, with reasons.** A chart that keeps its old colours for a moment after the theme is
  switched (F2): Streamlit does not run the page again on a switch, and nothing short of a
  script in the page would make it; the next click redraws it, and the choice is
  remembered, so it is seen once. Charts keep their filled panel rather than becoming
  outlined cards like the tiles (F10): an outlined chart needs a see-through background,
  and then, just after a switch, its text would be dark on dark until that click.
  Benchmarks' columns hold their two-line labels level: tilted, they garbled.

**Added in P5:**

- **Many columns, two levels of labels** (`STAGGER_FROM` = 9): from nine columns a column
  chart's labels take turns on two levels, each with two columns' room. At 1024px
  Benchmarks' fourteen bands ("40 to 45", "n = 145") had run together; the words and the
  counts stay as they were.
- **A chart's table view names its columns in words** (`components.heading`): a metric by
  its stat-sheet label, with its meaning on hover, and the rest in plain case ("Team", "Wins
  low") - they had shown the columns' own names, such as `team_name`. The CSV keeps the
  columns' own names.
- **The export buttons are short**: *Data (CSV)* and *Chart (HTML)*, the second with a
  tooltip; "Interactive chart (HTML)" was cut in a narrow column.

**Added in P6:**

- **An uncertainty band is drawn, and can be seen.** The chance curve on Postseason Outlook
  says "the band is the 95% interval", and no band had ever been drawn: its edges were
  traces with no line, so Plotly placed the lower edge nowhere and filled to nothing. The
  edges are now lines of no width. The wash behind a line is a role of the palette,
  `wash_opacity`: 0.15 in the light theme and 0.25 in the dark, where a tenth was all but
  invisible. A test holds it visible against the chart, translucent, and under a line that
  still reads at 3:1.

## 7. The assistant's surfaces (P7)

The answer is drawn by `wb/answers.py` on the AI Research page, and in short in the *Ask
AI about this* dialog. In effect since P7, each part checked live with the local model on a
throwaway copy of the data, at four window sizes and in both themes:

- **The page's top** holds what a question needs to start: the title and a two-line
  subtitle, the kinds of number, the assistant's and the sources' state, the workspace bar
  and what the workspace is about. What the workspace keeps is **one fold** - "In this
  workspace: Findings (n) · Proposed rosters (n, k waiting) · Experiment proposals (n)" - with
  a tab for each shelf (three folds, one under another, had pushed the first question below
  a laptop's window: finding F9). The fold and its tabs are keyed and the tabs' names hold no
  count, so saving or deleting on a shelf leaves it open where it was; every popover below
  the line that says what the last action did is keyed too, so it stays open as that line
  goes (F30).
- **The mode and the conversation's buttons** - Quick or Deep, *New conversation*, *Fetch
  current information* and what the last fetch did - sit under the conversation, just above
  the question box, where a question is asked. The page opens at its end, so they are in
  view.
- **The question**: Streamlit's user message, a filled card, with its mode, focus and time
  under it. **The answer**: its outcome tag first (the word, the icon, the colour) and the
  kinds of number it rests on, then the text, then notes and limits; modeled figures keep
  their interval in the text.
- **A question under way**: a running box - a spinner, never a tick - with each step as it
  comes, then *Stop*. A box a fragment draws again is written into without a `with` block,
  since leaving one marks it complete (F27).
- **What an answer rests on**: each result in a tab, with the chart its tool chose and its
  rows; each figure once, in the lab's words where it has them, and a percentile as every
  page writes one (F28). The evidence's fold counts the sources and names their kinds -
  "Evidence: 3 sources · the lab's data, the web" - so a reader sees whether the web was
  read before opening it; each source is led by its kind's icon: the lab's data `database`,
  a fitted model `model_training`, the contract file `request_quote`, current information
  `update`, the web `public`, the lab's documents `menu_book`. Paths and table names are code,
  in the secondary ink (F26). *How it was answered* lists each step, the model, the rules'
  version and the time. Both folds start closed.
- **Rosters to review**: each card leads with what has become of it - *Waiting* (orange,
  `pending`: "Not saved yet"), *Saved* (green, `check_circle`: "In the Team Builder as ..."),
  *Declined* (gray, `block`, as a declined answer looks) - then its tiles, how it differs from
  Option A, what it rests on and its players; the buttons come last and say what they do.
  Nothing is saved without the click, as before.
- **Experiments to review**: the assistant's idea tagged as untested, the lab's test tagged
  Modeled, kept apart, as before.
- **The dialog** carries the assistant's icon in its title, the answer in short, and *Open in
  AI Research*. It is the contextual way in at every size; the roadmap's docked panel is not
  built (decision D12).
- **Errors and an offline model**: a tagged line that says what to do; the conversation
  stays.

Kept, with reasons: the result tabs under an answer, which a phone scrolls sideways (F22 -
shorter, they would not say which result is which); and the avatars' column, which on a phone
indents each message by about 50px - it is Streamlit's chat layout, and no setting moves it.

## 8. The frame (P2)

- **Navigation in a top bar** (`st.navigation(position="top")`, the owner's choice): the six
  groups - League, Explore, Build, Forecast, Ask, System - are menus across the top, each
  opening its pages in the same order, under the same names and addresses. On a phone the
  menu folds into the sidebar.
- **The sidebar holds the filters and the data status**, so season, phase, team, player and
  the comparison window are always in view. It starts open on a desktop and closed on a
  phone (`initial_sidebar_state="auto"`), where it would cover the page.
- **Data status**: each source's state in a word and an icon; what lies behind it on hover;
  a line under it only when something needs doing (stale, failing, not supplied); the
  build; and a link to Data Health, where everything is in full.
- **Messages**: `components.alert(kind, message)` draws every error, warning, success and
  note, one icon per kind - error `error`, warning `warning`, success `check_circle`,
  note `info` - on every page.

## 9. The style rules

What Streamlit's theme cannot set lives in one file, `apps/workbench/wb/style.css`,
applied once per run by the frame through `wb/style.py` - never from a page.
`tests/ui/test_style.py` checks that the file holds these rules and nothing else, that only
the frame applies it, and that no page injects HTML or CSS of its own.

| Rule | Why | If Streamlit renames the hook |
| --- | --- | --- |
| `[data-testid="stMainBlockContainer"] { padding-top: 2.5rem; }` | With the top bar, Streamlit leaves 8rem above every title (6rem on a phone); 2.5rem keeps the title clear of the bar and shows about 80px more of each page on a desktop, 50px on a phone, measured in a browser (the owner's choice, P2) | The gap returns to Streamlit's own; nothing else changes |
| `[class*="st-key-tiles-"] [data-testid="stHorizontalBlock"] { display: grid; grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr)); }` | Headline tiles (`components.figures`, rows keyed `tiles-`): Streamlit's columns never wrap, so at 1024px five tiles were cut to 103px. As a grid they take as many equal columns as fit and wrap the rest: five across at 1440 and 1366 as before, three and two at 1024, two a row on a phone (the owner's choice, P3) | The tiles are Streamlit's columns, as before P3 |
| `[class*="st-key-tiles-"] [data-testid="stColumn"] { width: auto; min-width: 0; }` | A column's own width is a share of its row, which inside a grid cell would shrink the tile to that share of the cell | As above |
| `[class*="st-key-tiles-wide-"] [data-testid="stHorizontalBlock"] { grid-template-columns: repeat(auto-fit, minmax(14rem, 1fr)); }` | A row of four tiles or fewer (and `per_row=3`, for long text) has room for wider tiles: at least 14rem, so four stay across a desktop, a 1024px window gives two a row, and a phone one, as before - at 11rem a phone's two a row cut Contract Explorer's tiles | As above |

## 10. Choices and actions (P3)

- **A segmented control is for a few short choices.** On a row of its own it wraps onto a
  second line in a narrow window (Player Explorer's columns); inside columns or beside other
  controls it cannot, and its last choices are cut off - at 1024px the simulator's
  *Regression* could not be reached. A longer set of choices there is a dropdown:
  Benchmarks' seasons, the Optimizer's budget, the simulator's games missed and development.
  In a narrow column even three short choices need the column's width: P5 set the form
  charts' *Metric* and *Trailing games* one above the other, where side by side the choice
  of 20 games was cut off at 1024px.
- **What cannot be undone asks first** (the owner's decision): `components.confirmed_button`
  stays off until its box is ticked, and is never the page's main action - deleting a
  roster, a workspace, a finding or an experiment proposal, and clearing a workspace's
  history. A finding's and a proposal's sit in a *Delete* popover beside *Edit*. A test
  keeps any page from drawing a plain Delete or Clear button.
- **The open page's group is not named on the page** (decision D7, the owner's): placed
  above or beside the title it must clear the top bar, which pushes every page down about
  60px. The open menu marks the page, and the title names it.
