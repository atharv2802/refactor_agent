"""Voice-path tests: assistant config + webhook tool execution (no real Vapi)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from server.app import app
from server.session_store import store

client = TestClient(app)

CALL_REQUEST = {
    "payer_name": "Blue Shield of California",
    "claims": [{
        "claim_id": "CLM-2025-0001", "provider_npi": "1841293847",
        "provider_tax_id": "954321987", "patient_member_id": "BSC123456789",
        "patient_first_name": "Maria", "patient_last_name": "Gonzalez",
        "patient_date_of_birth": "03/14/1985", "date_of_service": "01/10/2025",
        "billed_amount": 1450.0,
    }],
}


def _new_call() -> str:
    return client.post("/api/claims", json=CALL_REQUEST).json()["call_id"]


def test_assistant_config_has_prompt_and_tools():
    call_id = _new_call()
    cfg = client.get(f"/api/assistant/{call_id}").json()
    assert cfg["model"]["messages"][0]["content"]
    names = {t["function"]["name"] for t in cfg["model"]["tools"]}
    assert names == {"record_claim_status", "record_call_info"}
    assert cfg["metadata"]["call_id"] == call_id


def test_function_call_records_claim_and_end_of_call_saves_result():
    call_id = _new_call()
    body = {
        "message": {
            "type": "function-call",
            "call": {"id": "vapi-abc", "metadata": {"call_id": call_id}},
            "functionCall": {
                "name": "record_claim_status",
                "parameters": {"claim_id": "CLM-2025-0001", "status": "adjusted",
                               "lines": [{"status": "paid", "paid_amount": 1100.0}]},
            },
        }
    }
    r = client.post("/vapi/webhook", json=body)
    assert r.status_code == 200
    session = store.get(call_id)
    assert len(session.claims_completed) == 1

    end = {"message": {"type": "end-of-call-report",
                       "call": {"id": "vapi-abc", "metadata": {"call_id": call_id}},
                       "summary": "Call done.",
                       "artifact": {"messages": [
                           {"role": "bot", "message": "Hi, billing department here."},
                           {"role": "user", "message": "It was paid 1100."},
                       ]}}}
    assert client.post("/vapi/webhook", json=end).status_code == 200
    result = client.get(f"/api/results/{call_id}")
    assert result.status_code == 200
    data = result.json()
    assert data["claims"][0]["status"] == "adjusted"
    assert data["claims"][0]["lines"][0]["status"] == "paid"
    assert len(data["transcript"]) == 2
    assert data["transcript"][0]["role"] == "agent"


def test_tool_calls_variant_with_string_arguments():
    call_id = _new_call()
    body = {
        "message": {
            "type": "tool-calls",
            "call": {"id": "vapi-xyz", "metadata": {"call_id": call_id}},
            "toolCalls": [{
                "id": "tc1",
                "function": {"name": "record_claim_status",
                             "arguments": json.dumps({"claim_id": "CLM-2025-0001",
                                                      "status": "not_found"})},
            }],
        }
    }
    r = client.post("/vapi/webhook", json=body)
    assert r.status_code == 200
    assert store.get(call_id).claims_completed[0].status.value == "not_found"


def test_webhook_rejects_bad_secret(monkeypatch):
    from server import vapi_webhook

    class FakeSettings:
        vapi_webhook_secret = "expected-secret"

    monkeypatch.setattr(vapi_webhook, "get_settings", lambda: FakeSettings())
    r = client.post("/vapi/webhook", headers={"x-vapi-secret": "wrong"},
                    json={"message": {"type": "status-update"}})
    assert r.status_code == 401
