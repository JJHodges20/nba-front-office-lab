# 0020 - Sign-in for the whole workbench

Date: 2026-10-29. Status: accepted. Follows [0019](0019-capstone-api.md) and
[0008](0008-workbench.md).

## Context

After the capstone (decision 0019), the API asked for a signed-in token on every endpoint but
`/health`, `/auth/register` and `/auth/token`. The workbench did not ask for anything.

- Only *Ask the Docs* signed in, and it did so to reach the API.
- The other fourteen pages read the lab directly, on a server that listens on this machine
  alone.

On 2026-10-29 the owner asked for a sign-in "at every level": you have to log in no matter
what.

## Decision

1. **Nothing of the workbench is drawn without a sign-in.**
   - The frame (`apps/workbench/app.py`) checks the session before anything else: before the
     data status, the menus, the filters or any page.
   - Signed out, the sign-in page is all there is, and no data is read.
   - The sign-in page answers at every page's address. A typed or bookmarked address opens
     it, rather than Streamlit's "Page not found", and once signed in that address opens the
     page it names.
2. **One set of accounts: the API's.**
   - The workbench signs in against `data/api/accounts.sqlite`, through the account service
     (`services.accounts.project_accounts`), with the same rules for a name and a password and
     the same bcrypt hashes.
   - It works whether or not the API is running: the workbench may import services
     (`docs/ARCHITECTURE.md`), and the account service is one.
   - A user registered on either signs in on both.
3. **A sign-in lasts as long as one of the API's tokens**: `sign_in.token_minutes` in
   `configs/api.yaml`, 60 minutes. Every run checks two things:
   - that the sign-in has not run out;
   - that the account still exists (deleted from *Ask the Docs* or through the API).

   Either one failing signs the session out, with a word on the sign-in page.
4. **One sign-in serves *Ask the Docs* too.** When the API answers at sign-in, the same name
   and password sign in to it, and the page opens signed in. When it does not answer, the page
   asks for them itself, as before.
5. **Signing out forgets the whole session.**
   - This holds from the sidebar, or from *Ask the Docs*' own button, which now signs out of
     everything; deleting the account there does the same.
   - Whoever signs in next starts with nothing of the last person's filters or choices.
6. **Who is signed in sits in the sidebar**, with *Sign out*, above the data status. *All
   pages* stays the sidebar's foot (UI polish P8, the owner's decision D13).

## Consequences

- **What is guarded, and what is not:**
  - Every workbench page and every API endpoint now needs a sign-in.
  - Three things do not, by design:
    - the API's `/health`, which Docker's health check calls;
    - registering and signing in themselves;
    - the API's own documentation pages, `/docs` and `/openapi.json`. These describe the
      endpoints and are where *Authorize* signs in.
  - The `fol` command line is the machine owner's tool and asks for no sign-in.
- **Anyone who reaches the sign-in page may register**, as with the API. Both listen on this
  machine only (and, in Docker, are published on 127.0.0.1 only). Accounts made only by the
  owner, say with a `fol` command, would be a later decision.
- **A sign-in keeps each person's questions to the documents theirs** (as before). It does
  not divide the lab: rosters, research workspaces and the data are the project's, shared by
  everyone who signs in.
- **A new browser tab, or a typed address, is a new session**, so it signs in again. This is
  how Streamlit keeps a session, and it is the safe default; nothing is kept in a cookie.
- **Tests.** The whole-workbench tests (`tests/ui/conftest.py`, `app`) open signed in to a
  stand-in for the accounts that writes nothing, because the built test projects are shared
  and read-only. `tests/ui/test_sign_in.py` signs in for real on private copies:
  - register, sign in, a wrong password, the rules for a name and a password, a name taken;
  - sign out, a sign-in that has run out, a deleted account;
  - the API signed in at the same time.
- **Docker** needs no change. The workbench and the API share the mounted data folder, so they
  read one accounts file.
