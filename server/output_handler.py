"""Output sinks.

The engine writes results through the ``OutputSink`` protocol, so swapping JSON
files for a database (the production path) is a new sink, not an engine change.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from server.models import CallResult


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
            json.dumps(result.model_dump(), indent=2, default=str),
            encoding="utf-8",
        )
        return str(path)
