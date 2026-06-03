"""EDI 837 parsing + 835 mapping tests."""

from __future__ import annotations

from server.edi import map_result_to_835, parse_837
from server.models import ClaimLineResult, ClaimStatus, ClaimStatusResult, LineStatus

SAMPLE_837 = (
    "NM1*85*2*NORTHSTAR MEDICAL GROUP*****XX*1841293847~"
    "REF*EI*954321987~"
    "NM1*IL*1*GONZALEZ*MARIA****MI*BSC123456789~"
    "DMG*D8*19850314*F~"
    "CLM*CLM-2025-0001*1450.00***11:B:1*Y*A*Y*I~"
    "DTP*472*D8*20250110~"
)


def test_parse_837_extracts_all_fields():
    claims = parse_837(SAMPLE_837)
    assert len(claims) == 1
    c = claims[0]
    assert c.claim_id == "CLM-2025-0001"
    assert c.provider_npi == "1841293847"
    assert c.provider_tax_id == "954321987"
    assert c.patient_member_id == "BSC123456789"
    assert c.patient_last_name == "GONZALEZ"
    assert c.patient_date_of_birth == "03/14/1985"
    assert c.date_of_service == "01/10/2025"
    assert c.billed_amount == 1450.0


def test_parse_837_handles_newline_terminators():
    claims = parse_837(SAMPLE_837.replace("~", "\n"))
    assert len(claims) == 1
    assert claims[0].claim_id == "CLM-2025-0001"


def test_map_paid_claim_to_835():
    result = ClaimStatusResult(
        claim_id="C1", status=ClaimStatus.ADJUSTED, total_paid_amount=1100.0,
        payment_date="2025-01-25", check_or_eft_number="88432",
        lines=[ClaimLineResult(status=LineStatus.PAID, paid_amount=1100.0)],
    )
    m = map_result_to_835(result)
    assert m["CLP"]["claim_status_code"] == "1"
    assert m["AMT_AU"]["approved_amount"] == 1100.0
    assert m["TRN"]["reference"] == "88432"
    assert m["lines"][0]["SVC"]["status"] == "paid"


def test_map_denied_line_splits_carc_code():
    result = ClaimStatusResult(
        claim_id="C1", status=ClaimStatus.ADJUSTED,
        lines=[ClaimLineResult(
            status=LineStatus.DENIED, denial_reason_code="CO-45",
            denial_reason_description="exceeds fee schedule",
        )],
    )
    m = map_result_to_835(result)
    assert m["CLP"]["claim_status_code"] == "4"
    assert m["lines"][0]["CAS"]["group_code"] == "CO"
    assert m["lines"][0]["CAS"]["reason_code"] == "45"


def test_map_partial_payment_status_code():
    result = ClaimStatusResult(
        claim_id="C1", status=ClaimStatus.ADJUSTED,
        lines=[
            ClaimLineResult(status=LineStatus.PAID, paid_amount=220.0),
            ClaimLineResult(status=LineStatus.DENIED, denial_reason_code="CO-97"),
        ],
    )
    m = map_result_to_835(result)
    assert m["CLP"]["claim_status_code"] == "2"  # mixed paid + denied
    assert len(m["lines"]) == 2


def test_map_pending_claim():
    result = ClaimStatusResult(
        claim_id="C1", status=ClaimStatus.PENDING,
        pending_reason="in review", pending_timeline="5 to 7 business days",
    )
    m = map_result_to_835(result)
    assert m["CLP"]["claim_status_code"] == "23"
    assert m["pending"]["timeline"] == "5 to 7 business days"
