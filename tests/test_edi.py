"""EDI 837 parsing + 835 mapping tests."""

from __future__ import annotations

from server.edi import map_result_to_835, parse_837
from server.models import ClaimStatus, ClaimStatusResult

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
        claim_id="C1", status=ClaimStatus.PAID, paid_amount=1100.0,
        payment_date="2025-01-25", check_or_eft_number="88432",
    )
    m = map_result_to_835(result)
    assert m["CLP"]["claim_status_code"] == "1"
    assert m["AMT_AU"]["approved_amount"] == 1100.0
    assert m["TRN"]["reference"] == "88432"


def test_map_denied_claim_splits_carc_code():
    result = ClaimStatusResult(
        claim_id="C1", status=ClaimStatus.DENIED, denial_reason_code="CO-45",
        denial_reason_description="exceeds fee schedule",
    )
    m = map_result_to_835(result)
    assert m["CLP"]["claim_status_code"] == "4"
    assert m["CAS"]["group_code"] == "CO"
    assert m["CAS"]["reason_code"] == "45"
