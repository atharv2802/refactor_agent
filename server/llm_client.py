"""LLM client abstraction.

The conversation engine depends on the ``LLMClient`` protocol, not on OpenAI
directly. This keeps the orchestration logic provider-agnostic: swapping in
Anthropic, an open model, or a fake for tests means writing a new client, not
touching the engine. The canonical transcript format is the OpenAI chat-message
schema; other providers' clients translate to/from it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class AssistantTurn:
    """Normalised result of one LLM call."""

    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    # Raw assistant message in OpenAI format, to append back to the transcript.
    raw_message: dict[str, Any] = field(default_factory=dict)


class LLMClient(Protocol):
    def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> AssistantTurn: ...


class OpenAIClient:
    """OpenAI Chat Completions implementation of ``LLMClient``."""

    def __init__(self, api_key: str, model: str, temperature: float = 0.7) -> None:
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key)
        self._model = model
        self._temperature = temperature

    def chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> AssistantTurn:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            tools=tools or None,
            tool_choice="auto" if tools else None,
            temperature=self._temperature,
        )
        message = response.choices[0].message

        tool_calls: list[ToolCall] = []
        for call in message.tool_calls or []:
            try:
                arguments = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                arguments = {}
            tool_calls.append(
                ToolCall(id=call.id, name=call.function.name, arguments=arguments)
            )

        raw: dict[str, Any] = {"role": "assistant", "content": message.content}
        if message.tool_calls:
            raw["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.function.name,
                        "arguments": call.function.arguments,
                    },
                }
                for call in message.tool_calls
            ]

        return AssistantTurn(
            content=message.content, tool_calls=tool_calls, raw_message=raw
        )
