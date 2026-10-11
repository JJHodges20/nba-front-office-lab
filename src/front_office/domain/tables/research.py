"""Data contracts for the user's research with the AI assistant (decision 0018, A6).

Kept in ``data/assistant/assistant.sqlite``, apart from the lab's database and the current
cache: a build never touches it, and nothing in it is league data. A workspace holds the
questions the user asked and the answers they got, the findings they bookmarked, the
rosters the assistant proposed and what the user did with each. It is all the user's own
work: deleting a workspace deletes what it holds and nothing else - a roster saved from a
proposal lives on in the Team Builder.

The file is versioned: ``research_schema`` records each version applied, and the store
copies the file aside before it moves it to a newer one.
"""

from __future__ import annotations

from front_office.domain.schema import DType, Field, Provenance, TableContract

_ID = Provenance.IDENTIFIER
_USER = Provenance.ASSUMPTION
_OPS = Provenance.OPERATIONAL
_KEPT = "Kept in data/assistant/assistant.sqlite, not the lab's database."

SEASON_TYPES = ("regular", "playoffs")
MODES = ("quick", "deep")
OUTCOMES = ("supported", "qualified", "insufficient", "clarify", "declined")
PROPOSAL_STATUSES = ("draft", "saved", "declined")
APPROVAL_ACTIONS = ("saved", "already_saved", "refused", "declined")
WORKSPACE = "research_workspaces.workspace_id"


def _moment(name: str, description: str, *, nullable: bool = False) -> Field:
    return Field(name, DType.DATETIME, description, nullable=nullable, provenance=_OPS)


def _focus(what: str) -> tuple[Field, ...]:
    """The season, team, player and roster a question is about, or a workspace looks at."""
    return (
        Field("season", DType.STRING, f"Season {what}.", provenance=_USER),
        Field(
            "season_type",
            DType.STRING,
            f"Regular season or playoffs, {what}.",
            provenance=_USER,
            allowed=SEASON_TYPES,
        ),
        Field("team_id", DType.INTEGER, f"Team {what}, by the league's id.", provenance=_ID),
        Field("player_id", DType.INTEGER, f"Player {what}, by the league's id.", provenance=_ID),
        Field("roster_id", DType.INTEGER, f"Team Builder roster {what}.", provenance=_ID),
    )


RESEARCH_SCHEMA = TableContract(
    name="research_schema",
    domain="research",
    description=f"Each version of the research store's tables applied to the file. {_KEPT}",
    grain="One row per version applied.",
    fields=(
        Field(
            "version",
            DType.INTEGER,
            "Version number.",
            nullable=False,
            provenance=_OPS,
            minimum=1,
        ),
        Field("note", DType.STRING, "What the version added.", nullable=False, provenance=_OPS),
        _moment("applied_at", "When it was applied to this file."),
    ),
    primary_key=("version",),
    introduced_in="A6",
)

RESEARCH_WORKSPACES = TableContract(
    name="research_workspaces",
    domain="research",
    description=(
        "Named research workspaces: what the user is working on, their notes, and the season, "
        f"team, player or roster the workspace looks at. {_KEPT}"
    ),
    grain="One row per workspace.",
    fields=(
        Field(
            "workspace_id",
            DType.INTEGER,
            "Workspace id, assigned when it is created.",
            nullable=False,
            provenance=_ID,
        ),
        Field("name", DType.STRING, "Name the user gave it.", nullable=False, provenance=_USER),
        Field(
            "goal", DType.STRING, "What the user is working on, in their words.", provenance=_USER
        ),
        Field(
            "notes",
            DType.STRING,
            "The user's notes, and summaries of earlier questions the assistant wrote at the "
            "user's request - prior choices and summaries, not evidence.",
            provenance=_USER,
        ),
        *_focus("the workspace looks at, when a question names none"),
        Field(
            "conversation",
            DType.INTEGER,
            "The conversation under way: earlier turns of it are what a follow-up reads.",
            nullable=False,
            provenance=_OPS,
            minimum=1,
        ),
        Field(
            "archived",
            DType.BOOLEAN,
            "Whether the user put it away.",
            nullable=False,
            provenance=_USER,
        ),
        _moment("created_at", "When it was created."),
        _moment("updated_at", "When it, or anything in it, last changed."),
    ),
    primary_key=("workspace_id",),
    introduced_in="A6",
)

