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
    """Claim-level outcome.

    A claim is either still PENDING (not yet adjudicated) or ADJUSTED (processed,
    broken down into service lines). NOT_FOUND means the payer has no record;
    UNRESOLVED means we couldn't get a clear answer (rep hung up, no clarity).
    """

    PENDING = "pending"
    ADJUSTED = "adjusted"
    NOT_FOUND = "not_found"
    UNRESOLVED = "unresolved"


class LineStatus(str, Enum):
    """Service-line outcome within an adjusted claim."""

    PAID = "paid"
    DENIED = "denied"


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
class ClaimLineResult(BaseModel):
    """One adjudicated service line within an adjusted claim (maps to 835 SVC/CAS)."""

    procedure_code: Optional[str] = None  # CPT/HCPCS, e.g. 99214
    line_number: Optional[str] = None
    status: LineStatus
    paid_amount: Optional[float] = None  # if paid
    billed_amount: Optional[float] = None
    denial_reason_code: Optional[str] = None  # CARC/RARC if denied
    denial_reason_description: Optional[str] = None


class ClaimStatusResult(BaseModel):
    """Extracted status for one claim (maps to 835 CLP + its service lines)."""

    claim_id: str
    status: ClaimStatus

    # PENDING claims: why and for how long.
    pending_reason: Optional[str] = None
    pending_timeline: Optional[str] = None

    # ADJUSTED claims: per-line breakdown + claim-level remittance details.
    lines: list[ClaimLineResult] = Field(default_factory=list)
    total_paid_amount: Optional[float] = None
    payment_date: Optional[str] = None
    check_or_eft_number: Optional[str] = None
    appeal_deadline: Optional[str] = None

    # General.
    status_details: Optional[str] = None
    additional_info: Optional[str] = None

    # Human-review triage. The status extracted from a voice call drives
    # irreversible money decisions (post a payment, write off a denial, file an
    # appeal), and a misheard amount/code looks just as plausible as a correct
    # one. Rather than attempting a live handoff, we flag claims the agent can't
    # confidently resolve so a human re-checks them before acting.
    #   needs_human_review   — gate: don't act on this claim until a human looks.
    #   review_reasons       — why it was flagged (uncertain value, stuck call...).
    #   low_confidence_fields — exact field names the reviewer should re-verify.
    needs_human_review: bool = False
    review_reasons: list[str] = Field(default_factory=list)
    low_confidence_fields: list[str] = Field(default_factory=list)


class TranscriptTurn(BaseModel):
    role: str  # "agent" | "rep"
    text: str


class CallResult(BaseModel):
    """Complete, persisted output of a call."""

    call_id: str
    payer_name: str
    call_timestamp: str  # ISO 8601
    rep_name: Optional[str] = None
    reference_number: Optional[str] = None
    claims: list[ClaimStatusResult] = Field(default_factory=list)
    call_summary: Optional[str] = None
    transcript: list[TranscriptTurn] = Field(default_factory=list)


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

    def to_result(
        self, transcript: Optional[list["TranscriptTurn"]] = None
    ) -> CallResult:
        from datetime import datetime, timezone

        # Every requested claim gets an outcome: any claim never recorded during
        # the call is persisted as 'unresolved' (rep hung up / no clear answer).
        recorded = {c.claim_id for c in self.claims_completed}
        claims = list(self.claims_completed)
        for claim in self.call_request.claims:
            if claim.claim_id not in recorded:
                claims.append(
                    ClaimStatusResult(
                        claim_id=claim.claim_id,
                        status=ClaimStatus.UNRESOLVED,
                        status_details="Not resolved during the call.",
                        needs_human_review=True,
                        review_reasons=["unresolved_no_clear_answer"],
                    )
                )

        return CallResult(
            call_id=self.call_id,
            payer_name=self.call_request.payer_name,
            call_timestamp=datetime.now(timezone.utc).isoformat(),
            rep_name=self.rep_name,
            reference_number=self.reference_number,
            claims=claims,
            transcript=transcript or [],
        )
