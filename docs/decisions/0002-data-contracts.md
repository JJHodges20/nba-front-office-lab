# 0002 - Data contracts as the single definition of each table

Date: 2026-10-01. Status: accepted.

## Context

A table's shape is needed in three places: where normalised data is produced, where it
is stored, and where it is documented. Three hand-maintained definitions drift.

The roadmap also requires the interface to keep measured statistics, modeled estimates
and user assumptions clearly apart, which is only possible if that distinction is
recorded somewhere every screen can read.

## Decision

Each canonical table is declared once, as a `TableContract` in
`front_office/domain/tables/`. The contract carries column types, nullability, units,
allowed values, keys and a provenance tag per column.

- Processing must satisfy it: normalisers end with `conform_frame`, which raises on any
  violation.
- Storage builds database tables from it.
- The data dictionary is generated from it, and a test fails when the committed copy is
  stale.

Validation is strict. Text in a numeric column, numbers in a text column, non-ISO date
strings and empty strings used for "missing" are rejected, not repaired.

A small purpose-built validator was chosen over a schema library: the rules needed are
few, the provenance tag is specific to this project, and it keeps the domain layer free
of a heavy dependency.

## Consequences

- Changing a table means changing one definition and regenerating the dictionary.
- A normaliser cannot silently hand bad data to storage.
- Strictness costs a little explicit conversion code in each normaliser.
