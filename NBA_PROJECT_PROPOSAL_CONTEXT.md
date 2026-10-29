# NBA Front Office Lab: project proposal context

From a read-only inspection of the repository on 2026-10-19 (last commit `df52ef9`,
2026-10-15). Every statement below comes from the code, configuration, local data or
documentation; the test figures come from a run on 2026-10-19.

## 1. Project overview

- **Name:** NBA Front Office Lab (Python package `front_office`, command `fol`, version 0.1.0).
- **Purpose:** a research workbench for one question: *how can a team assemble a highly
  competitive roster, possibly a championship one, on a constrained payroll?* It combines
  player and team statistics, contracts, salary-cap rules, historical team outcomes and
  roster fit.
- **Intended users:** someone doing front-office research into roster construction under a
  budget. It runs on the user's own computer.
- **Problem it solves:** "best stats for the least money" ignores whether players add up to
  a contender. The lab measures player value, roster fit and postseason chances, and shows
  every estimate with its error, beside its record on past seasons.
- **What a user can do:**
  - explore league, team and player statistics since 1996-97;
  - import a contract file, then see payrolls against the cap, tax line and aprons;
  - build rosters by hand and check them against roster rules;
  - see how often past teams reached each playoff stage;
  - read a tested player-value model (impact, wins above replacement, value against salary);
  - describe a roster's fit;
  - generate several candidate rosters under a budget;
  - estimate postseason chances with intervals;
  - simulate what-if scenarios;
  - ask a local AI model questions answered from the lab's own data and models;
  - sign in and ask questions about the lab's documentation (RAG).

## 2. Current architecture

The package in `src/front_office/` is layered: providers, raw store, processing, storage,
analytics, modeling, services, then the outer interfaces (command line, workbench, AI
assistant, API). An architecture test fails on any import that crosses the layer rules.

| Area | What exists |
| --- | --- |
| **Backend** | FastAPI app factory `server/app.py`, served by uvicorn on port 8000. **16 endpoints:** health (1); sign-in: `register`, `token`, `GET`/`DELETE /auth/me` (4); documents: `POST /rag/ask`, question history (list, get, delete) and `GET`/`POST /rag/index` (6); lab data: `/lab`, a season's teams, a team, a season's players, a player (5). Data endpoints are read-only and expose no salaries. |
| **Frontend** | Streamlit workbench `apps/workbench/`: 15 pages in six menus, Plotly charts, dark and light themes. 14 pages call the services directly. *Ask the Docs* calls the API over HTTP with the token (`wb/api_client.py`). |
| **Databases** | **`data/front_office.sqlite`:** 23 tables built with SQLAlchemy from typed data contracts. The one declared foreign key is `roster_players` → `custom_rosters`; other references between tables are checked by data-quality checks. The local build holds 30 teams, 892 team-seasons, 5,242 players, 20,668 player-seasons, 76,046 team games and 4,189 contracts. **`data/api/accounts.sqlite`:** SQLAlchemy ORM, `api_users` one-to-many `api_questions`, a relationship each way, cascade delete; created on the API's first use. **`data/assistant/assistant.sqlite`:** research workspaces plus five child tables keyed to them. **`data/rag/`:** ChromaDB. |
| **Authentication** | JWT signed with HS256 (PyJWT); 60-minute expiry; issuer and required claims checked. Passwords kept only as bcrypt hashes (cost 12). Every endpoint except `/health`, `/auth/register` and `/auth/token` needs the token. The signing key comes from `FOL_API_SECRET`, or else from a key file generated in `data/api/`. **The workbench asks for a sign-in before any page** (C8, decision 0020), against the same accounts; one sign-in also signs in to the API for *Ask the Docs*. |
| **AI / ML** | **Statistical models:** a player-value model, a postseason-probability model and simulator parameters. Each is fitted to roughly thirty seasons, tested on seasons it had not seen, and pinned in `configs/models/`. A constrained roster optimizer runs on top. **AI Research assistant:** a local Ollama model (`qwen3:8b`, fallback `qwen3:4b-instruct`) calling typed, read-only tools. A checker removes any figure the tools did not return, and a proposed roster is saved only on the user's click. It also has keyword (SQLite FTS5) search of the docs and optional web search. |
| **RAG** | Markdown files under `docs/`, split at headings (six files excluded), embedded with `nomic-embed-text` into the ChromaDB collection `lab_documents`. For each question, the five nearest passages go to `qwen3:8b`, which answers from them alone with numbered citations. The checker cuts figures no passage holds, and the answer is stored under the user. |
| **Docker** | `compose.yaml`: `ollama` (`ollama/ollama:0.40.0`); `models` (a one-time pull of both models); `api` (indexes the docs, then serves on 8000, with a health check); `ui` (Streamlit on 8501, starts once the API is healthy). Ports are bound to 127.0.0.1, and `data/` is mounted. `compose.gpu.yaml` adds an NVIDIA GPU. The `Dockerfile` uses `python:3.14.6-slim` and runs as a non-root user. |
| **Tests** | pytest, **4,259 collected** at C7: unit 3,355, ui 787, assistant 73, architecture 25, integration 19; 4,272 after C8. Live-network and Ollama tests are deselected by default; Ollama, the network and the API are faked. A full run on 2026-10-29 (`pytest -n 6`): **4,272 passed**, in 5 min 44 s, after C8 added 13 sign-in tests. |

