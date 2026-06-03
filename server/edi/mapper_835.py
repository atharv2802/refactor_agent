"""Map a ``ClaimStatusResult`` to EDI 835 remittance concepts.

This does not emit a wire-format 835; it produces a structured view keyed by the
835 segments our fields correspond to. It documents domain intent and makes a
future real-835 generator straightforward.

  CLP   -> claim-level status + amounts (status code 1/4/22/23...)
  CAS   -> adjustment reason (CARC/RARC), e.g. CO-45
  DTM*036 -> payment/coverage date
  TRN   -> check / EFT reference
  AMT*AU -> approved/paid amount
"""

from __future__ import annotations

from typing import Any

from server.models import ClaimStatus, ClaimStatusResult

# Our status enum -> 835 CLP02 claim status code.
_CLP_STATUS_CODE: dict[ClaimStatus, str] = {
    ClaimStatus.PAID: "1",  # processed as primary
    ClaimStatus.DENIED: "4",  # denied
    ClaimStatus.PENDING: "23",  # not-yet-adjudicated / pending (approximation)
    ClaimStatus.IN_REVIEW: "23",
    ClaimStatus.NOT_FOUND: "23",
    ClaimStatus.OTHER: "23",
}


def map_result_to_835(result: ClaimStatusResult) -> dict[str, Any]:
    """Return an 835-shaped dict for one claim result."""
    mapping: dict[str, Any] = {
        "CLP": {
            "claim_id": result.claim_id,
            "claim_status_code": _CLP_STATUS_CODE.get(result.status, "23"),
            "status": result.status.value,
            "total_paid_amount": result.paid_amount,
        }
    }

    if result.denial_reason_code:
        # CARC codes look like "CO-45": group code CO, reason code 45.
        group, _, reason = result.denial_reason_code.partition("-")
        mapping["CAS"] = {
            "group_code": group or None,
            "reason_code": reason or None,
            "raw_code": result.denial_reason_code,
            "description": result.denial_reason_description,
        }

    if result.payment_date:
        mapping["DTM_036"] = {"payment_date": result.payment_date}

    if result.check_or_eft_number:
        mapping["TRN"] = {"reference": result.check_or_eft_number}

    if result.paid_amount is not None:
        mapping["AMT_AU"] = {"approved_amount": result.paid_amount}

    if result.appeal_deadline:
        mapping["appeal_deadline"] = result.appeal_deadline

    return mapping
