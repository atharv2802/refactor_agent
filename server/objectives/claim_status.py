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
    LineStatus,
)
from server.objectives.base import CallObjective, ToolResult
from server.objectives.registry import register_objective

# Above this, a paid amount is more likely a misheard figure than a real one, so
# it always earns a human glance. (Mirrors the guardrails "suspicious amount"
# bar; kept here so review triage doesn't depend on the guardrails internals.)
_REVIEW_AMOUNT_THRESHOLD = 1_000_000.0


def _derive_review(result: ClaimStatusResult) -> None:
    """Decide whether a recorded claim needs a human glance before it's acted on.

    Combines what the agent flagged itself (``needs_human_review`` /
    ``low_confidence_fields``) with deterministic rules for situations whose
    extracted value drives an irreversible money decision: no clear resolution,
    an appeal deadline to honour, or an implausibly large amount. Mutates
    ``result`` in place.
    """
    reasons = list(result.review_reasons)
    reasons += [f"low_confidence:{name}" for name in result.low_confidence_fields]

    if result.status is ClaimStatus.UNRESOLVED:
        reasons.append("unresolved_no_clear_answer")
    if result.appeal_deadline:
        reasons.append("denial_with_appeal_deadline")

    amounts = [result.total_paid_amount, *(line.paid_amount for line in result.lines)]
    if any(a is not None and a > _REVIEW_AMOUNT_THRESHOLD for a in amounts):
        reasons.append("amount_above_review_threshold")

    # Dedupe, preserve order, drop empties.
    result.review_reasons = list(dict.fromkeys(r for r in reasons if r))
    result.needs_human_review = result.needs_human_review or bool(result.review_reasons)


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

# Navigating phone menus (IVR)
The payer may answer with an automated system (IVR) rather than a person. If you \
hear a recorded menu or an automated voice listing options:
- Listen for the path to claim status or provider services and follow it.
- Respond out loud with the requested keyword (e.g. say "claims", "provider", \
"representative", or "agent"); if asked to choose a number, say that number clearly.
- Keep asking for "provider services" or a "live representative" until a person \
answers.
- Do NOT give your greeting or any claim details to the automated system. Only \
begin the call flow below once a live human representative is on the line.

# Call flow (once a live representative answers)
1. GREETING: Briefly introduce yourself (billing for {provider}) and say you're \
calling to check on claim status.
2. VERIFICATION: The rep will ask identifying questions (provider NPI, Tax ID, \
member ID, patient name, date of birth, date of service). Different payers ask for \
different items in ANY order — just answer whatever is asked, ONE item at a time. \
Do not dump every field at once.
3. CLAIM INQUIRY: First find out whether the claim is still PENDING (not yet \
processed) or has been ADJUSTED (processed). Reps usually do NOT volunteer the \
details, so ASK explicitly:
   - If PENDING: find out WHY it's pending and HOW LONG it's expected to take. Do \
not accept a vague "it's still processing" — push for a reason and a timeline.
   - If ADJUSTED: go through it SERVICE LINE by SERVICE LINE. For each line, ask \
whether it was PAID or DENIED.
       * Paid line: ask how much was paid on that line.
       * Denied line: ask WHY — the denial reason code (CARC/RARC, e.g. CO-45) and \
the plain-English reason. Reps rarely give the code unprompted; request it and \
confirm the exact code. (Denied lines are recorded for later follow-up.)
     Then ask for the CHECK or EFT number the payment was sent under, and the \
