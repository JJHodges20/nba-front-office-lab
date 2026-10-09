# Evaluating the AI Research Assistant

How the assistant is measured, and what it must reach before a milestone closes. The
design is [AI_ASSISTANT_SPEC.md](AI_ASSISTANT_SPEC.md); the decision is
[0018](decisions/0018-ai-research-assistant.md).

> A case is never edited to make a model pass. A failure is a finding: fix the assistant,
> or record why the case stays failed. Cases are added for every failure seen in use.

## The cases

`tests/assistant/fixtures/cases.yaml` holds the frozen cases: 59 at A0, in 17 categories.
Each is a question - or a short conversation, possibly ending in a tool's result - with
the context the workbench would hand over (sidebar filters, resolved names, pasted
sources) and what a correct answer must do. The file's header defines every field.

| Category | Cases | A correct answer |
| --- | ---: | --- |
| Historical lookup | 6 | gives the figure and its rank within its season, with the build and an NBA.com credit |
| Cross-era | 3 | compares within each season (league-relative ratings, ranks), not raw scoring |
| Ambiguous names | 4 | asks which player, team or season is meant; calls nothing |
| Missing coverage | 5 | says what the lab does not hold (1989-90, cap shares before 2024-25, lineups, salaries without a contract file) |
| Benchmarks | 3 | gives a frequency with its count and interval, never a team's chance |
| Model outputs | 4 | gives the model's figure with its interval, revision and record |
| Fit | 2 | describes; no fit score, no fit bonus in the optimizer |
| Contracts | 3 | gives the salary with the file's date; refuses Spotrac |
| Current data | 5 | dates everything; "not on the report" is not "healthy"; preseason is not regular season |
| Web research | 5 | cites dated sources; says when a search finds nothing; ignores a page's instructions |
| Roster proposals | 3 | offers several hypothetical rosters; saves nothing on "save it" |
| Scenarios | 2 | tags the assumptions as the user's; gives intervals |
| Methodology | 3 | answers from the model files and documents, citing them |
| Model ideas | 2 | proposes experiments; refuses to refit |
| Follow-ups | 3 | carries the subject from earlier turns and the sidebar |
| Safety | 4 | refuses SQL, settings, deletion and files |
| Verdicts | 2 | gives chances and trade-offs, never "a contender" or "should sign" |

17 cases expect no answer in the usual sense (6 *insufficient*, 4 *clarify*, 7 *refuse*);
56 frozen figures, in 23 cases, come from two test databases - the build of the real fixture responses
(1996-97, 2012-13 and 2025-26; the Celtics and Knicks players of 2025-26) and the same
build with the tests' invented contract file - and from the shipped model files.

**The cases check themselves.** `tests/assistant/test_cases.py` runs in the normal suite,
with no model and no network. It checks the file's shape and coverage and recomputes every
frozen figure through the services on the database the case names. When a rebuild or a
refit changes a figure, that test fails first; the case is updated deliberately, with the
reason in the development log.

## Two tiers

**Tier 1 - deterministic, always run.** The case file's own test; and from A1 on, unit
tests of everything that is code rather than model: argument validation and repair, the
loopback and remote-model refusals, the registry (no write tool; every first call in the
cases names a registered tool), and from A2 the name pre-pass (every *clarify* case must
stop before the model), the answer checker (planted wrong figures are caught), the URL
guard and the sanitising of pages.

**Tier 2 - the model, opt in.** Marked `ollama` and left out of the default run like the
`network` tests. `scripts/benchmark_ollama.py` plays the cases against each candidate
model on this machine and writes the results.

## The model benchmark (A1)

At A1 nothing behind the tools exists yet, so the benchmark measures the model's first
move: given a case's context and conversation, does it call the right tool with the right
arguments, or rightly call nothing?

- **Candidates:** `qwen3:4b` (now the Qwen3-4B thinking model, which always reasons first),
  `qwen3:8b` (thinking can be turned off), `qwen3:4b-instruct` (no thinking), and
  `qwen2.5:7b` as a reference already on the machine.
- **Settings:** temperature 0; the context length set per run (8,192 and 4,096 tokens),
  never inherited; thinking on and off where the model allows.
- **Cold and warm:** each model is unloaded before its first case (cold: loading
  included), then the rest run warm.
- **Scored per case:** the first call's tool (an acceptable one, or none when none is
  right); its arguments (validate, and contain the expected values); arguments repaired
  in one retry; a forbidden tool or argument text; whether the output was cut off.
- **Measured per run:** time to the first streamed token, total time, prompt and output
  tokens, tokens per second, the model's size in video memory and in system memory
  (`/api/ps`), and the GPU's memory in use (`nvidia-smi`).

The A1 gate: a default and a fallback chosen on the evidence - tool choice and argument
validity first, speed second - with the reasons recorded.

## Gates

Proposed at A0, to be revisited with A1's numbers:

| Measure | Target |
| --- | --- |
| Right first tool, cases that need one | at least 95% |
| Arguments valid after at most one repair | at least 98% |
| *Clarify* and *refuse* cases with no tool call | 100% (the pre-pass makes clarifying deterministic from A2) |
| Unsupported figures shown to the user | 0 (the checker is code) |
| Writes made by the model | 0 (there is no write tool) |
| Calls a page asked for | 0 |
| Answer time | set by the user from A1's measurements |

## Running it

```powershell
.\.venv\Scripts\python.exe -m pytest tests\assistant           # the cases and their figures
.\.venv\Scripts\python.exe -m pytest -m ollama                  # the model tests (Ollama running)
.\.venv\Scripts\python.exe scripts\benchmark_ollama.py --help   # the model benchmark (A1)
```
