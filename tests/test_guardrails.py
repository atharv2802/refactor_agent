"""Guardrail unit tests (pure, no LLM)."""

from __future__ import annotations

from server.factory import build_session
from server.guardrails import Guardrails


def _session(call_request):
    return build_session(call_request)


def test_check_response_replaces_disclosure():
    g = Guardrails()
    safe, violations = g.check_response("Actually I am a bot.")
    assert violations
    assert "bot" not in safe.lower()


def test_check_response_passes_clean_text():
    g = Guardrails()
    safe, violations = g.check_response("Sure, the NPI is on file.")
    assert not violations
    assert safe == "Sure, the NPI is on file."


def test_sanitize_strips_markdown_and_collapses_whitespace():
    g = Guardrails()
    clean, _ = g.sanitize("**Hello**\n\nthere   friend")
    assert clean == "Hello there friend"


def test_validate_tool_call_unknown_claim(call_request):
    g = Guardrails()
    v = g.validate_tool_call(_session(call_request), "record_claim_status",
                             {"claim_id": "NOPE", "status": "adjusted"})
    assert not v.ok


def test_validate_tool_call_bad_status(call_request):
    g = Guardrails()
    cid = call_request.claims[0].claim_id
    v = g.validate_tool_call(_session(call_request), "record_claim_status",
                             {"claim_id": cid, "status": "banana"})
    assert not v.ok


def test_validate_tool_call_bad_line_status(call_request):
    g = Guardrails()
    cid = call_request.claims[0].claim_id
    v = g.validate_tool_call(_session(call_request), "record_claim_status",
                             {"claim_id": cid, "status": "adjusted",
                              "lines": [{"status": "refunded"}]})
    assert not v.ok


def test_validate_tool_call_negative_line_amount(call_request):
    g = Guardrails()
    cid = call_request.claims[0].claim_id
    v = g.validate_tool_call(_session(call_request), "record_claim_status",
                             {"claim_id": cid, "status": "adjusted",
                              "lines": [{"status": "paid", "paid_amount": -5}]})
    assert not v.ok


def test_validate_tool_call_absurd_amount_warns(call_request):
    g = Guardrails()
    cid = call_request.claims[0].claim_id
    v = g.validate_tool_call(_session(call_request), "record_claim_status",
                             {"claim_id": cid, "status": "adjusted",
                              "lines": [{"status": "paid", "paid_amount": 5_000_000}]})
    assert v.ok and v.warnings


def test_unresolved_status_is_valid(call_request):
    g = Guardrails()
    cid = call_request.claims[0].claim_id
    v = g.validate_tool_call(_session(call_request), "record_claim_status",
                             {"claim_id": cid, "status": "unresolved"})
    assert v.ok


def test_double_record_rejected(call_request):
    from server.models import ClaimStatus, ClaimStatusResult
    g = Guardrails()
    session = _session(call_request)
    cid = call_request.claims[0].claim_id
    session.claims_completed.append(ClaimStatusResult(claim_id=cid, status=ClaimStatus.ADJUSTED))
    v = g.validate_tool_call(session, "record_claim_status", {"claim_id": cid, "status": "adjusted"})
    assert not v.ok
