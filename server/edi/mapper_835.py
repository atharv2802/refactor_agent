"""Map a ``ClaimStatusResult`` to EDI 835 remittance concepts.

This does not emit a wire-format 835; it produces a structured view keyed by the
835 segments our fields correspond to. It documents domain intent and makes a
future real-835 generator straightforward.

  CLP     -> claim-level status + total paid (status code 1/4/22/23...)
  SVC     -> one per service line (procedure code + paid/billed)
  CAS     -> per-line adjustment reason (CARC/RARC), e.g. CO-45
  DTM*036 -> payment/coverage date
  TRN     -> check / EFT reference
  AMT*AU  -> approved/total-paid amount
"""

from __future__ import annotations

from typing import Any

from server.models import ClaimLineResult, ClaimStatus, ClaimStatusResult, LineStatus


def _clp_status_code(result: ClaimStatusResult) -> str:
    """835 CLP02 claim status code (approximation of the X12 code list)."""
    if result.status is ClaimStatus.ADJUSTED:
        has_paid = any(line.status is LineStatus.PAID for line in result.lines)
        has_denied = any(line.status is LineStatus.DENIED for line in result.lines)
        if has_paid and not has_denied:
            return "1"  # processed as primary, paid
        if has_denied and not has_paid:
            return "4"  # denied
        return "2"  # processed as primary, partial (mix of paid + denied)
    # pending / not_found / unresolved -> not (fully) adjudicated
    return "23"


def _map_line(line: ClaimLineResult) -> dict[str, Any]:
    svc: dict[str, Any] = {
        "SVC": {
            "procedure_code": line.procedure_code,
            "line_number": line.line_number,
            "line_paid_amount": line.paid_amount,
            "line_billed_amount": line.billed_amount,
            "status": line.status.value,
        }
    }
    if line.status is LineStatus.DENIED and line.denial_reason_code:
        group, _, reason = line.denial_reason_code.partition("-")
        svc["CAS"] = {
            "group_code": group or None,
            "reason_code": reason or None,
            "raw_code": line.denial_reason_code,
            "description": line.denial_reason_description,
        }
    return svc


def map_result_to_835(result: ClaimStatusResult) -> dict[str, Any]:
    """Return an 835-shaped dict for one claim result."""
    mapping: dict[str, Any] = {
        "CLP": {
            "claim_id": result.claim_id,
            "claim_status_code": _clp_status_code(result),
            "status": result.status.value,
            "total_paid_amount": result.total_paid_amount,
        },
        "lines": [_map_line(line) for line in result.lines],
    }

    if result.status is ClaimStatus.PENDING:
        mapping["pending"] = {
            "reason": result.pending_reason,
            "timeline": result.pending_timeline,
        }

    if result.payment_date:
        mapping["DTM_036"] = {"payment_date": result.payment_date}

    if result.check_or_eft_number:
        mapping["TRN"] = {"reference": result.check_or_eft_number}

    if result.total_paid_amount is not None:
        mapping["AMT_AU"] = {"approved_amount": result.total_paid_amount}

    if result.appeal_deadline:
        mapping["appeal_deadline"] = result.appeal_deadline

    return mapping
