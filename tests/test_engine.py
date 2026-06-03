"""Conversation-engine behaviour, driven entirely by a fake LLM."""

from __future__ import annotations

from server.config import Settings
from server.factory import build_engine, build_session
from server.models import ClaimStatus, ConversationPhase, LineStatus
from tests.conftest import FakeLLM, text_turn, tool_turn


def _engine(call_request, script, **overrides):
    session = build_session(call_request)
    settings = Settings(openai_api_key="test", **overrides)
    engine = build_engine(session, llm=FakeLLM(script), settings=settings)
    return engine, session


def test_opening_message_is_recorded(call_request):
    engine, _ = _engine(call_request, [])
    opening = engine.opening_message()
    assert opening
    assert engine.transcript[-1]["content"] == opening


def test_happy_path_records_claim_and_completes(call_request):
    cid = call_request.claims[0].claim_id
    script = [
        text_turn("Sure, the NPI is 1841293847."),
        tool_turn("record_claim_status", {
            "claim_id": cid, "status": "adjusted",
            "lines": [{"status": "paid", "paid_amount": 1100.0}],
            "payment_date": "January 25", "check_or_eft_number": "88432",
        }),
        text_turn("Could I get your name and a reference number?"),
        tool_turn("record_call_info", {"rep_name": "Sarah", "reference_number": "REF-1"}),
        text_turn("Thank you, goodbye."),
    ]
    engine, session = _engine(call_request, script)
    engine.opening_message()
    engine.process_turn("Can I get your NPI?")
    engine.process_turn("It was paid, 1100 on Jan 25, EFT 88432.")
    engine.process_turn("Sarah, REF-1.")

    assert engine.is_complete
    assert session.phase == ConversationPhase.COMPLETE
    assert len(session.claims_completed) == 1
    result = session.claims_completed[0]
    assert result.status == ClaimStatus.ADJUSTED
    assert result.lines[0].status == LineStatus.PAID
    assert result.lines[0].paid_amount == 1100.0
    assert session.rep_name == "Sarah"


def test_agent_low_confidence_flags_claim_for_review(call_request):
    cid = call_request.claims[0].claim_id
    script = [
        tool_turn("record_claim_status", {
            "claim_id": cid, "status": "adjusted",
            "lines": [{"status": "paid", "paid_amount": 1100.0}],
            "check_or_eft_number": "88432",
            "low_confidence_fields": ["check_or_eft_number"],
        }),
        text_turn("Could I get your name and a reference number?"),
    ]
    engine, session = _engine(call_request, script)
    engine.opening_message()
    engine.process_turn("It was paid, around 1100, EFT eight-eight... sorry, hard to hear.")

    result = session.claims_completed[0]
    assert result.needs_human_review is True
    assert "low_confidence:check_or_eft_number" in result.review_reasons


def test_appeal_deadline_auto_flags_claim_for_review(call_request):
    cid = call_request.claims[0].claim_id
    script = [
        tool_turn("record_claim_status", {
            "claim_id": cid, "status": "adjusted",
            "lines": [{"status": "denied", "denial_reason_code": "CO-45"}],
            "appeal_deadline": "April 30",
        }),
        text_turn("Thanks. Your name and a reference number?"),
    ]
    engine, session = _engine(call_request, script)
    engine.opening_message()
    engine.process_turn("Denied under CO-45, appeal by April 30.")

    result = session.claims_completed[0]
    assert result.needs_human_review is True
    assert "denial_with_appeal_deadline" in result.review_reasons


def test_invalid_claim_id_is_rejected_and_not_recorded(call_request):
    script = [
        tool_turn("record_claim_status", {"claim_id": "WRONG", "status": "adjusted"}),
        text_turn("Sorry, let me re-check that claim number."),
    ]
    engine, session = _engine(call_request, script)
    engine.opening_message()
    engine.process_turn("That claim was paid.")
    assert len(session.claims_completed) == 0


def test_response_guardrail_blocks_ai_disclosure(call_request):
    script = [text_turn("Yes, I am an AI assistant calling for billing.")]
    engine, _ = _engine(call_request, script)
    engine.opening_message()
    result = engine.process_turn("Are you a bot?")
    assert "ai" not in result.text.lower()
    assert result.violations


def test_long_response_warns_but_is_not_truncated(call_request):
    long_text = "Okay. " * 200  # ~1200 chars
    engine, _ = _engine(call_request, [text_turn(long_text)], max_response_chars=500)
    engine.opening_message()
    result = engine.process_turn("Tell me everything.")
    assert any("response_length" in w for w in result.warnings)
    assert len(result.text) > 500  # soft signal, not a hard cut


def test_turn_limit_forces_wrap_up(call_request):
    engine, session = _engine(call_request, [text_turn("ok")], max_turns=1)
    engine.opening_message()
    engine.process_turn("turn one")  # allowed
    result = engine.process_turn("turn two")  # exceeds max_turns
    assert session.phase == ConversationPhase.COMPLETE
    assert "wrap up" in result.text.lower() or "thank you" in result.text.lower()