## 3. Current development status

| Feature | Status |
| --- | --- |
| League data pipeline (`fol refresh`: stats.nba.com → raw store → database) | Implemented and functional |
| League, Player, Team, Analytics Lab and Data Health pages | Implemented and functional |
| Contract import and Contract Explorer | Implemented and functional with a user-supplied file. The repository ships none; the local copy (MrBridge dataset, 2015-16 to 2026-27) is git-ignored. |
| Salary-cap rules by season | **Partially implemented:** rules are configured for 2024-25 to 2026-27 only. Earlier seasons need cited rules files. |
| Team Builder | Implemented and functional |
| Winning Benchmarks | Implemented, at team level. **Payroll history** is in the database but not yet in this research. |
| Player Value model | Implemented and functional (tested out of sample) |
| Roster Fit | Implemented as **description only**: the lab's own test found fit added no prediction beyond the sum of player impacts. |
| Roster Optimizer | Implemented and functional; needs the imported salaries. |
| Postseason Outlook | Implemented and functional (tested out of sample, with intervals) |
| Scenario Simulator | Implemented. **The rest of the league is not simulated** (no league-wide simulation). |
| AI Research assistant (A0-A9) | Implemented and functional when Ollama and the model are installed. Web search works only with the user's own Ollama key. Evaluation: 47-49 of 59 cases end to end (`docs/AI_EVALUATION.md`). |
| API, JWT sign-in, RAG, *Ask the Docs*, Docker Compose (C1-C7) | Implemented and functional |
| Sign-in for the whole workbench (C8) | Implemented and functional (2026-10-29) |
| Lineup tables (`lineups`, `lineup_stats`) | **Planned but not implemented** (deferred) |
| Roadmap version 8: trades, aging curves, draft value, multi-year planning | **Planned but not implemented:** listed in the roadmap; no milestone builds it. |

## 4. Course requirements assessment

| Requirement | What exists | Missing / to implement |
| --- | --- | --- |
| FastAPI, at least 3 endpoints | 16 endpoints, in `server/auth.py`, `rag.py`, `data.py` and `app.py`. | Nothing. |
| SQLAlchemy, at least 2 related tables | `api_users` 1→many `api_questions`: ORM, both directions, cascade delete. Also `custom_rosters` → `roster_players`. | Nothing. |
| Pydantic on every endpoint | 29 models in `server/schemas.py`: a request model for each body or form, a response model for every endpoint, typed path and query parameters. A test checks every endpoint's published schema. | Nothing. |
| JWT authentication | HS256 tokens with expiry; tests refuse altered, expired, other-key and deleted-user tokens. Since C8 the workbench asks for a sign-in before any page, against the same accounts (`tests/ui/test_sign_in.py`). | Nothing. |
| RAG with ChromaDB and Ollama | `pipelines/rag.py`, `storage/vectors.py`, `services/passages.py`, `assistant/rag.py`. | Nothing. Needs Ollama with `nomic-embed-text` and `qwen3:8b` (about 5.5 GB). |
| Streamlit frontend | 15 pages; *Ask the Docs* uses the API. | Nothing. |
| Docker Compose, whole app | One command starts Ollama, the model pull, the API and the workbench. | Nothing structural. **The NBA data** must already be built in `data/`: Compose fetches nothing, and a fresh clone has no data. |
| At least 5 passing tests | 4,259 collected; 268 are the capstone's, per `docs/CAPSTONE.md`. Result: see §2. | Nothing. |
| README: setup, diagram, usage | Prerequisites; step-by-step setup (clone, configure, build the data, `docker compose up`); two Mermaid diagrams; usage (signing in, ingesting the documents, asking); the endpoint table with method, path and auth required; tech stack; testing; design decisions; limitations; screenshots. | If submitted as PDF or slides, export the Mermaid diagrams as images. |
| requirements files | `requirements.txt` (runtime) and `requirements-dev.txt`, pinned; a test keeps them in step with `pyproject.toml`. | Nothing. |