RESEARCH_TURNS = TableContract(
    name="research_turns",
    domain="research",
    description=(
        "Each question asked in a workspace and the answer it got, kept as it was: the data "
        f"build and model files it used are recorded, and nothing rewrites it. {_KEPT}"
    ),
    grain="One row per question.",
    fields=(
        Field("turn_id", DType.INTEGER, "Turn id.", nullable=False, provenance=_ID),
        Field(
            "workspace_id",
            DType.INTEGER,
            "Workspace it was asked in.",
            nullable=False,
            provenance=_ID,
            references=WORKSPACE,
        ),
        Field(
            "conversation",
            DType.INTEGER,
            "Conversation within the workspace.",
            nullable=False,
            provenance=_OPS,
            minimum=1,
        ),
        _moment("asked_at", "When it was asked."),
        Field(
            "question", DType.STRING, "The question as written.", nullable=False, provenance=_USER
        ),
        Field(
            "mode",
            DType.STRING,
            "Quick or Deep.",
            nullable=False,
            provenance=_USER,
            allowed=MODES,
        ),
        *_focus("the question was asked about"),
        Field(
            "asked_from",
            DType.STRING,
            "The page it was asked from.",
            nullable=False,
            provenance=_OPS,
        ),
        Field(
            "about",
            DType.STRING,
            "What the page was showing, in words, when asked from another page.",
            provenance=_OPS,
        ),
        Field(
            "outcome",
            DType.STRING,
            "What kind of answer it got; empty when none came back.",
            provenance=_OPS,
            allowed=OUTCOMES,
        ),
        Field("answer_text", DType.STRING, "The answer as shown.", provenance=_OPS),
        Field("error", DType.STRING, "Why no answer came back.", provenance=_OPS),
        Field("build_id", DType.INTEGER, "The lab's data build it read.", provenance=_OPS),
        Field(
            "value_model",
            DType.STRING,
            "The player value model revision the build applied.",
            provenance=_OPS,
        ),
        Field("model", DType.STRING, "The local language model that answered.", provenance=_OPS),
        Field("policy", DType.STRING, "The version of the assistant's rules.", provenance=_OPS),
        Field(
            "seconds",
            DType.FLOAT,
            "How long the answer took.",
            provenance=_OPS,
            unit="seconds",
            minimum=0,
        ),
        Field(
            "payload",
            DType.STRING,
            "Everything the page draws, as JSON: the results, their rows and charts, the "
            "evidence, the notes, the steps.",
            nullable=False,
            provenance=_OPS,
        ),
    ),
    primary_key=("turn_id",),
    indexes=(("workspace_id", "conversation"),),
    introduced_in="A6",
)

RESEARCH_FINDINGS = TableContract(
    name="research_findings",
    domain="research",
    description=(
        "Answers the user bookmarked, each a copy of what it said and rested on, so that it "
        f"outlasts the history it came from. {_KEPT}"
    ),
    grain="One row per bookmark.",
    fields=(
        Field("finding_id", DType.INTEGER, "Finding id.", nullable=False, provenance=_ID),
        Field(
            "workspace_id",
            DType.INTEGER,
            "Workspace it belongs to.",
            nullable=False,
            provenance=_ID,
            references=WORKSPACE,
        ),
        Field(
            "turn_id",
            DType.INTEGER,
            "The turn it was saved from, while that turn is kept.",
            provenance=_ID,
        ),
        Field("title", DType.STRING, "Title the user gave it.", nullable=False, provenance=_USER),
        Field("note", DType.STRING, "The user's note on it.", provenance=_USER),
        Field("question", DType.STRING, "The question.", nullable=False, provenance=_USER),
        Field("answer_text", DType.STRING, "The answer, as shown.", provenance=_OPS),
        Field(
            "evidence",
            DType.STRING,
            "What the answer rested on, one source a line, with its dates.",
            provenance=_OPS,
        ),
        _moment("asked_at", "When the question was asked."),
        Field("build_id", DType.INTEGER, "The data build the answer read.", provenance=_OPS),
        _moment("created_at", "When it was bookmarked."),
    ),
    primary_key=("finding_id",),
    indexes=(("workspace_id",),),
    introduced_in="A6",
)

