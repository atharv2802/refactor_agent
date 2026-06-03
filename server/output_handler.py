"""Output serialization + sinks.

``to_document`` is the single serialization path for a finished call: it dumps
the ``CallResult`` and attaches the EDI 835 remittance view to each claim, so the
persisted file and the ``/api/results`` response are byte-identical. The engine
writes through the ``OutputSink`` protocol, so swapping JSON files for a database
(the production path) is a new sink, not an engine change.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from server.edi import map_result_to_835
from server.models import CallResult


def to_document(result: CallResult) -> dict[str, Any]:
    """Serialise a ``CallResult`` with the 835 remittance view per claim."""
    doc = result.model_dump()
    for claim_doc, claim in zip(doc["claims"], result.claims):
        claim_doc["remittance_835"] = map_result_to_835(claim)
    return doc


class OutputSink(Protocol):
    def write(self, result: CallResult) -> str: ...


class FileOutputSink:
    """Persist each call result as ``<output_dir>/<call_id>.json``."""

    def __init__(self, output_dir: str) -> None:
        self._dir = Path(output_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def write(self, result: CallResult) -> str:
        path = self._dir / f"{result.call_id}.json"
        path.write_text(
            json.dumps(to_document(result), indent=2, default=str),
            encoding="utf-8",
        )
        return str(path)
