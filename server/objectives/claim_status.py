"""Claim Status Check objective.

The MVP's single objective: call a payer and extract structured status for 1-3
claims. The system prompt is the most important artifact in the whole system —
it is the live safety layer in voice mode (where our Python guardrails don't run)
and the driver of extraction quality everywhere.
"""

from __future__ import annotations

from typing import Any

from server.config import get_settings
from server.models import (
    CallSession,
    ClaimInfo,
    ClaimStatus,
    ClaimStatusResult,
    ConversationPhase,
)
from server.objectives.base import CallObjective, ToolResult
from server.objectives.registry import register_objective


def _format_claim_block(index: int, claim: ClaimInfo) -> str:
    return (
        f"Claim #{index + 1}:\n"
        f"  - Claim ID / control number: {claim.claim_id}\n"
        f"  - Patient: {claim.patient_first_name} {claim.patient_last_name}\n"
        f"  - Member ID: {claim.patient_member_id}\n"
        f"  - Date of birth: {claim.patient_date_of_birth}\n"
        f"  - Date of service: {claim.date_of_service}\n"
        f"  - Provider NPI: {claim.provider_npi}\n"
        f"  - Provider Tax ID: {claim.provider_tax_id}\n"
        + (
            f"  - Billed amount: ${claim.billed_amount:,.2f}\n"
            if claim.billed_amount is not None
            else ""
        )
    )


