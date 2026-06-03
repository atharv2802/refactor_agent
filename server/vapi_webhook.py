"""Vapi webhook + assistant-config layer.

In voice mode Vapi owns the LLM loop; our server only (a) hands Vapi the
assistant config with claim data injected into the system prompt, and (b)
executes tool calls Vapi forwards back. Because our Python response guardrails
don't run on the voice path, the SYSTEM PROMPT is the live safety layer; the
dependable server-side control here is ``Guardrails.validate_tool_call`` on the
tool path, which runs identically to text mode.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request

from server.config import get_settings
from server.guardrails import Guardrails
from server.models import TranscriptTurn
from server.objectives import get_objective
from server.safety import AuditLog
from server.session_store import store
from server.tool_runner import execute_tool_call

logger = logging.getLogger("claim_agent.vapi")
router = APIRouter()

_objective = get_objective("claim_status")
_guardrails = Guardrails()
_audit = AuditLog()


def build_assistant_config(call_id: str) -> dict[str, Any]:
    """Construct a transient Vapi assistant for a stored session."""
    settings = get_settings()
    session = store.get(call_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Unknown call_id {call_id}")

    return {
        "name": "Claim Status Agent",
        "firstMessage": _objective.get_first_message(session),
        "model": {
            "provider": "openai",
            "model": settings.openai_model,
            "temperature": 0.7,
            "messages": [
                {"role": "system", "content": _objective.get_system_prompt(session)}
            ],
            "tools": _objective.get_tools(),
        },
        "voice": {"provider": settings.voice_provider, "voiceId": settings.voice_id},
        "server": {
            "url": f"{settings.server_url}/vapi/webhook",
            "secret": settings.vapi_webhook_secret,
        },
        "metadata": {"call_id": call_id},
    }


def _verify_secret(secret_header: str | None) -> None:
    expected = get_settings().vapi_webhook_secret
    if expected and secret_header != expected:
        raise HTTPException(status_code=401, detail="Invalid webhook secret")


def _execute_tool(session, name: str, arguments: dict[str, Any]) -> str:
    return execute_tool_call(
        objective=_objective,
        guardrails=_guardrails,
        audit=_audit,
        session=session,
        name=name,
        arguments=arguments,
    )


def _extract_transcript(message: dict[str, Any]) -> list[TranscriptTurn]:
    """Best-effort transcript from a Vapi end-of-call report across payload shapes."""
    turns: list[TranscriptTurn] = []
    messages = (message.get("artifact") or {}).get("messages") or message.get("messages") or []
    for m in messages:
        role = m.get("role")
        text = m.get("message") or m.get("content")
        if not text or role in {"system", "tool", "function"}:
            continue
        turns.append(TranscriptTurn(role="agent" if role in {"assistant", "bot"} else "rep", text=text))
    return turns


def _capture_rep_turns(session, message: dict[str, Any]) -> None:
    """Best-effort: keep the rep's words on the session so the tool handler can
    ground recorded values. Voice mode doesn't run our text loop, so the only
    place to pick up the transcript is whatever Vapi includes on the webhook
    payload. If nothing is present we leave it alone (grounding then no-ops)."""
    rep_texts = [t.text for t in _extract_transcript(message) if t.role == "rep"]
    if rep_texts:
        session.rep_turns = rep_texts


def _iter_tool_calls(message: dict[str, Any]):
    """Yield (tool_call_id, name, arguments) across Vapi payload variants."""
    # Newer: message.toolCalls / toolCallList
    for call in message.get("toolCalls") or message.get("toolCallList") or []:
        fn = call.get("function", {})
        yield call.get("id"), fn.get("name"), fn.get("arguments") or {}
    # Legacy: message.functionCall = {name, parameters}
    fc = message.get("functionCall")
    if fc:
        yield None, fc.get("name"), fc.get("parameters") or {}


@router.post("/vapi/webhook")
async def vapi_webhook(
    request: Request,
    x_vapi_secret: str | None = Header(default=None),
) -> dict[str, Any]:
    _verify_secret(x_vapi_secret)
    body = await request.json()
    message = body.get("message", {})
    msg_type = message.get("type")
    call = message.get("call", {}) or {}
    vapi_call_id = call.get("id")
    call_id = (call.get("metadata") or {}).get("call_id") or (
        message.get("metadata") or {}
    ).get("call_id")

    logger.info("vapi event type=%s call=%s", msg_type, call_id or vapi_call_id)

    if msg_type == "assistant-request":
        if not call_id:
            raise HTTPException(status_code=400, detail="Missing call_id in metadata")
        return {"assistant": build_assistant_config(call_id)}

    if msg_type in {"function-call", "tool-calls"}:
        session = store.resolve(call_id=call_id, vapi_call_id=vapi_call_id)
        if session is None:
            raise HTTPException(status_code=404, detail="No active session for call")
        import json

        _capture_rep_turns(session, message)
        results = []
        for tool_call_id, name, raw_args in _iter_tool_calls(message):
            arguments = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            output = _execute_tool(session, name, arguments)
            results.append({"toolCallId": tool_call_id, "result": output})
        # Support both response shapes Vapi has used.
        return {"results": results, "result": results[0]["result"] if results else ""}

    if msg_type == "end-of-call-report":
        session = store.resolve(call_id=call_id, vapi_call_id=vapi_call_id)
        if session is not None:
            result = session.to_result(transcript=_extract_transcript(message))
            result.call_summary = message.get("summary")
            store.save_result(result)
            from server.output_handler import FileOutputSink

            FileOutputSink(get_settings().output_dir).write(result)
            _audit.record(session.call_id, "call_ended")
        return {"ok": True}

    return {"ok": True}
