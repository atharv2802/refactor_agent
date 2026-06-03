"""Abstract call-objective contract.

A ``CallObjective`` fully describes a call type: its system prompt, the tools the
agent may call, the opening line, and how tool calls mutate session state. The
conversation engine and the Vapi webhook layer both drive an objective through
this interface, so adding a new call type (eligibility check, denial follow-up)
is a new subclass — nothing else changes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from server.models import CallSession, ConversationPhase


@dataclass
class ToolResult:
    """Outcome of a tool call: a message handed back to the LLM, plus state hints."""

    content: str
    completed_call: bool = False


class CallObjective(ABC):
    #: Stable identifier used by the registry and Vapi assistant config.
    name: str = "base"

    @abstractmethod
    def get_system_prompt(self, session: CallSession) -> str:
        """Full system prompt with verification data injected from the session."""

    @abstractmethod
    def get_tools(self) -> list[dict[str, Any]]:
        """OpenAI-format tool/function schemas exposed to the LLM."""

    @abstractmethod
    def get_first_message(self, session: CallSession) -> str:
        """The line the agent speaks first when the call connects."""

    @abstractmethod
    def handle_tool_call(
        self, session: CallSession, name: str, arguments: dict[str, Any]
    ) -> ToolResult:
        """Execute one tool call, mutating ``session`` as needed."""

    def is_complete(self, session: CallSession) -> bool:
        """Whether the objective has been satisfied for this session."""
        return session.phase == ConversationPhase.COMPLETE
