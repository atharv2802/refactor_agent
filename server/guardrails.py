"""Runtime guardrails.

Two kinds of checks live here:

* Response-level (``check_response`` / ``sanitize``) — applied to text the agent
  is about to say. These only run in TEXT MODE; in voice mode Vapi owns the LLM
  loop and streams straight to TTS, so the SYSTEM PROMPT is the live defense
  there. Treat phrase scrubbing as a brittle backstop + audit signal, not the
  primary control.

* Tool-call validation (``validate_tool_call``) — applied before any tool
  mutates state. This DOES run in voice mode (tool calls come back to us via
  webhook), so it is the dependable server-side control for both modes.
"""

from __future__ import annotations

from dataclasses import dataclass

from server.models import CallSession, ClaimStatus, LineStatus

# Substring matches are brittle (paraphrase evades, "AI department" false-positives).
# Kept only as a last-resort backstop and audit signal.
_BLOCKED_PHRASES = (
    "i am an ai",
    "i'm an ai",
    "as an ai",
    "i am a bot",
    "i'm a bot",
    "artificial intelligence",
    "language model",
    "i'm automated",
    "i am automated",
)

_SAFE_FALLBACK = "I'm sorry, could you repeat that?"

# Absurd-amount threshold: above this we warn (likely a misheard figure).
_AMOUNT_WARN_THRESHOLD = 1_000_000.0


@dataclass
class ToolValidation:
    ok: bool
    error: str | None = None
    warnings: list[str] | None = None


class Guardrails:
    def __init__(self, max_response_chars: int = 500) -> None:
        self._max_chars = max_response_chars

    # ------------------------------------------------------------- responses
    def check_response(self, text: str) -> tuple[str, list[str]]:
        """Return (safe_text, violations). Replaces text on a hard violation."""
        violations: list[str] = []
        lowered = text.lower()
        for phrase in _BLOCKED_PHRASES:
            if phrase in lowered:
                violations.append(f"ai_disclosure:{phrase}")
        if violations:
            return _SAFE_FALLBACK, violations
        return text, violations

    def sanitize(self, text: str) -> tuple[str, list[str]]:
        """Normalise for speech. Length is a SOFT signal (warn, don't truncate)."""
        warnings: list[str] = []
        cleaned = text.replace("*", "").replace("#", "").replace("`", "")
        cleaned = " ".join(cleaned.split())  # collapse whitespace / line breaks
        if len(cleaned) > self._max_chars:
            warnings.append(
                f"response_length:{len(cleaned)}>{self._max_chars}"
            )
        return cleaned, warnings

    # ------------------------------------------------------------ tool calls
    def validate_tool_call(
        self, session: CallSession, name: str, arguments: dict
    ) -> ToolValidation:
        if name == "record_claim_status":
            return self._validate_record_claim(session, arguments)
        if name == "record_call_info":
            return ToolValidation(ok=True)
        return ToolValidation(ok=False, error=f"Unknown tool: {name}")

    def _validate_record_claim(
        self, session: CallSession, arguments: dict
    ) -> ToolValidation:
        warnings: list[str] = []
        claim_id = arguments.get("claim_id")
        valid_ids = {c.claim_id for c in session.call_request.claims}

        if not claim_id or claim_id not in valid_ids:
            return ToolValidation(
                ok=False,
                error=(
                    f"claim_id '{claim_id}' is not one of the claims on this call "
                    f"({sorted(valid_ids)}). Use an exact claim_id."
                ),
            )

        if session.is_recorded(claim_id):
            return ToolValidation(
                ok=False,
                error=f"Claim '{claim_id}' was already recorded; do not record it twice.",
            )

        status = arguments.get("status")
        valid_status = {s.value for s in ClaimStatus}
        if status not in valid_status:
            return ToolValidation(
                ok=False,
                error=f"status '{status}' is invalid. Use one of {sorted(valid_status)}.",
            )

        valid_line_status = {s.value for s in LineStatus}
        for idx, line in enumerate(arguments.get("lines") or []):
            line_status = line.get("status")
            if line_status not in valid_line_status:
                return ToolValidation(
                    ok=False,
                    error=(
                        f"line {idx} status '{line_status}' is invalid. "
                        f"Use one of {sorted(valid_line_status)}."
                    ),
                )
            err, warn = self._check_amount(line.get("paid_amount"), f"line {idx} paid_amount")
            if err:
                return ToolValidation(ok=False, error=err)
            warnings.extend(warn)

        err, warn = self._check_amount(arguments.get("total_paid_amount"), "total_paid_amount")
        if err:
            return ToolValidation(ok=False, error=err)
        warnings.extend(warn)

        return ToolValidation(ok=True, warnings=warnings or None)

    @staticmethod
    def _check_amount(amount, label: str) -> tuple[str | None, list[str]]:
        if amount is None:
            return None, []
        if amount < 0:
            return f"{label} cannot be negative.", []
        if amount > _AMOUNT_WARN_THRESHOLD:
            return None, [f"amount_suspicious:{label}:{amount}"]
        return None, []
