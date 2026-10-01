# 0001 - Layered architecture enforced by tests

Date: 2026-10-01. Status: accepted.

## Context

The roadmap asks for clear architectural boundaries so ingestion, analytics,
optimisation, modeling and the UI can evolve independently, and its completion gate
requires that no milestone weakens an unrelated boundary. Fourteen milestones is long
enough for a convention to erode unnoticed.

## Decision

Each architectural layer is a sub-package of `front_office` with an explicit list of the
layers it may import. `tests/architecture/test_layer_boundaries.py` parses every source
file and fails on a forbidden import. The same test confines key third-party libraries to
one layer each and rejects cap-sized dollar literals in source code.

Lower layers (`providers`, `rawstore`, `processing`, `storage`, `quality`, `analytics`)
depend only on `domain` and receive everything else as arguments. Only `pipelines`,
`services` and `interfaces` read configuration.

## Consequences

- A boundary can only be relaxed deliberately, by editing the rule, the architecture
  document and this record together.
- Lower layers are testable with plain values: no settings object, no database, no
  network.
- Some plumbing lives in `pipelines` and `services` that would otherwise be reached for
  directly. That is the intended cost.
