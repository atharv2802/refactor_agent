"""Shared test fixtures and a fake LLM.

The conversation engine takes its ``LLMClient`` via injection, so every test
here runs fully offline (no OpenAI key, no network) by scripting the assistant's
turns with ``FakeLLM``.
"""

from __future__ import annotations

import json

import pytest

from server.llm_client import AssistantTurn, ToolCall
from server.models import CallRequest


@pytest.fixture(autouse=True)
def _hermetic_settings(monkeypatch):
    """Keep tests independent of a developer's local ``.env``.

    Settings normally load from ``.env``; if it defines ``VAPI_WEBHOOK_SECRET``
    the webhook starts rejecting unsigned test requests. Force an empty secret
    (env vars take precedence over the ``.env`` file) so the default path is
    open, while ``test_webhook_rejects_bad_secret`` still patches its own.
    """
    from server.config import get_settings

    monkeypatch.setenv("VAPI_WEBHOOK_SECRET", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class FakeLLM:
    """Returns scripted ``AssistantTurn``s in order, ignoring inputs."""

    def __init__(self, script: list[AssistantTurn]) -> None:
        self._script = list(script)
        self._i = 0
        self.calls: list[tuple[list, list]] = []

    def chat(self, messages, tools):
        self.calls.append((messages, tools))
        if self._i >= len(self._script):
            # Default to a benign closing line if the script runs out.
            return text_turn("Thank you, goodbye.")
        turn = self._script[self._i]
        self._i += 1
        return turn


def text_turn(content: str) -> AssistantTurn:
    return AssistantTurn(content=content, raw_message={"role": "assistant", "content": content})


def tool_turn(name: str, arguments: dict, call_id: str = "tc1") -> AssistantTurn:
    return AssistantTurn(
        tool_calls=[ToolCall(id=call_id, name=name, arguments=arguments)],
        raw_message={
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(arguments)},
                }
            ],
        },
    )


@pytest.fixture
def call_request() -> CallRequest:
    return CallRequest.model_validate(
        {
            "payer_name": "Blue Shield of California",
            "claims": [
                {
                    "claim_id": "CLM-2025-0001",
                    "provider_npi": "1841293847",
                    "provider_tax_id": "954321987",
                    "patient_member_id": "BSC123456789",
                    "patient_first_name": "Maria",
                    "patient_last_name": "Gonzalez",
                    "patient_date_of_birth": "03/14/1985",
                    "date_of_service": "01/10/2025",
                    "billed_amount": 1450.0,
                }
            ],
        }
    )
