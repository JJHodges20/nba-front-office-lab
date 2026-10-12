# Release notes: the AI research assistant (A0-A9)

This release adds the AI research assistant to the lab: the **AI Research** page, where a
language model running on this computer answers questions in plain words from the lab's
own tools, and *Ask AI about this* on the other pages. It was built in ten milestones
(A0-A9, `docs/ROADMAP.md`) and checked as a whole in the last, the release audit. Why it is
built this way is [decision 0018](decisions/0018-ai-research-assistant.md); how it is
measured is [AI_EVALUATION.md](AI_EVALUATION.md).

## What it does

- **Answers from the lab's tools.** Statistics for players, teams and seasons; the fitted
  models - player value, roster fit, postseason chances, the scenario simulator; the lab's
  own documents; the contract file; this season's games, the league's transactions and its
  injury report, fetched as they fall due; dated news from the Hoops Rumors feeds; and the
  web, through your own Ollama account. Every figure in an answer is checked against what
  the tools returned before you see it, and one that no result holds is taken out.
- **Says what each answer rests on.** Each answer opens with its kind - supported, partly
  answered, not enough to answer, a question back, declined - and shows its rows, its
  charts and its sources with their dates. A modeled figure comes with its error: a chance
  with its 95% interval and the model's record on seasons it had not seen.
- **Never acts on its own.** It has no tool that writes. A roster it proposes is saved to
  the Team Builder only when you press *Save approved roster*, and only if the data, the
  model and the salaries are unchanged; an experiment it drafts for one of the models is
  kept only when you press *Keep in the workspace*, and is never applied. It gives no
  verdicts: asked "are they a contender?", it lays out the evidence.
- **Keeps your research.** Named workspaces on this computer hold every question and
  answer, findings, notes, proposed rosters and experiment proposals. A follow-up reads
  only its own workspace's conversation. Rebuilding the lab's data never touches them.
- **Stays on this computer** apart from what you ask of the web: the model runs locally
  through Ollama, which the lab reaches at 127.0.0.1 only; Ollama's cloud models, which
  could cost money, are refused.

## Install

Everything else in the lab works without the assistant.

1. The lab itself, as before: `.\scripts\bootstrap.ps1`, then `fol refresh` (README).
2. Install Ollama from ollama.com and start it.
3. `ollama pull qwen3:8b` - about 5 GB, once.
4. For web search, which is optional: copy `.env.example` to `.env` and put your own
   Ollama account's key after `FOL_OLLAMA_API_KEY=`. Never commit `.env`. Without it,
   links you paste into a question are still read.
5. `fol ui`, then open AI Research. The top of the page says whether the assistant is
   ready and, if not, what to do.

Start the workbench with `fol ui` rather than `streamlit run`: `fol ui` starts it from the
project folder, where `.streamlit/config.toml` keeps Streamlit's usage statistics off and
the server on this computer only.

## How it was checked

The release audit, milestone A9. [AI_EVALUATION.md](AI_EVALUATION.md) has every figure.

- **The test suite**: 3,950 tests pass in under five minutes, and the live model's own
  tests too. The suite is held to this computer: a test that reaches the network fails.
  The layer rules are tested, among them that only the providers can open a connection.
- **59 frozen questions**, answered end to end three times on the release code: 49, 49 and
  47 passed in every part. In every run no figure that no result holds was shown, nothing
  was saved, and a page's planted instruction was not followed. The right tool came first
  for 36 of the 37 that need one, and every question that should be asked back or refused
  was, with no tool called. One target is missed - see Known limits.
- **8 experiment questions**: 5 of 8, and every decision to draft one or not right.
- **A working session**: twenty questions a user might ask - follow-ups, a missing season,
  a verdict, injuries, news, the web, a scenario, rosters, a request to save one - asked
  twice in a row on a copy of the real data. Of the 40 answers, 34 answered the question in
  full or in part, 2 rightly said the lab holds no such season, the request to save was
  refused both times, and 3 missed what the lab holds. Every answer was kept; none failed.
  The model loads in 11 seconds and a first answer, cold, takes about 19; once loaded, a
  Quick answer takes 9 seconds at the median and a Deep one 75. `qwen3:8b` takes 5.8 GB,
  all of it on an 8 GB graphics card ([ASSISTANT_SESSION.md](research/ASSISTANT_SESSION.md)).
