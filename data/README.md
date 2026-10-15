# data/

Local data. Nothing in this directory except this file is committed.

| Path | Contents |
| --- | --- |
| `raw/` | Immutable, timestamped snapshots of what each provider returned. The database can be rebuilt from these. |
| `front_office.sqlite` | The database. |
| `imports/` | Files supplied by hand, such as contract exports, and the contract template. |
| `current.sqlite` | Current information the AI Research assistant fetched since the build: games, transactions, the injury report, news. |
| `assistant/` | Your research with the assistant (`assistant.sqlite`), and copies made before each upgrade of it (`backups/`). |
| `api/` | The HTTP API's accounts (`accounts.sqlite`) and, unless `FOL_API_SECRET` is set, the key that signs its tokens (`signing.key`). Keep the key to yourself. |

Set the `FOL_DATA_DIR` environment variable to keep data somewhere else.