payment date. If the rep gives only one claim-level amount with no line breakdown, \
record it as a single line.
   - If the claim CANNOT BE FOUND after a couple of attempts: record it as not_found.
   - If you CANNOT GET A CLEAR ANSWER (rep hangs up, transfers endlessly, or won't \
say): record it as unresolved and move on.
   CONFIRM CRITICAL VALUES before recording: read the money amounts, the check/EFT \
number, any denial code, and the appeal deadline back to the rep and ask them to \
confirm ("so that's eleven hundred dollars on EFT 8-8-4-3-2, correct?"). These \
figures drive payment and appeal decisions, so a misheard digit is costly. If you \
still cannot confirm a value (the rep won't repeat it, or you only half-heard it), \
record your best guess but list that field name in `low_confidence_fields` so a \
human re-checks it.
   When you have the full picture for a claim, call `record_claim_status` with the \
line-by-line breakdown.
4. NEXT CLAIM: If more claims remain, say something like "I also need to check on \
another claim." Claims may be for the SAME patient (no need to re-verify the \
patient — just give the next claim number) or a DIFFERENT patient. If it's a \
different patient, expect the rep to re-verify that patient, and provide the new \
member ID, name, and date of birth when asked.
5. WRAP UP: Once all claims are recorded, ask for the rep's name and a call \
reference number, then call `record_call_info`. Thank them and say goodbye.

# Tools
- `record_claim_status`: call it the moment you have complete info for a claim. \
Use the exact claim_id from the list above.
- `record_call_info`: call it at the very end with the rep's name and reference \
number. If the rep can't provide a reference number, still call it (leave it blank).

# When you get stuck (NO live handoffs)
You cannot transfer this call to anyone on our side, schedule a callback, or hand \
the call off to a human live. If the rep transfers you to a different department, \
puts you on a very long hold, or demands information you don't have:
- Keep the call moving where you reasonably can, but NEVER promise a callback or \
agree to be handed to someone on our end.
- If it blocks you from resolving a claim, briefly NOTE what happened in \
`additional_info`, record the claim (as `unresolved` if you got no clear answer, or \
with whatever partial details you did get), set `needs_human_review` to true with a \
short reason, and move on. A human will follow up — don't keep the rep waiting.

# Edge cases
- If asked for something not in your data: say you don't have that handy.
- If put on a brief hold: acknowledge and wait. For an unreasonably long hold, see \
"When you get stuck" above.
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
                        "Record the full status of a single claim. Call once you "
                        "have the complete picture. For an adjusted claim, include "
                        "every service line in 'lines'."
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
                                "description": (
                                    "Claim-level outcome: 'pending' (not yet "
                                    "processed), 'adjusted' (processed; fill 'lines'), "
                                    "'not_found' (payer has no record), or "
                                    "'unresolved' (no clear answer / rep hung up)."
                                ),
                            },
                            "pending_reason": {
                                "type": "string",
                                "description": "If pending: why it is pending.",
                            },
                            "pending_timeline": {
                                "type": "string",
                                "description": "If pending: how long it is expected to take.",
                            },
                            "lines": {
                                "type": "array",
                                "description": (
                                    "If adjusted: one entry per service line. Use a "
                                    "single line if the rep gives only a claim-level amount."
                                ),
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "procedure_code": {
                                            "type": "string",
                                            "description": "CPT/HCPCS code, e.g. 99214.",
                                        },
                                        "line_number": {
                                            "type": "string",
                                            "description": "Service line number, if stated.",
                                        },
                                        "status": {
                                            "type": "string",
                                            "enum": [s.value for s in LineStatus],
                                            "description": "'paid' or 'denied'.",
                                        },
                                        "paid_amount": {
                                            "type": "number",
                                            "description": "Amount paid on this line, if paid.",
                                        },
                                        "billed_amount": {
                                            "type": "number",
                                            "description": "Amount billed on this line, if stated.",
                                        },
                                        "denial_reason_code": {
                                            "type": "string",
                                            "description": "CARC/RARC code if denied, e.g. CO-45.",
                                        },
                                        "denial_reason_description": {
                                            "type": "string",
                                            "description": "Plain-English denial reason if denied.",
                                        },
                                    },
                                    "required": ["status"],
                                },
                            },
                            "total_paid_amount": {
                                "type": "number",
                                "description": "Total paid across the claim, if adjusted.",
                            },
                            "payment_date": {
                                "type": "string",
                                "description": "Payment/check date as stated by the rep.",
                            },
                            "check_or_eft_number": {
                                "type": "string",
                                "description": "Check number or EFT reference the money was sent under.",
                            },
                            "appeal_deadline": {
                                "type": "string",
                                "description": "Appeal deadline, if applicable.",
                            },
                            "status_details": {
                                "type": "string",
                                "description": "Any free-text clarification.",
                            },
                            "additional_info": {
                                "type": "string",
                                "description": "Anything else relevant the rep mentioned.",
                            },
                            "needs_human_review": {
                                "type": "boolean",
                                "description": (
                                    "Set true if a human should double-check this "
                                    "claim before acting on it: you were transferred "
                                    "around, put on a very long hold, couldn't get "
                                    "the info, or you are not confident in a value "
                                    "you recorded."
                                ),
                            },
                            "review_reasons": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": (
                                    "Short reasons a human should review this claim, "
                                    "e.g. 'rep transferred us twice' or 'could not "
                                    "confirm the paid amount'."
                                ),
                            },
                            "low_confidence_fields": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": (
                                    "Names of fields you recorded but could NOT "
                                    "confirm with the rep, e.g. 'total_paid_amount' "
                                    "or 'check_or_eft_number'. Use this when the line "
                                    "was noisy or the rep wouldn't repeat a value."
                                ),
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
        _derive_review(result)
        session.claims_completed.append(result)
        session.current_claim_index += 1

        review_note = (
            " Flagged for human review." if result.needs_human_review else ""
        )
        remaining = session.remaining_claims()
        if remaining > 0:
            session.phase = ConversationPhase.NEXT_CLAIM
            return ToolResult(
                content=(
                    f"Recorded claim {result.claim_id} as '{result.status.value}'.{review_note} "
                    f"{remaining} claim(s) still to check — proceed to the next one."
                )
            )

        session.phase = ConversationPhase.WRAP_UP
        return ToolResult(
            content=(
                f"Recorded claim {result.claim_id} as '{result.status.value}'.{review_note} "
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
