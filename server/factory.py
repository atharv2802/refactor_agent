"""Composition root.

One place that wires concrete implementations together (LLM client, guardrails,
objective, session). Keeping construction here means text mode, the webhook
server, and the eval runner all build engines the same way, and tests can pass a
fake ``llm`` to ``build_engine`` without touching globals.
"""

from __future__ import annotations

import uuid

from server.config import Settings, get_settings
from server.conversation_engine import ConversationEngine
from server.guardrails import Guardrails
from server.llm_client import LLMClient, OpenAIClient
from server.models import CallRequest, CallSession
from server.objectives import get_objective
from server.safety import AuditLog


def new_call_id() -> str:
    return f"call_{uuid.uuid4().hex[:12]}"


def build_session(call_request: CallRequest, call_id: str | None = None) -> CallSession:
    return CallSession(call_id=call_id or new_call_id(), call_request=call_request)


def build_engine(
    session: CallSession,
    *,
    objective_name: str = "claim_status",
    llm: LLMClient | None = None,
    settings: Settings | None = None,
    audit: AuditLog | None = None,
) -> ConversationEngine:
    settings = settings or get_settings()
    objective = get_objective(objective_name)
    llm = llm or OpenAIClient(
        api_key=settings.openai_api_key, model=settings.openai_model
    )
    guardrails = Guardrails(max_response_chars=settings.max_response_chars)
    return ConversationEngine(
        objective=objective,
        session=session,
        llm=llm,
        guardrails=guardrails,
        audit=audit,
        max_turns=settings.max_turns,
        max_tool_calls=settings.max_tool_calls,
    )
