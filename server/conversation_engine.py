"""Conversation engine (TEXT MODE orchestration).

Drives one turn-based conversation: takes what the rep said, runs the LLM
tool-calling loop against the active objective, applies response guardrails, and
returns spoken text. Voice mode does NOT use this loop — Vapi owns it there — but
it reuses the SAME objective (prompt, tools, handlers), so behaviour is shared
even though orchestration is not.

Dependencies (LLM client, guardrails, objective) are injected, which keeps the
engine unit-testable with a fake LLM and free of global state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from server.guardrails import Guardrails
from server.llm_client import LLMClient
from server.models import CallSession, ConversationPhase
from server.objectives.base import CallObjective
from server.safety import AuditLog


@dataclass
class EngineResult:
    text: str
    warnings: list[str] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)


class ConversationEngine:
    def __init__(
        self,
        *,
        objective: CallObjective,
        session: CallSession,
        llm: LLMClient,
        guardrails: Guardrails,
        audit: AuditLog | None = None,
        max_turns: int = 50,
        max_tool_calls: int = 10,
    ) -> None:
        self._objective = objective
        self._session = session
        self._llm = llm
        self._guardrails = guardrails
        self._audit = audit or AuditLog()
        self._max_turns = max_turns
        self._max_tool_calls = max_tool_calls

        self._messages: list[dict[str, Any]] = [
            {"role": "system", "content": objective.get_system_prompt(session)}
        ]
        self._turns = 0
        self._audit.record(session.call_id, "call_started", objective=objective.name)

    @property
    def session(self) -> CallSession:
        return self._session

    @property
    def transcript(self) -> list[dict[str, Any]]:
        return list(self._messages)

    def opening_message(self) -> str:
        """The agent speaks first; record it as the opening assistant turn."""
        text = self._objective.get_first_message(self._session)
        text, _ = self._guardrails.sanitize(text)
        self._messages.append({"role": "assistant", "content": text})
        return text

    def process_turn(self, rep_text: str) -> EngineResult:
        self._turns += 1
        self._messages.append({"role": "user", "content": rep_text})

        if self._turns > self._max_turns:
            return self._force_wrap_up()

        tools = self._objective.get_tools()
        tool_calls_made = 0

        while True:
            turn = self._llm.chat(self._messages, tools)
            self._messages.append(turn.raw_message)

            if not turn.tool_calls:
                return self._finalize_text(turn.content or "")

            for call in turn.tool_calls:
                tool_calls_made += 1
                content = self._execute_tool(call.name, call.arguments)
                self._messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": content,
                    }
                )

            if tool_calls_made >= self._max_tool_calls:
                # Stop the loop, ask the LLM for a closing line without tools.
                final = self._llm.chat(self._messages, tools=[])
                self._messages.append(final.raw_message)
                return self._finalize_text(final.content or "")

    # ------------------------------------------------------------- internals
    def _execute_tool(self, name: str, arguments: dict[str, Any]) -> str:
        validation = self._guardrails.validate_tool_call(
            self._session, name, arguments
        )
        if not validation.ok:
            self._audit.record(
                self._session.call_id, "tool_rejected", tool=name, reason=validation.error
            )
            return f"ERROR: {validation.error}"

        for warning in validation.warnings or []:
            self._audit.record(self._session.call_id, "tool_warning", warning=warning)

        result = self._objective.handle_tool_call(self._session, name, arguments)
        self._audit.record(
            self._session.call_id,
            "tool_executed",
            tool=name,
            phase=self._session.phase.value,
        )
        return result.content

    def _finalize_text(self, text: str) -> EngineResult:
        safe_text, violations = self._guardrails.check_response(text)
        clean_text, warnings = self._guardrails.sanitize(safe_text)
        if violations:
            self._audit.record(
                self._session.call_id, "response_blocked", violations=violations
            )
        # Replace the raw assistant content with the sanitized version.
        if self._messages and self._messages[-1].get("role") == "assistant":
            self._messages[-1]["content"] = clean_text
        return EngineResult(text=clean_text, warnings=warnings, violations=violations)

    def _force_wrap_up(self) -> EngineResult:
        self._session.phase = ConversationPhase.COMPLETE
        self._audit.record(self._session.call_id, "forced_wrap_up", turns=self._turns)
        text = (
            "I appreciate your time, but I need to wrap up now. "
            "Thank you so much for your help, and have a great day."
        )
        clean, _ = self._guardrails.sanitize(text)
        return EngineResult(text=clean)

    @property
    def is_complete(self) -> bool:
        return self._objective.is_complete(self._session)