RESEARCH_PROPOSALS = TableContract(
    name="research_proposals",
    domain="research",
    description=(
        "Rosters the assistant proposed in a workspace, kept until the user saves or declines "
        f"each. {_KEPT}"
    ),
    grain="One row per proposal in a workspace, named by its fingerprint.",
    fields=(
        Field(
            "workspace_id",
            DType.INTEGER,
            "Workspace it was proposed in.",
            nullable=False,
            provenance=_ID,
            references=WORKSPACE,
        ),
        Field(
            "fingerprint",
            DType.STRING,
            "The proposal's fingerprint: everything in it, hashed.",
            nullable=False,
            provenance=_ID,
        ),
        Field("turn_id", DType.INTEGER, "The turn that proposed it, while kept.", provenance=_ID),
        Field("label", DType.STRING, "Option A, Option B...", nullable=False, provenance=_OPS),
        Field(
            "payroll_season",
            DType.STRING,
            "Season it is priced for.",
            nullable=False,
            provenance=_OPS,
        ),
        Field(
            "status",
            DType.STRING,
            "Waiting for the user, saved as a roster, or declined.",
            nullable=False,
            provenance=_USER,
            allowed=PROPOSAL_STATUSES,
        ),
        Field(
            "roster_id", DType.INTEGER, "The Team Builder roster it was saved as.", provenance=_ID
        ),
        Field(
            "payload",
            DType.STRING,
            "The proposal as the page shows it, as JSON.",
            nullable=False,
            provenance=_OPS,
        ),
        _moment("created_at", "When it was proposed."),
        _moment("decided_at", "When the user saved or declined it.", nullable=True),
    ),
    primary_key=("workspace_id", "fingerprint"),
    introduced_in="A6",
)

RESEARCH_APPROVALS = TableContract(
    name="research_approvals",
    domain="research",
    description=(
        "Every press of a proposal's save or decline button and what came of it: saved, "
        f"found saved already, refused because something had changed, or declined. {_KEPT}"
    ),
    grain="One row per press.",
    fields=(
        Field("approval_id", DType.INTEGER, "Approval id.", nullable=False, provenance=_ID),
        Field(
            "workspace_id",
            DType.INTEGER,
            "Workspace the proposal belongs to.",
            nullable=False,
            provenance=_ID,
            references=WORKSPACE,
        ),
        Field(
            "fingerprint",
            DType.STRING,
            "The proposal's fingerprint.",
            nullable=False,
            provenance=_ID,
        ),
        Field(
            "action",
            DType.STRING,
            "What came of it.",
            nullable=False,
            provenance=_OPS,
            allowed=APPROVAL_ACTIONS,
        ),
        Field("roster_id", DType.INTEGER, "The roster it saved or found.", provenance=_ID),
        Field("detail", DType.STRING, "Why it was refused, in plain sentences.", provenance=_OPS),
        _moment("at", "When the button was pressed."),
    ),
    primary_key=("approval_id",),
    indexes=(("workspace_id", "fingerprint"),),
    introduced_in="A6",
)

TABLES: tuple[TableContract, ...] = (
    RESEARCH_SCHEMA,
    RESEARCH_WORKSPACES,
    RESEARCH_TURNS,
    RESEARCH_FINDINGS,
    RESEARCH_PROPOSALS,
    RESEARCH_APPROVALS,
)
