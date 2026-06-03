"""Domain models.

Input models map to fields we extract from an EDI 837 claim submission.
Output models map to EDI 835 remittance-advice concepts (see ``edi/mapper_835``).

Money is modelled as ``float`` for the MVP. Production should use ``Decimal`` or
integer cents to avoid floating-point rounding on dollar amounts.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ClaimStatus(str, Enum):
    PAID = "paid"
    DENIED = "denied"
    PENDING = "pending"
    IN_REVIEW = "in_review"
    NOT_FOUND = "not_found"
    OTHER = "other"


class ConversationPhase(str, Enum):
    GREETING = "greeting"
    VERIFICATION = "verification"
    CLAIM_INQUIRY = "claim_inquiry"
    NEXT_CLAIM = "next_claim"
    WRAP_UP = "wrap_up"
    COMPLETE = "complete"


# --------------------------------------------------------------------------- #
# Input (from 837)
# --------------------------------------------------------------------------- #
class ClaimInfo(BaseModel):
    """A single claim to check on a call."""

    claim_id: str
    provider_npi: str
    provider_tax_id: str
    patient_member_id: str
    patient_first_name: str
    patient_last_name: str
    patient_date_of_birth: str  # MM/DD/YYYY
    date_of_service: str  # MM/DD/YYYY
    billed_amount: Optional[float] = None


class CallRequest(BaseModel):
    """A batch of claims to check against one payer in a single call."""

    payer_name: str
    payer_phone_number: Optional[str] = None
    claims: list[ClaimInfo] = Field(..., min_length=1, max_length=3)


# --------------------------------------------------------------------------- #
# Output (maps to 835)
# --------------------------------------------------------------------------- #
class ClaimStatusResult(BaseModel):
    """Extracted status for one claim."""

    claim_id: str
    status: ClaimStatus
    status_details: Optional[str] = None
    paid_amount: Optional[float] = None
    payment_date: Optional[str] = None
    check_or_eft_number: Optional[str] = None
    denial_reason_code: Optional[str] = None
    denial_reason_description: Optional[str] = None
    appeal_deadline: Optional[str] = None
    additional_info: Optional[str] = None


class CallResult(BaseModel):
    """Complete, persisted output of a call."""

    call_id: str
    payer_name: str
    call_timestamp: str  # ISO 8601
    rep_name: Optional[str] = None
    reference_number: Optional[str] = None
    claims: list[ClaimStatusResult] = Field(default_factory=list)
    call_summary: Optional[str] = None


# --------------------------------------------------------------------------- #
# State
# --------------------------------------------------------------------------- #
class CallSession(BaseModel):
    """Mutable state for one active call."""

    call_id: str
    call_request: CallRequest
    phase: ConversationPhase = ConversationPhase.GREETING
    current_claim_index: int = 0
    claims_completed: list[ClaimStatusResult] = Field(default_factory=list)
    rep_name: Optional[str] = None
    reference_number: Optional[str] = None

    def current_claim(self) -> Optional[ClaimInfo]:
        if 0 <= self.current_claim_index < len(self.call_request.claims):
            return self.call_request.claims[self.current_claim_index]
        return None

    def is_recorded(self, claim_id: str) -> bool:
        return any(c.claim_id == claim_id for c in self.claims_completed)

    def remaining_claims(self) -> int:
        return len(self.call_request.claims) - len(self.claims_completed)

    def to_result(self) -> CallResult:
        from datetime import datetime, timezone

        return CallResult(
            call_id=self.call_id,
            payer_name=self.call_request.payer_name,
            call_timestamp=datetime.now(timezone.utc).isoformat(),
            rep_name=self.rep_name,
            reference_number=self.reference_number,
            claims=list(self.claims_completed),
        )