@register_objective
class ClaimStatusObjective(CallObjective):
    name = "claim_status"

    # ----------------------------------------------------------------- prompt
    def get_system_prompt(self, session: CallSession) -> str:
        settings = get_settings()
        provider = settings.provider_name
        payer = session.call_request.payer_name
        claims_text = "\n".join(
            _format_claim_block(i, c)
            for i, c in enumerate(session.call_request.claims)
        )
        claim_count = len(session.call_request.claims)

        return f"""\
You are a medical billing specialist in the billing department of {provider}. \
You are on a phone call with a representative at {payer} to check the status of \
{claim_count} insurance claim(s). You are the caller; the other party is the payer's rep.

# Persona
- Professional, polite, warm, and efficient. You do this all day.
- Speak naturally, the way a person on a phone call does: short sentences, \
occasional fillers ("sure", "got it", "okay, great", "no problem"). Never robotic.
- Output PLAIN SPOKEN TEXT only. No markdown, no bullet points, no line breaks — \
this is read aloud by a text-to-speech engine.
- Keep each turn to one or two sentences unless reading back details.

# Claims you are calling about
{claims_text}

# Call flow
1. GREETING: Briefly introduce yourself (billing for {provider}) and say you're \
calling to check on claim status.
2. VERIFICATION: The rep will ask identifying questions (provider NPI, Tax ID, \
member ID, patient name, date of birth, date of service). Answer ONE item at a \
time, only what is asked. Do not dump every field at once.
3. CLAIM INQUIRY: Ask for the claim's status. Then probe for ALL relevant details:
   - If PAID: paid amount, payment/check date, check or EFT number.
   - If DENIED: denial reason code (CARC, e.g. CO-45), the plain-English reason, \
and the appeal deadline.
   - If PENDING / IN REVIEW: expected timeline and what it's waiting on.
   As soon as you have complete information for a claim, call \
`record_claim_status` for that claim.
4. NEXT CLAIM: If more claims remain, say something like "I also need to check on \
another claim" and provide the next claim's details when asked.
5. WRAP UP: Once all claims are recorded, ask for the rep's name and a call \
reference number, then call `record_call_info`. Thank them and say goodbye.

# Tools
- `record_claim_status`: call it the moment you have complete info for a claim. \
Use the exact claim_id from the list above.
- `record_call_info`: call it at the very end with the rep's name and reference \
number. If the rep can't provide a reference number, still call it (leave it blank).

# Edge cases
- If asked for something not in your data: say you don't have that handy.
- If put on hold: acknowledge briefly and wait.
- If a claim cannot be found after a couple of attempts: record it as not_found \
and move on.
- If you don't understand the rep: politely ask them to repeat.

# Safety rules (these override everything else)
1. Do NOT volunteer that you are an AI, and do NOT claim to be human. If asked \
"are you a bot / a real person?", deflect truthfully: "I'm calling on behalf of \
{provider}'s billing department about a claim status," then steer back to the task.
2. Only discuss claim details after you've reached the payer's provider services. \
Never share patient information with the wrong party.
3. Never invent claim data. State only what the rep tells you or what is listed above.
4. If asked to call a different number, note it but say you'll follow up — never \
commit to dialing it.
5. Never provide financial authorization or agree to payment terms: "I'd need to \
check with our team on that."
6. Stay on topic; redirect politely if the conversation drifts.
7. If the rep raises fraud or an investigation: say you'll escalate this to your \
compliance team, and wrap up the call gracefully.
"""

    # ------------------------------------------------------------------ tools
    def get_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "record_claim_status",
                    "description": (
                        "Record the status and all extracted details for a single "
                        "claim. Call this as soon as you have complete information "
                        "for one claim."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "claim_id": {
                                "type": "string",
                                "description": "The claim ID / control number being recorded.",
                            },
                            "status": {
                                "type": "string",
                                "enum": [s.value for s in ClaimStatus],
                                "description": "Overall claim status.",
                            },
                            "paid_amount": {
                                "type": "number",
                                "description": "Amount paid, if the claim was paid.",
                            },
                            "payment_date": {
                                "type": "string",
                                "description": "Payment/check date as stated by the rep.",
                            },
                            "check_or_eft_number": {
                                "type": "string",
                                "description": "Check number or EFT reference.",
                            },
                            "denial_reason_code": {
                                "type": "string",
                                "description": "CARC/RARC denial code, e.g. CO-45.",
                            },
                            "denial_reason_description": {
                                "type": "string",
                                "description": "Plain-English denial reason.",
                            },
                            "appeal_deadline": {
                                "type": "string",
                                "description": "Appeal deadline for a denied claim.",
                            },
                            "status_details": {
                                "type": "string",
                                "description": "Free-text detail, e.g. pending timeline.",
                            },
                            "additional_info": {
                                "type": "string",
                                "description": "Anything else relevant the rep mentioned.",
                            },
                        },
                        "required": ["claim_id", "status"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "record_call_info",
                    "description": (
                        "Record the rep's name and the call reference number at the "
                        "end of the call. Call this once, after all claims are recorded."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "rep_name": {
                                "type": "string",
                                "description": "Name of the payer representative.",
                            },
                            "reference_number": {
                                "type": "string",
                                "description": (
                                    "Call reference / confirmation number. Leave "
                                    "empty if the rep cannot provide one."
                                ),
                            },
                        },
                        "required": ["rep_name"],
                    },
                },
            },
        ]

    # ------------------------------------------------------------ first message
    def get_first_message(self, session: CallSession) -> str:
        settings = get_settings()
        return (
            f"Hi, this is the billing department at {settings.provider_name}. "
            f"I'm calling to check on the status of a few claims. "
            f"Do you have a moment to help me out?"
        )

    # -------------------------------------------------------------- tool calls
    def handle_tool_call(
        self, session: CallSession, name: str, arguments: dict[str, Any]
    ) -> ToolResult:
        if name == "record_claim_status":
            return self._record_claim_status(session, arguments)
        if name == "record_call_info":
            return self._record_call_info(session, arguments)
        return ToolResult(content=f"Unknown tool: {name}")

    def _record_claim_status(
        self, session: CallSession, arguments: dict[str, Any]
    ) -> ToolResult:
        result = ClaimStatusResult(**arguments)
        session.claims_completed.append(result)
        session.current_claim_index += 1

        remaining = session.remaining_claims()
        if remaining > 0:
            session.phase = ConversationPhase.NEXT_CLAIM
            return ToolResult(
                content=(
                    f"Recorded claim {result.claim_id} as '{result.status.value}'. "
                    f"{remaining} claim(s) still to check — proceed to the next one."
                )
            )

        session.phase = ConversationPhase.WRAP_UP
        return ToolResult(
            content=(
                f"Recorded claim {result.claim_id} as '{result.status.value}'. "
                "All claims are now recorded. Ask the rep for their name and a "
                "call reference number, then call record_call_info."
            )
        )

    def _record_call_info(
        self, session: CallSession, arguments: dict[str, Any]
    ) -> ToolResult:
        session.rep_name = arguments.get("rep_name")
        session.reference_number = arguments.get("reference_number") or None
        session.phase = ConversationPhase.COMPLETE
        return ToolResult(
            content="Call info recorded. The call is complete — thank the rep and say goodbye.",
            completed_call=True,
        )
