# UI polish: release checklist

What to do before the `ui-polish` branch is pushed and merged. Every step is the owner's to
run or to approve: nothing here is done for them. The evidence for each phase is in
[FINAL_AUDIT.md](FINAL_AUDIT.md) and `docs/DEVELOPMENT_LOG.md`.

## 1. Decide

- [ ] **D13**, a keyboard path to the pages (finding F31): an *All pages* fold in the sidebar,
      or leave it.
- [ ] **D14**, focus marks on links and menu items (F32): one more style rule, or leave it.
- [ ] **F29**, the answer checker: whether to open an assistant milestone for it.
- [ ] **The README's screenshots**: new ones in the new look, or keep the old ones.
- [ ] **D6**, the assistant's context: unchanged by the polish; a separate proposal if wanted.

## 2. Look

Start the workbench the usual way, from the project folder - `.\.venv\Scripts\fol.exe ui`;
`streamlit run` from anywhere else shows no theme (finding F18) - and choose **Dark** in the
app's menu (top right) once: the browser remembers it.

- [ ] Every page from the top bar, in both themes: League Overview, Winning Benchmarks,
      Player Explorer, Player Value, Team Explorer, Contract Explorer, Analytics Lab, Team
      Builder, Roster Fit, Roster Optimizer, Postseason Outlook, Scenario Simulator, AI
      Research, Data Health.
- [ ] A team and a player chosen in the sidebar, kept from page to page.
- [ ] A narrow window (or a phone): tiles wrap, the sidebar starts closed.
- [ ] AI Research: a Quick question; *Stop* on a second one; the evidence opened.

## 3. Test

```powershell
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m pytest -n auto    # every test but the live ones; about 5 minutes
```

- [ ] Ruff clean; every test passes (3,983 or more at P8).
- [ ] Optional, with Ollama running: `.\.venv\Scripts\python.exe -m pytest -m ollama`.

## 4. Push

- [ ] On the `ui-polish` branch, never `main`: `git status` clean, `git log origin/ui-polish..`
      lists P5 to P8.
- [ ] The outgoing diff holds no data, PDFs or keys:

      ```powershell
      git diff --stat origin/ui-polish..ui-polish
      git diff --name-only origin/ui-polish..ui-polish | Select-String -Pattern "data/|\.pdf$|\.env$|\.sqlite"
      ```

      The second command must print nothing. `.env` (the web search key) is git-ignored and
      must never be committed; `.env.example` holds no value.
- [ ] `git push origin ui-polish`, then open a pull request to `main` for review.

## 5. If something goes wrong

- **A page looks wrong after an update**: stop the workbench (Ctrl+C) and start it again; a
  running server keeps the old code.
- **The theme is off**: the colours are in `.streamlit/config.toml` and `apps/workbench/wb/theme.py`,
  kept in step by `tests/ui/test_theme.py`.
- **A Streamlit upgrade moved its markup**: the four style rules in `apps/workbench/wb/style.css`
  then do nothing, and the page falls back to Streamlit's own spacing and columns
  (DESIGN_SYSTEM.md section 9). Nothing breaks.
- **To undo a phase**: `git revert` its commit (the table in FINAL_AUDIT.md lists them). No
  phase changed the data, a model or a stored record, so nothing else needs undoing.
