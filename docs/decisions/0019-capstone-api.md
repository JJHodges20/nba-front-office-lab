# 0019 - The capstone: an HTTP API with sign-in, a vector index of the documents, Docker

Date: 2026-10-15. Status: accepted. Follows [0008](0008-workbench.md) and
[0018](0018-ai-research-assistant.md).

## Context

The owner is using the lab as the capstone of a course whose brief requires every one of
these: a FastAPI backend with at least three endpoints; a SQLAlchemy database with at least
two related tables; Pydantic validation on every endpoint; JWT authentication; a RAG
pipeline (ChromaDB with Ollama or a hosted model); a Streamlit frontend; Docker Compose
running the whole app with one command; at least five passing tests; a README with setup
instructions, an architecture diagram and a usage guide; and a `requirements.txt`.

Before this decision the lab met four of them. Its tables are built with SQLAlchemy from
the data contracts, with foreign keys between them (a roster and its players; a research
workspace and its questions, findings and proposals). The workbench is a Streamlit app. Its
suite held 3,986 tests. It has no HTTP interface, no accounts, no vector index - the AI
assistant searches the lab's documents by keyword, with SQLite's full-text search - no
container, and its dependencies were declared in `pyproject.toml` alone.

The owner decided four things on 2026-10-15: one new workbench page uses the API, the other
pages keep reading the lab directly; Ollama runs inside Compose, with a setting to use the
computer's own instead; Docker uses the owner's existing `data/` folder; and the work runs
milestone by milestone (C1 to C7), each committed when its gate passes, nothing pushed
without asking.

## Decision

1. **A new outer layer, `server`**: the FastAPI app. It imports `domain`, `config`,
   `pipelines`, `services` and the assistant's facade (`front_office.assistant.api`) alone,
   as the workbench does. It formats what services return into response models; it computes
   nothing, as no interface does. Every request and every response is a Pydantic model, so
   FastAPI validates both, and its OpenAPI page (`/docs`) documents them.
2. **Accounts are a fourth file**, `data/api/accounts.sqlite`: never the lab's database,
   never touched by a build, apart from the user's research. Two tables, related: a user,
   and the questions that user asked the documents - each question belongs to one user, and
   deleting a user deletes their questions. Their contracts are in `domain/tables`, like
   every stored table's; `storage` maps them with SQLAlchemy's ORM (a `relationship` each
   way), and remains the only layer that writes SQL. A password is kept as a bcrypt hash and
   never returned or logged.
3. **JWT sign-in.** `POST /auth/token` takes a name and a password (OAuth2's password form,
   so the `/docs` page's *Authorize* button works) and returns a signed token (HS256) that
   expires. Every endpoint but the health check, registration and sign-in needs it. The
   signing key is the user's own - `FOL_API_SECRET`, from the environment or the git-ignored
   `.env`, never in `.env.example` - and when none is set the API makes one, keeps it in the
   data folder beside the accounts, and never prints it.
4. **RAG beside the keyword search, not instead of it.** The lab's documents - the same
   sections `research_docs` reads, the same files left out - are cut into passages, embedded
   by a local Ollama embedding model (`nomic-embed-text`) and kept in a ChromaDB collection
   in the data folder. A question is embedded the same way; the nearest passages are handed
   to the local chat model as quoted data, and the answer cites them by number, with each
   source's file and heading. The AI Research assistant keeps its tested keyword search: its
   evaluation cases are frozen, and swapping its retrieval would reopen every one.
5. **Ollama in a container.** Inside Compose, Ollama is the service `ollama`, not
   `127.0.0.1`. The rule that the model runs on this machine (0018) is widened by exactly
   two names: `ollama`, this app's own container, and `host.docker.internal`, Docker's name
   for the computer it runs on - and the provider refuses either unless every address it
   resolves to is private. Every other address is refused as before: a LAN address is still
   another machine. `FOL_OLLAMA_HOST` sets the address from outside, as Compose does.
6. **One workbench module may call the lab's own API.** The workbench reaches the network
   through nothing (A9). The new page signs in and asks the documents over HTTP, through
   `wb/api_client.py` alone, at the address `FOL_API_URL` names - never a URL from the page
   or the model. The architecture test names that module as the one exception.
7. **Docker Compose**: one image for the API and the workbench, a service for each, and
   Ollama with a one-time step that pulls its models. The owner's `data/` folder is mounted;
   ports are published on this machine only, as the workbench has always listened.
8. **`requirements.txt` pins what the suite runs against**, generated from `pyproject.toml`'s
   declarations; a test keeps the two in step.

## Consequences

- The lab has a second interface that can change the user's data - accounts and their
  questions - so the same rules hold for it as for the workbench: validation at the edge,
  SQL only in `storage`, nothing fitted or built by a request.
- A vector index is stored state that can go stale: it records the embedding model and a
  fingerprint of each passage, and is rebuilt when either changes.
- The two widened rules are tested: the Ollama names (accepted, and refused when they
  resolve to a public address) and the workbench's one network module.

## Settled while building C2 (2026-10-15)

- **Endpoints**: `GET /health` (public), `POST /auth/register` (public, 201 or 409 for a
  name taken), `POST /auth/token` (public, OAuth2's password form), `GET /auth/me`, and
  `DELETE /auth/me`, which deletes the account and every question it asked: what can be
  made through the API can be removed through it.
- **Names and passwords.** A name is 3 to 32 letters, digits, dots, hyphens or underscores,
  kept and compared in lower case. A password is 8 characters at least and 72 bytes at most:
  bcrypt reads no further, and from version 5 refuses a longer one rather than cutting it.
  The rules are the domain's (`domain/accounts.py`); the request model and the service both
  read them. A wrong password, a name nobody has and a password too long to be anyone's all
  get the same 401, and an unknown name still checks a hash, so the time a refusal takes
  does not say which names exist.
- **The ORM maps the contracts' tables.** `storage/accounts.py` builds the two tables from
  their contracts, as every store does, and maps a declarative class onto each
  (`__table__`), so the columns stay the contract's; the classes add the relationship each
  way. The contracts have no notion of a unique column, so the store adds the unique index on
  the name itself - two registrations of one name at the same moment cannot both succeed.
  Ids are never reused (SQLite's `AUTOINCREMENT`): a token names its user by id, and a new
  user given a deleted user's id would be signed in by the old token.
- **The key** must be at least 32 bytes (RFC 7518; PyJWT warns below it, and warnings are
  errors in the suite). A key the API makes is 64 random characters, written only if no file
  is there yet, so two servers starting at once keep one key.
- **`configs/api.yaml`** holds what may change - how long a token lasts (60 minutes) and
  bcrypt's cost (12) - and refuses an unknown field, so a key cannot be put there.
- **The accounts file is not versioned yet.** The first change to its contracts adds a
  version table, the way the research store has one.
- **`server` loads settings**, like `interfaces`: `create_app()` with no arguments is what
  uvicorn's `--factory` calls. `fol api` starts it on `127.0.0.1:8000`.
- **FastAPI 0.143 includes a router lazily**, so the tests that every endpoint has its
  models and its sign-in read the published OpenAPI schema - what a client sees - rather than
  the app's route list.
