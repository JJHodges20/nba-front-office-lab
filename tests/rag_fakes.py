"""A small documentation folder and an embedding that needs no model, for the RAG tests.

``words`` embeds a text by its words: each word adds to one of a few dozen directions, so a
question shares a direction with the passages that use its words, and the nearest passage is
the one a reader would pick. It is deterministic, and nothing is downloaded.
"""

from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path

from front_office.domain.api_settings import RagSettings
from tests.ollama_fakes import ScriptedOllama

DIMENSIONS = 64
WORD = re.compile(r"[a-z]{3,}")
# Words every passage or question carries - the prefixes among them - which would only blur
# the picture.
COMMON = {"search", "document", "query", "the", "and", "for", "with", "lab", "documents"}

DOCUMENTS = {
    "docs/ARCHITECTURE.md": """\
# Architecture

The lab is built in layers.

## The database

The database is one SQLite file whose tables come from the data contracts. A build drops
and rewrites the league tables in one transaction.

## The API

The API signs users in with tokens. A token expires after 60 minutes.
""",
    "docs/decisions/0010-player-value.md": """\
# 0010 - Player value

## How it was tested

The value model is tested on seasons it never saw, one season at a time. Its error with the
minutes as played is 3.01 points per 100 possessions.
""",
    "docs/WORKBENCH.md": """\
# The workbench

## Charts

Every chart has a table view and an export button. Charts keep to one scale.
""",
    "docs/METRICS.md": """\
# Metrics

Left out of the search: the glossary is generated from code.
""",
}


def words(text: str) -> list[float]:
    """``text`` as a unit vector of its words."""
    vector = [0.0] * DIMENSIONS
    for word in WORD.findall(text.lower()):
        if word in COMMON:
            continue
        slot = int(hashlib.sha256(word.encode()).hexdigest(), 16) % DIMENSIONS
        vector[slot] += 1.0
    length = math.sqrt(sum(value * value for value in vector)) or 1.0
    # Never the zero vector: cosine distance needs a direction.
    return [value / length for value in vector] if any(vector) else [1.0] + [0.0] * (DIMENSIONS - 1)


def write_documents(root: Path, documents: dict[str, str] = DOCUMENTS) -> None:
    for relative, text in documents.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


EMBEDDING_MODEL = RagSettings().embedding_model


def ollama(**kwargs: object) -> ScriptedOllama:
    """Ollama with the chat model and the embedding model pulled, embedding by words."""
    models = kwargs.pop("models", ("qwen3:8b", f"{EMBEDDING_MODEL}:latest"))
    return ScriptedOllama(models=models, embedder=words, **kwargs)  # type: ignore[arg-type]
