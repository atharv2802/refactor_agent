"""Interactive terminal mode.

You play the payer rep: type what the rep says, the agent responds as text. This
is the fastest way to iterate on the prompt and extraction logic — no voice
infra, no API cost beyond the LLM calls.
"""

from __future__ import annotations

import json
from pathlib import Path

from server.config import get_settings
from server.factory import build_engine, build_session
from server.models import CallRequest
from server.output_handler import FileOutputSink, to_document


def load_call_request(claims_path: str) -> CallRequest:
    data = json.loads(Path(claims_path).read_text(encoding="utf-8"))
    return CallRequest.model_validate(data)


def run_text_mode(claims_path: str) -> None:
    settings = get_settings()
    if not settings.openai_api_key:
        print("ERROR: OPENAI_API_KEY is not set. Add it to your .env file.")
        return

    call_request = load_call_request(claims_path)
    session = build_session(call_request)
    engine = build_engine(session, settings=settings)

    print("=" * 70)
    print(f"  Call to {call_request.payer_name} — {len(call_request.claims)} claim(s)")
    print(f"  Call ID: {session.call_id}")
    print("  You are the PAYER REP. Type the rep's lines. Ctrl-C or 'quit' to end.")
    print("=" * 70)

    print(f"\nAGENT: {engine.opening_message()}\n")

    try:
        while not engine.is_complete:
            rep_text = input("REP:   ").strip()
            if rep_text.lower() in {"quit", "exit"}:
                break
            if not rep_text:
                continue
            result = engine.process_turn(rep_text)
            print(f"\nAGENT: {result.text}\n")
            for warning in result.warnings:
                print(f"       [warn: {warning}]")
    except (KeyboardInterrupt, EOFError):
        print("\n(call interrupted)")

    result = session.to_result(transcript=engine.clean_transcript())
    sink = FileOutputSink(settings.output_dir)
    path = sink.write(result)

    print("\n" + "=" * 70)
    print("  CALL RESULT")
    print("=" * 70)
    print(json.dumps(to_document(result), indent=2, default=str))
    print(f"\nSaved to: {path}")
