# Capstone: how the lab meets the brief

The NBA Front Office Lab is an AI-powered research workbench for building NBA rosters. For
the course capstone it gained an HTTP API with sign-in, a retrieval-augmented question
answering over its own documentation, and a Docker Compose setup; everything it already
did - the data pipeline, the fitted models, the fourteen-page workbench, the local AI
assistant - is unchanged. This page maps each requirement of the brief to where it is met
and how to check it. Why it is built this way: decision
[0019](decisions/0019-capstone-api.md).

**State:** milestone C2 of C7 (see the [roadmap](ROADMAP.md)). Each requirement below says
whether it is met, and from which milestone.

| # | Requirement | Where it is met | Status |
| --- | --- | --- | --- |
| 1 | FastAPI backend with at least 3 endpoints | `src/front_office/server/` (`fol api`, then `http://localhost:8000/docs`): `GET /health`, `POST /auth/register`, `POST /auth/token`, `GET /auth/me`, `DELETE /auth/me` | Met (C2); more in C3-C4 |
| 2 | SQLAlchemy database with at least 2 related tables | The API's users and the questions each asked (`api_questions.user_id` → `api_users`, deleted with their user), in `data/api/accounts.sqlite`, mapped with SQLAlchemy's ORM with a relationship each way (`storage/accounts.py`). The lab's own tables are built with SQLAlchemy from its data contracts too, with foreign keys: a saved roster and its players (`roster_players.roster_id` → `custom_rosters`), a research workspace and its questions (`research_turns.workspace_id` → `research_workspaces`) | Met (C2) |
| 3 | Pydantic validation on all endpoints | `server/schemas.py`: a model for every request and every response; `tests/unit/server/test_app.py` checks each endpoint in the published schema | Met for every endpoint so far (C2) |
| 4 | JWT authentication | `POST /auth/token` returns a signed token (HS256) that expires after an hour; every endpoint but the health check, registration and sign-in requires it. Tests: altered, unsigned, expired, wrongly issued, other-key and deleted-user tokens are refused | Met (C2) |
| 5 | RAG pipeline (ChromaDB + Ollama) | The lab's documents embedded by a local Ollama model into ChromaDB, retrieved for each question, answered by the local chat model with numbered sources | Planned (C3) |
| 6 | Streamlit frontend | `apps/workbench/` - fourteen pages; a new page signs in and asks through the API | Met; the new page planned (C5) |
| 7 | Docker Compose: the whole app with one command | `docker compose up` - the API, the workbench and Ollama | Planned (C6) |
| 8 | At least 5 passing tests | `tests/` - 4,090 at C2 (`pytest -n auto`), 99 of them for the API: `tests/unit/server/`, `tests/unit/storage/test_account_store.py`, `tests/unit/services/test_accounts.py` | Met |
| 9 | README: setup, architecture diagram, usage guide | [README.md](../README.md) | Setup and usage met; the diagram planned (C7) |
| 10 | `requirements.txt` | [requirements.txt](../requirements.txt) (runtime) and [requirements-dev.txt](../requirements-dev.txt) (tests), pinned as tested and kept in step with `pyproject.toml` by `tests/unit/test_requirements.py` | Met (C1) |
