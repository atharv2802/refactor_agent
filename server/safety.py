"""PII safety: log redaction and a lightweight audit trail.

We never log raw conversation content. ``redact`` masks the common PII shapes
(SSN, member/claim IDs, NPI, DOB, phone, dollar amounts) before anything reaches
a log. ``AuditLog`` records structured, non-PII events for traceability.

This MVP is NOT HIPAA-compliant — see DECISION_LOG.md. Production needs BAAs,
encryption at rest/in transit, access controls, and retention policies.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("claim_agent.audit")

# Order matters: more specific patterns first.
_REDACTIONS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[SSN]"),
    (re.compile(r"\b\d{2}/\d{2}/\d{4}\b"), "[DOB/DATE]"),
    (re.compile(r"\b\d{10}\b"), "[NPI/ID]"),
    (re.compile(r"\b[A-Z]{2,4}\d{6,12}\b"), "[MEMBER_ID]"),
    (re.compile(r"\b\+?\d[\d\-\(\) ]{8,}\d\b"), "[PHONE]"),
    (re.compile(r"\$\s?\d[\d,]*(?:\.\d{2})?"), "[AMOUNT]"),
]


def redact(text: str) -> str:
    """Mask common PII patterns. Safe to call on anything before logging."""
    if not text:
        return text
    masked = text
    for pattern, replacement in _REDACTIONS:
        masked = pattern.sub(replacement, masked)
    return masked


@dataclass
class AuditEvent:
    timestamp: str
    call_id: str
    action: str
    detail: dict[str, Any] = field(default_factory=dict)


class AuditLog:
    """In-memory + logger-backed audit trail for one process/call."""

    def __init__(self) -> None:
        self._events: list[AuditEvent] = []

    def record(self, call_id: str, action: str, **detail: Any) -> None:
        event = AuditEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            call_id=call_id,
            action=action,
            detail={k: redact(str(v)) for k, v in detail.items()},
        )
        self._events.append(event)
        logger.info("audit %s call=%s %s", action, call_id, event.detail)

    @property
    def events(self) -> list[AuditEvent]:
        return list(self._events)
