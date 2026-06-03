"""Shared tool-execution pipeline.

The text-mode engine and the voice webhook both run LLM tool calls through the
exact same sequence: validate the call, audit a rejection or any warnings, hand
off to the objective's handler, then audit the execution. Keeping it here once
means this server-side safety control behaves identically on both paths (it is
the dependable guardrail in voice mode, where the response-level checks don't
run).
"""

from __future__ import annotations

from typing import Any

from server.guardrails import Guardrails
from server.models import CallSession
from server.objectives.base import CallObjective
from server.safety import AuditLog


def execute_tool_call(
    *,
    objective: CallObjective,
    guardrails: Guardrails,
    audit: AuditLog,
    session: CallSession,
    name: str,
    arguments: dict[str, Any],
) -> str:
    """Validate, audit, and execute one tool call; return the message for the LLM."""
    validation = guardrails.validate_tool_call(session, name, arguments)
    if not validation.ok:
        audit.record(
            session.call_id, "tool_rejected", tool=name, reason=validation.error
        )
        return f"ERROR: {validation.error}"

    for warning in validation.warnings or []:
        audit.record(session.call_id, "tool_warning", warning=warning)

    result = objective.handle_tool_call(session, name, arguments)
    audit.record(
        session.call_id, "tool_executed", tool=name, phase=session.phase.value
    )
    return result.content
