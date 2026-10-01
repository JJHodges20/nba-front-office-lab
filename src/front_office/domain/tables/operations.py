"""Data contracts for the lab's own bookkeeping.

These tables describe the data rather than the league: what was fetched and when, how
the last build went, which checks passed. The Data Health page reads nothing else.
"""

from __future__ import annotations

from front_office.domain.schema import DType, Field, Provenance, TableContract

_OPS = Provenance.OPERATIONAL

FETCH_STATUSES = ("stored", "unchanged", "failed")
BUILD_STATUSES = ("ok", "problems")
ISSUE_SEVERITIES = ("error", "note")
CHECK_SEVERITIES = ("error", "warning")


def _text(name: str, description: str, *, nullable: bool = False, **extra: object) -> Field:
    return Field(name, DType.STRING, description, nullable=nullable, provenance=_OPS, **extra)


def _number(name: str, description: str, *, nullable: bool = False) -> Field:
    return Field(name, DType.INTEGER, description, nullable=nullable, provenance=_OPS, minimum=0)


def _moment(name: str, description: str, *, nullable: bool = False) -> Field:
    return Field(name, DType.DATETIME, description, nullable=nullable, provenance=_OPS)


FETCH_LOG = TableContract(
    name="fetch_log",
    domain="operations",
    description="Every attempt to fetch a dataset from a source, successful or not.",
    grain="One row per fetch attempt.",
    fields=(
        _number("fetch_id", "Attempt id, assigned when recorded."),
        _text("source", "Source the dataset comes from."),
        _text("dataset", "Dataset requested."),
        _text("partition_key", "Which slice of the dataset: season, season type, team."),
        _text("season", "Season requested, if the dataset is seasonal.", nullable=True),
        _text("status", "What happened.", allowed=FETCH_STATUSES),
        _number("rows", "Rows returned.", nullable=True),
        _text("error", "Why the attempt failed.", nullable=True),
        _moment("started_at", "When the attempt began."),
        _moment("finished_at", "When the attempt ended."),
    ),
    primary_key=("fetch_id",),
    indexes=(("source", "dataset"), ("finished_at",)),
)

BUILDS = TableContract(
    name="builds",
    domain="operations",
    description="Every rebuild of the database from the raw store.",
    grain="One row per build.",
    fields=(
        _number("build_id", "Build id, assigned when recorded."),
        _moment("started_at", "When the build began."),
        _moment("finished_at", "When the build ended."),
        _text("lab_version", "Version of the lab that ran the build."),
        _text("schema_fingerprint", "Fingerprint of the table contracts the build used."),
        _text("status", "Whether the build was clean.", allowed=BUILD_STATUSES),
        _number("rows_loaded", "Rows written across all tables."),
        _number("build_errors", "Table parts that could not be built."),
        _number("build_notes", "Adjustments made to source data."),
        _number("check_errors", "Quality checks that found a contradiction."),
        _number("check_warnings", "Quality checks that raised a warning."),
    ),
    primary_key=("build_id",),
)

BUILD_ISSUES = TableContract(
    name="build_issues",
    domain="operations",
    description="What the most recent build could not build, or had to adjust.",
    grain="One row per issue from the most recent build.",
    fields=(
        _number("issue_number", "Position of the issue in the build's report."),
        _text("table_name", "Table the issue concerns."),
        _text("scope", "Season the issue belongs to, or 'all seasons'."),
        _text(
            "severity",
            "Error: data is missing. Note: source data was adjusted.",
            allowed=ISSUE_SEVERITIES,
        ),
        _text("message", "What happened."),
    ),
    primary_key=("issue_number",),
)

CHECK_RESULTS = TableContract(
    name="check_results",
    domain="operations",
    description="The outcome of every data-quality check in the most recent build.",
    grain="One row per check.",
    fields=(
        _text("check_name", "Check name: table and rule."),
        _text("table_name", "Table the check concerns."),
        _text("description", "What the check requires."),
        _text("severity", "What a failure means.", allowed=CHECK_SEVERITIES),
        _number("examined", "Items examined."),
        _number("failures", "Items that failed."),
        Field("passed", DType.BOOLEAN, "Whether nothing failed.", nullable=False, provenance=_OPS),
        _text("examples", "A few failing items, one per line.", nullable=True),
    ),
    primary_key=("check_name",),
)

RAW_SNAPSHOTS = TableContract(
    name="raw_snapshots",
    domain="operations",
    description="The newest raw snapshot of every dataset slice, as of the most recent build.",
    grain="One row per dataset slice.",
    fields=(
        _text("source", "Source the dataset comes from."),
        _text("dataset", "Dataset."),
        _text("partition_key", "Which slice of the dataset: season, season type, team."),
        _text("season", "Season, if the dataset is seasonal.", nullable=True),
        _moment("fetched_at", "When the newest snapshot was fetched."),
        _number("versions", "How many distinct snapshots of this slice are stored."),
    ),
    primary_key=("source", "dataset", "partition_key"),
    indexes=(("source", "dataset"),),
)

# Replaced by every build.
BUILD_STATE_TABLES: tuple[TableContract, ...] = (BUILD_ISSUES, CHECK_RESULTS, RAW_SNAPSHOTS)
# Appended to; never replaced.
HISTORY_TABLES: tuple[TableContract, ...] = (FETCH_LOG, BUILDS)
TABLES: tuple[TableContract, ...] = (*HISTORY_TABLES, *BUILD_STATE_TABLES)
