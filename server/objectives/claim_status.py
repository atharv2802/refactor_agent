"""Claim Status Check objective.

The MVP's single objective: call a payer and extract structured status for 1-3
claims. The system prompt is the most important artifact in the whole system —
it is the live safety layer in voice mode (where our Python guardrails don't run)
and the driver of extraction quality everywhere.
"""

from __future__ import annotations

import re
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

# A number as it might appear in rep speech/text ("1,100", "1100.00", "220").
_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
# Well-formed CARC/RARC denial code, e.g. CO-45, PR-1, OA-23 (group prefix + digits).
_CARC_RE = re.compile(r"^(CO|PR|OA|PI|CR)-?\d{1,3}$", re.IGNORECASE)
# How close a recorded amount must be to a number the rep said to count as "heard".
_GROUNDING_TOLERANCE = 0.5


def _norm(value: Any) -> str:
    """Lowercase, strip everything but [a-z0-9] — for loose identifier matching."""
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def _numbers_in(text: str) -> list[float]:
    out: list[float] = []
    for match in _NUMBER_RE.findall(text):
        try:
            out.append(float(match.replace(",", "")))
        except ValueError:
            continue
    return out


def _amount_heard(amount: float, numbers: list[float]) -> bool:
    return any(abs(amount - n) <= _GROUNDING_TOLERANCE for n in numbers)


def _flag_data_quality(result: ClaimStatusResult, session: CallSession) -> None:
    """Catch likely hallucinations by grounding recorded values in the rep's words.

    The extracted status drives irreversible money decisions, and the agent
    can't tell a misheard/invented figure from a real one. So before a claim is
    acted on we check, deterministically (runs in BOTH text and voice modes via
    the tool handler):

    * Grounding — every recorded money amount, check/EFT number, and denial code
      should be traceable to something the rep actually said. A value with no
      anchor in the transcript is added to ``low_confidence_fields`` for a human
      to re-verify (we flag, never silently drop — the figure may be right).
    * Denial-code shape — a code that isn't a valid CARC/RARC pattern is noted.
    * Plausibility — a line paid more than it was billed is almost always a
      mishear, so it's flagged.

    Best-effort: if we have no rep turns to compare against (e.g. a voice webhook
    that didn't carry the transcript) we skip grounding rather than flag blindly.
    """
    rep_turns = session.rep_turns
    if not rep_turns:
        return

    joined = " ".join(rep_turns)
    numbers = _numbers_in(joined)
    norm_text = _norm(joined)
    ungrounded: list[str] = []

    if result.total_paid_amount is not None and not _amount_heard(
        result.total_paid_amount, numbers
    ):
        ungrounded.append("total_paid_amount")
    if result.check_or_eft_number and _norm(result.check_or_eft_number) not in norm_text:
        ungrounded.append("check_or_eft_number")

    for i, line in enumerate(result.lines):
        if line.paid_amount is not None and not _amount_heard(line.paid_amount, numbers):
            ungrounded.append(f"lines[{i}].paid_amount")
        code = line.denial_reason_code
        if code:
            if _norm(code) not in norm_text:
                ungrounded.append(f"lines[{i}].denial_reason_code")
            if not _CARC_RE.match(code.strip()):
                result.review_reasons.append(f"malformed_denial_code:{code}")
        if (
            line.paid_amount is not None
            and line.billed_amount is not None
            and line.paid_amount > line.billed_amount + _GROUNDING_TOLERANCE
        ):
            result.review_reasons.append(f"paid_exceeds_billed:line{i}")

    for name in ungrounded:
        if name not in result.low_confidence_fields:
            result.low_confidence_fields.append(name)
    if ungrounded:
        result.review_reasons.append("values_not_heard_in_call")


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
- Be patient and easy to work with, NOT pushy. Answer the question you were asked, \
then STOP and let the rep lead. Do not tack a "can you confirm?" or another request \
onto the end of every turn, and do not repeat a question you've already asked — ask \
once, then wait.
- The rep often needs to look things up. A brief acknowledgement ("sure", "no \
problem, take your time") is plenty while they search; don't keep prompting them.

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
member ID, patient name, date of birth, date of service). They ask in ANY order \
and only for what they need. Provide ONLY the single item they asked for, then wait \
for their next question. Do NOT volunteer other fields, do NOT recite several at \
once, and do NOT ask the rep to "confirm" identity details back to you — you are \
the party being verified, so just supply each item plainly when asked and let them \
drive.
3. CLAIM INQUIRY: Once verification is done, find out whether the claim is still \
PENDING (not yet processed) or has been ADJUSTED (processed). Ask ONE question at a \
time and give the rep room to answer — don't stack multiple asks into one turn. \
Reps usually don't volunteer details, so do ask for them, but conversationally:
   - If PENDING: ask why it's pending and roughly how long it's expected to take, \
rather than accepting a bare "it's still processing".
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
   CONFIRM CRITICAL VALUES before recording: once the rep has GIVEN you the money \
amounts, check/EFT number, denial code, and appeal deadline, read them back ONCE in \
a single natural line and ask them to confirm ("so that's eleven hundred dollars on \
EFT 8-8-4-3-2, correct?"). These figures drive payment and appeal decisions, so a \
misheard digit is costly. This read-back is only for figures the REP gave you — \
never for the identity details you provided. If you \
cannot confirm a money amount, a check/EFT number, or a denial code (the rep won't \
repeat it, or you only half-heard it), do NOT guess — leave that field blank and \
add its name to `low_confidence_fields` so a human re-checks it. NEVER invent a \
number or code to fill a gap: a blank flagged field is safe, but a guessed dollar \
amount or code looks correct and can trigger a wrong payment.
   When you have the full picture for a claim, call `record_claim_status` with the \
line-by-line breakdown. If the rep LATER CORRECTS a value you already recorded \
(e.g. a different amount or check number), call `record_claim_status` AGAIN with \
the same claim_id and the corrected values — it will amend the existing record.
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
                        "every service line in 'lines'. To correct a value after the "
                        "rep gives an updated figure, call this again with the same "
                        "claim_id — it amends the existing record."
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
        _flag_data_quality(result, session)
        _derive_review(result)

        # Amend-in-place: a second record for a claim_id we've already captured
        # is the rep correcting an earlier value (the founder wanted amendable
        # records, not record-once). Replace the prior result and always flag the
        # amended claim so a human sees the correction before acting on it.
        existing = next(
            (i for i, c in enumerate(session.claims_completed) if c.claim_id == result.claim_id),
            None,
        )
        if existing is not None:
            result.review_reasons = list(
                dict.fromkeys([*result.review_reasons, "amended_after_initial_record"])
            )
            result.needs_human_review = True
            session.claims_completed[existing] = result
            verb = "Updated"
        else:
            session.claims_completed.append(result)
            session.current_claim_index += 1
            verb = "Recorded"

        review_note = (
            " Flagged for human review." if result.needs_human_review else ""
        )
        remaining = session.remaining_claims()
        if remaining > 0:
            session.phase = ConversationPhase.NEXT_CLAIM
            return ToolResult(
                content=(
                    f"{verb} claim {result.claim_id} as '{result.status.value}'.{review_note} "
                    f"{remaining} claim(s) still to check — proceed to the next one."
                )
            )

        session.phase = ConversationPhase.WRAP_UP
        return ToolResult(
            content=(
                f"{verb} claim {result.claim_id} as '{result.status.value}'.{review_note} "
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
