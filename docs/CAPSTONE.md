# Capstone: how the lab meets the brief

The NBA Front Office Lab is an AI-powered research workbench for building NBA rosters. For
the course capstone it gained an HTTP API with sign-in, a retrieval-augmented question
answering over its own documentation, a workbench page that uses them, and a Docker Compose
setup; everything it already did - the data pipeline, the fitted models, the fourteen other
pages, the local AI assistant - is unchanged. This page maps each requirement of the brief
to where it is met and how to check it. Why it is built this way: decision
[0019](decisions/0019-capstone-api.md).

**State:** complete - all seven milestones, C1 to C7, and C8, the sign-in for the whole workbench (see the [roadmap](ROADMAP.md)). Every
requirement below is met, and says from which milestone.

**To check it in a few minutes**: `docker compose up --build` (or, by hand, `fol rag index`
then `fol api` and `fol ui`); open http://localhost:8000/docs, register, *Authorize*, and try
`POST /rag/ask`; open http://localhost:8501, *Ask* menu, *Ask the Docs*; and run
`pytest -n auto`.

| # | Requirement | Where it is met | Status |
| --- | --- | --- | --- |
| 1 | FastAPI backend with at least 3 endpoints | `src/front_office/server/` (`fol api`, then `http://localhost:8000/docs`): `GET /health`; sign-in - `POST /auth/register`, `POST /auth/token`, `GET` and `DELETE /auth/me`; the documents - `POST /rag/ask`, `GET /rag/questions`, `GET` and `DELETE /rag/questions/{id}`, `GET` and `POST /rag/index`; the lab's data - `GET /lab`, `GET /seasons/{season}/teams`, `GET /teams/{team_id}`, `GET /seasons/{season}/players`, `GET /players/{player_id}` | Met (C2-C4): 16 endpoints |
| 2 | SQLAlchemy database with at least 2 related tables | The API's users and the questions each asked (`api_questions.user_id` → `api_users`, deleted with their user), in `data/api/accounts.sqlite`, mapped with SQLAlchemy's ORM with a relationship each way (`storage/accounts.py`). The lab's own tables are built with SQLAlchemy from its data contracts too, with foreign keys: a saved roster and its players (`roster_players.roster_id` → `custom_rosters`), a research workspace and its questions (`research_turns.workspace_id` → `research_workspaces`) | Met (C2) |
| 3 | Pydantic validation on all endpoints | `server/schemas.py`: a model for every request and every response; `tests/unit/server/test_app.py` checks each endpoint in the published schema | Met (C2-C4): all 16 endpoints |
| 4 | JWT authentication | `POST /auth/token` returns a signed token (HS256) that expires after an hour; every endpoint but the health check, registration and sign-in requires it. Tests: altered, unsigned, expired, wrongly issued, other-key and deleted-user tokens are refused. Since C8 the workbench asks for a sign-in too, before any page, against the same accounts ([decision 0020](decisions/0020-workbench-sign-in.md), `tests/ui/test_sign_in.py`) | Met (C2; the whole workbench, C8) |
| 5 | RAG pipeline (ChromaDB + Ollama) | The lab's documents (`docs/`) cut into passages and embedded by a local Ollama model (`nomic-embed-text`) into ChromaDB (`data/rag/`: `fol rag index` or `POST /rag/index`); for each question (`POST /rag/ask`) the nearest five passages are retrieved and the local chat model (`qwen3:8b`) answers from them alone, citing each by number; the lab's checker cuts a figure no passage holds. Code: `pipelines/rag.py`, `storage/vectors.py`, `services/passages.py`, `assistant/rag.py` | Met (C3) |
| 6 | Streamlit frontend | `apps/workbench/` (`fol ui`): fifteen pages. *Ask the Docs* (`wb/views/docs.py`, in the *Ask* menu) is the API's: it registers and signs in, builds the index, asks the documents and shows each answer with its sources, and lists and deletes the user's questions - over HTTP with the token, through `wb/api_client.py` | Met (C5) |
| 7 | Docker Compose: the whole app with one command | `docker compose up --build` (`compose.yaml`, `Dockerfile`): Ollama, a one-time pull of the two models, the API (which indexes the documents first) and the workbench, at http://localhost:8501 and http://localhost:8000/docs. Run live on 2026-10-15: up in about four minutes from nothing, every check of the Ask the Docs page passed against it | Met (C6) |
| 8 | At least 5 passing tests | `tests/` - 4,259 at C7 (`pytest -n auto`), 4,272 at C8 (`pytest -n 6`); 268 of them for the capstone: `tests/unit/server/`, the account and vector stores, the account and passage services, the RAG pipeline and answer, the page and its client in `tests/ui/`, and the Docker files (`tests/unit/test_docker.py`) | Met |
| 9 | README: setup, architecture diagram, usage guide | [README.md](../README.md): *Setup* (by hand, and *With Docker*); *Architecture*, with two Mermaid diagrams - the system, and a question to the documents step by step; and the usage guide - the workbench's pages, *The API and Ask the Docs* with every endpoint and PowerShell and curl examples tried against the running API, other commands, and what to do when something goes wrong | Met (C7) |
| 10 | `requirements.txt` | [requirements.txt](../requirements.txt) (runtime) and [requirements-dev.txt](../requirements-dev.txt) (tests), pinned as tested and kept in step with `pyproject.toml` by `tests/unit/test_requirements.py` | Met (C1) |