- **Failure on purpose**, each with a test: Ollama stopped, slow or cut off midway; the
  network down; sites that refuse or fail; a damaged research file; a season the lab does
  not hold; *Stop* pressed while the model writes; a page with planted instructions; a
  model that obeys them.
- **In a browser**, light and dark: the damaged research file said, set aside and started
  afresh, and the Ask dialog with it.
- **The network**: every place the code can reach it was checked against the source
  register. Nothing paid runs, and nothing undeclared.

What the audit found, and fixed: the roster optimizer's solver could hang or crash when
different threads took turns calling it, as the workbench's pages and the assistant's
questions do; *Stop* let the model's last request run;
a damaged research file stopped the AI Research page; questions about what a figure means,
or for a verdict, were sometimes answered from the model's memory; one result did not say
what it held; and an image named by reference in an answer would have been fetched.

## When something goes wrong

| What you see | What to do |
| --- | --- |
| *Assistant: offline* | Start the Ollama app. Every other page works without it. |
| *Assistant: no model* | `ollama pull qwen3:8b`, then reload the page. |
| An answer is taking long | Press *Stop*: what was gathered so far is kept, and nothing the model was writing when you pressed it is acted on. A Quick question stops looking things up after about 90 seconds, a Deep one after about 5 minutes. |
| *Your saved research cannot be opened* | The file that keeps your workspaces, `data/assistant/assistant.sqlite`, is damaged or was made by a newer version of the lab. *Set it aside and start afresh* renames it beside itself (`assistant-set-aside-<time>.sqlite`, with its `-wal` file if there is one) and starts a new one; nothing is deleted. Copies made before each upgrade of the file are in `data/assistant/backups/`: to go back to one, stop the workbench and copy it over `data/assistant/assistant.sqlite`. |
| Games, moves, injuries or news look old | `fol current status` says when each was last fetched and whether the last try failed; `fol current refresh` fetches what is due. A failed fetch keeps the last copy and says how old it is. |
| *Web search: not set up* | Put your key in `.env` (Install, step 4). |
| *Ollama's web search allowance is used up for now* | The free allowance is not published; wait and try later. The lab never retries on its own. |
| An exported chart (HTML) shows nothing | It loads Plotly's script from the web when opened; open it with a connection, or save the chart as a PNG with the camera button instead. |
| A page shows an error after an update | Stop the workbench (Ctrl+C) and start it again: a running server keeps the old code. |

## Known limits

- **A small model.** `qwen3:8b` runs on an 8 GB graphics card. On the 59 frozen questions
  it chose the right first tool for 36 of the 37 that need one, and got every part right in
  49. What it gets wrong is mostly its wording around the figures: a citation left out, a
  season not said, a figure under the wrong label, which the checker cannot always see. A
  figure that no result holds never reaches you: the checker takes it out.
- **Made-up ids.** In two of the frozen questions the model makes up a team's id - "1", or
  the Knicks' id cut short to "2752". The lab refuses such a call rather than guess, and
  says which id was likely meant, so the answer comes back incomplete rather than wrong.
  This is the one evaluation target the release misses: 93% of calls valid, against 98%.
- **Answers vary.** The model runs at temperature 0, yet the same twenty questions asked
  twice in a row got the same tools 16 times but the same kind of answer only 9 times: each
  answer becomes part of the conversation the next question reads, and small differences
  grow. The wording, and sometimes which tools are used, differ between runs; what is
  checked - no unsupported figure, nothing saved - held every time.
- **No verdicts.** Asked whether a team is a contender, or whom to sign, it lays out the
  evidence and says it gives no verdict.
- **The web.** Search uses your own Ollama account, whose free allowance is not published.
  Sites that ask AI agents not to read them are not read - ESPN and AP among them - and
  Sports Reference, Spotrac and nba.com are refused. A page's words are its site's, shown
  as such.
- **The injury report** is read but never redistributed, and none is published in the
  preseason. A player not on it is never called healthy.
- **Salaries** come from your own contract file: the lab cannot fetch them.
- **An exported interactive chart (HTML)** needs a connection to draw.
- **Measured on one machine**: Windows 11 with an RTX 4060 (8 GB), Python 3.14, Ollama
  0.40.0. On other machines the times will differ.
