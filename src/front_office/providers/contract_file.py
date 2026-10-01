"""Contract-file adapter.

No free source of NBA contract data permits automated collection for this kind of use
(see ``docs/DATA_SOURCE_REGISTER.md``), so contract data comes from a file the user
supplies. This adapter reads that file and returns its text unchanged as a snapshot,
together with what the user says about where the figures came from and when they were
current. Parsing is the processing layer's job.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path

from front_office.domain.datasets import CONTRACT_FILE, CONTRACT_FILE_DATASET
from front_office.domain.snapshots import Snapshot
from front_office.providers.nba_stats import ProviderError

MAX_FILE_BYTES = 20 * 1024 * 1024
"""A contract file is a few hundred rows; anything this large is the wrong file."""


def read_contract_file(
    path: Path,
    *,
    source_label: str,
    as_of: date,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> Snapshot:
    """Read a contract file into a snapshot.

    ``source_label`` records where the figures came from and ``as_of`` the date they
    were current; both are the user's statement and are stored with the data.
    """
    label = source_label.strip()
    if not label:
        raise ProviderError("say where the contract figures came from (source label is empty)")
    if not path.is_file():
        raise ProviderError(f"contract file not found: {path}")
    size = path.stat().st_size
    if size == 0:
        raise ProviderError(f"contract file is empty: {path}")
    if size > MAX_FILE_BYTES:
        raise ProviderError(f"contract file is implausibly large ({size:,} bytes): {path}")
    try:
        # utf-8-sig also reads plain UTF-8 and drops the byte-order mark Excel adds.
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as error:
        raise ProviderError(
            f"{path} is not UTF-8 text; in Excel choose 'CSV UTF-8 (Comma delimited)' when saving"
        ) from error

    return Snapshot(
        source=CONTRACT_FILE,
        dataset=CONTRACT_FILE_DATASET,
        partition={},
        fetched_at=now(),
        payload={
            "filename": path.name,
            "source_label": label,
            "as_of": as_of.isoformat(),
            "text": text,
        },
        request={"path": str(path)},
    )
