# data/

Local data. Nothing in this directory except this file is committed.

| Path | Contents |
| --- | --- |
| `raw/` | Immutable, timestamped snapshots of what each provider returned. The database can be rebuilt from these. |
| `front_office.sqlite` | The database. |
| `imports/` | Files supplied by hand, such as contract exports, and the contract template. |

Set the `FOL_DATA_DIR` environment variable to keep data somewhere else.
