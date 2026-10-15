# Capstone: how the lab meets the brief

The NBA Front Office Lab is an AI-powered research workbench for building NBA rosters. For
the course capstone it gained an HTTP API with sign-in, a retrieval-augmented question
answering over its own documentation, and a Docker Compose setup; everything it already
did - the data pipeline, the fitted models, the fourteen-page workbench, the local AI
assistant - is unchanged. This page maps each requirement of the brief to where it is met
and how to check it. Why it is built this way: decision
[0019](decisions/0019-capstone-api.md).

**State:** milestone C1 of C7 (see the [roadmap](ROADMAP.md)). Each requirement below says
whether it is met, and from which milestone.

| # | Requirement | Where it is met | Status |
| --- | --- | --- | --- |
| 1 | FastAPI backend with at least 3 endpoints | `src/front_office/server/` | Planned (C2-C4) |
| 2 | SQLAlchemy database with at least 2 related tables | The lab's tables are built with SQLAlchemy from its data contracts, with foreign keys: a saved roster and its players (`roster_players.roster_id` → `custom_rosters`), a research workspace and its questions (`research_turns.workspace_id` → `research_workspaces`). The API adds users and their questions, mapped with SQLAlchemy's ORM | Met; the API's tables planned (C2) |
| 3 | Pydantic validation on all endpoints | Request and response models on every endpoint | Planned (C2-C4) |
| 4 | JWT authentication | Sign-in returns a signed, expiring token that every other endpoint requires | Planned (C2) |
| 5 | RAG pipeline (ChromaDB + Ollama) | The lab's documents embedded by a local Ollama model into ChromaDB, retrieved for each question, answered by the local chat model with numbered sources | Planned (C3) |
| 6 | Streamlit frontend | `apps/workbench/` - fourteen pages; a new page signs in and asks through the API | Met; the new page planned (C5) |
| 7 | Docker Compose: the whole app with one command | `docker compose up` - the API, the workbench and Ollama | Planned (C6) |
| 8 | At least 5 passing tests | `tests/` - 3,991 at C1 (`pytest -n auto`) | Met |
| 9 | README: setup, architecture diagram, usage guide | [README.md](../README.md) | Setup and usage met; the diagram planned (C7) |
| 10 | `requirements.txt` | [requirements.txt](../requirements.txt) (runtime) and [requirements-dev.txt](../requirements-dev.txt) (tests), pinned as tested and kept in step with `pyproject.toml` by `tests/unit/test_requirements.py` | Met (C1) |