`docs/CAPSTONE.md` maps each requirement to its files; it states all ten met.

## 5. Data sources and RAG opportunities

**Existing sources** (`docs/DATA_SOURCE_REGISTER.md`):

- **League data:** stats.nba.com through `nba_api` (public JSON, no key): statistics,
  games, standings, rosters, on/off splits.
- **Contracts:** a contract CSV the user supplies. In use: the MrBridge dataset of
  HoopsHype public salaries.
- **Cap rules:** salary-cap figures and roster rules transcribed by hand, with citations,
  into `configs/seasons/`.
- **For the assistant:**
  - the NBA transactions file and official injury-report PDFs;
  - Hoops Rumors RSS/Atom feeds;
  - optional Ollama web search;
  - links the user pastes.
- **Ruled out:** Basketball Reference (its terms), Spotrac (refuses automated requests),
  BALLDONTLIE (contracts are paid only).

**What RAG indexes now:** the lab's own documentation:

- the research write-ups for benchmarks, player value, roster fit, postseason and the
  simulator;
- 19 decision records, the architecture, the workbench guide, the audit and the
  contract-data guide.

**Further corpora already in the repository or its local cache** (not indexed for RAG
today):

- the metric glossary and data dictionary, excluded on purpose because their long tables
  crowd out prose;
- the cached news items and injury reports the assistant reads.

**Why retrieval helps:** questions such as "how is player value tested?" or "why is fit not
added to projections?" have their answers in prose that ships with the lab. Retrieval lets a
local model quote those passages with citations instead of answering from memory.

**Structured queries vs. document retrieval.** Numbers come from structured queries:

- the API's data endpoints and the assistant's typed tools query SQLite through the
  services, for a team's net rating or a player's estimated value with its interval;
- the AI Research assistant answers such questions through its typed tools.

RAG answers questions about **how and why**: method, definitions, decisions and limits.

## 6. Technical risks

1. **The local model's hardware and setup.** RAG and the assistant need Ollama running
   locally, a download of about 5.5 GB on first start, and in practice a GPU (`qwen3:8b`
   was chosen to fit an 8 GB card). On a grader's machine without one, answers are slow
   or fail.
   *Backup plans:*
   - Point `FOL_OLLAMA_HOST` at an Ollama the grader already runs.
   - Use the configured smaller fallback model (`qwen3:4b-instruct`).
   - Rely on the test suite, which passes without Ollama (fakes).
   - Bring a recorded demo or screenshots of *Ask the Docs*.
   - Swapping in an API-hosted LLM, which the brief allows, would be new work: it is not
     implemented.
2. **Data availability on a fresh machine.** `data/` is git-ignored. A fresh clone or
   `docker compose up` has no NBA database, so the data endpoints return 503 and the pages
   are empty until `fol refresh` runs. That makes about 650 requests to stats.nba.com,
   around 15 minutes, and that service can throttle. Contract data cannot be redistributed.
   *Backup plans:*
   - Demo on the machine that holds the built database.
   - Keep a copy of the raw store, so `fol build` rebuilds offline in one to two minutes.
   - Show that the RAG and sign-in path works with no NBA data at all: it indexes only
     `docs/`.
   - The tests use synthetic fixtures, so they need no built data.

## 7. Relevant files

- `README.md` (setup, architecture diagrams, usage)
- `docs/CAPSTONE.md` (requirement map)
- `docs/ROADMAP.md`
- `docs/decisions/0019-capstone-api.md`
- `docs/ARCHITECTURE.md`
- `docs/DATA_SOURCE_REGISTER.md`
- `docs/DATA_DICTIONARY.md`
- `docs/AI_EVALUATION.md`
- `docs/AUDIT.md`
- `src/front_office/server/`: `app.py`, `auth.py`, `security.py` (JWT), `schemas.py`
  (Pydantic), `rag.py`, `data.py`
- `src/front_office/storage/accounts.py` (ORM tables), `storage/vectors.py` (ChromaDB),
  `storage/schema.py`
- `src/front_office/pipelines/rag.py`, `assistant/rag.py`, `services/passages.py`,
  `config/documents.py`
- `apps/workbench/app.py`, `apps/workbench/wb/views/docs.py`, `wb/api_client.py`
- `compose.yaml`, `compose.gpu.yaml`, `Dockerfile`
- `requirements.txt`, `requirements-dev.txt`, `pyproject.toml`
- `configs/api.yaml`, `configs/assistant.yaml`, `configs/models/`, `configs/seasons/`
- `tests/unit/server/`, `tests/unit/test_docker.py`, `tests/unit/test_requirements.py`,
  `tests/ui/test_docs_page.py`, `tests/architecture/`
