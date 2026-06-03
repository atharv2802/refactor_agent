"""Minimal EDI 837 parser.

This is intentionally NOT a full 837 implementation. It is a forward-only scan
that walks segments and pulls just the fields we need to make a status call. A
production parser would validate the full loop structure (2000A/B/C, 2300, 2400)
and handle every situational segment.

Segments we read:
  NM1*85   -> billing provider, NPI in element 9
  REF*EI   -> provider Tax ID
  NM1*IL   -> subscriber/patient name + member ID
  DMG      -> patient date of birth (DMG*D8*CCYYMMDD)
  CLM      -> claim ID (element 1) + billed amount (element 2)
  DTP*472  -> date of service
"""

from __future__ import annotations

from server.models import ClaimInfo

_DEFAULT_ELEMENT_SEP = "*"
_DEFAULT_SEGMENT_SEP = "~"


def _split_segments(raw: str) -> list[list[str]]:
    # EDI files may use ~ terminators or newlines; tolerate both.
    normalized = raw.replace("\r", "").replace("\n", _DEFAULT_SEGMENT_SEP)
    segments = []
    for seg in normalized.split(_DEFAULT_SEGMENT_SEP):
        seg = seg.strip()
        if seg:
            segments.append(seg.split(_DEFAULT_ELEMENT_SEP))
    return segments


def _fmt_date(yyyymmdd: str) -> str:
    """CCYYMMDD -> MM/DD/YYYY (best effort)."""
    digits = "".join(ch for ch in yyyymmdd if ch.isdigit())
    if len(digits) == 8:
        return f"{digits[4:6]}/{digits[6:8]}/{digits[0:4]}"
    return yyyymmdd


def parse_837(raw: str) -> list[ClaimInfo]:
    """Extract one ``ClaimInfo`` per CLM segment found in the 837 text."""
    segments = _split_segments(raw)

    provider_npi = ""
    provider_tax_id = ""
    member_id = ""
    first_name = ""
    last_name = ""
    dob = ""

    claims: list[ClaimInfo] = []
    pending_claim_id: str | None = None
    pending_billed: float | None = None

    def flush(dos: str = "") -> None:
        nonlocal pending_claim_id, pending_billed
        if pending_claim_id is None:
            return
        claims.append(
            ClaimInfo(
                claim_id=pending_claim_id,
                provider_npi=provider_npi,
                provider_tax_id=provider_tax_id,
                patient_member_id=member_id,
                patient_first_name=first_name,
                patient_last_name=last_name,
                patient_date_of_birth=dob,
                date_of_service=dos,
                billed_amount=pending_billed,
            )
        )
        pending_claim_id = None
        pending_billed = None

    for elements in segments:
        tag = elements[0]

        if tag == "NM1":
            qualifier = elements[1] if len(elements) > 1 else ""
            if qualifier == "85" and len(elements) > 9:
                provider_npi = elements[9]
            elif qualifier == "IL":
                last_name = elements[3] if len(elements) > 3 else ""
                first_name = elements[4] if len(elements) > 4 else ""
                if len(elements) > 9:
                    member_id = elements[9]

        elif tag == "REF" and len(elements) > 2 and elements[1] == "EI":
            provider_tax_id = elements[2]

        elif tag == "DMG" and len(elements) > 2:
            dob = _fmt_date(elements[2])

        elif tag == "CLM":
            # A new claim begins; flush any prior claim without an explicit DOS.
            flush()
            pending_claim_id = elements[1] if len(elements) > 1 else ""
            if len(elements) > 2:
                try:
                    pending_billed = float(elements[2])
                except ValueError:
                    pending_billed = None

        elif tag == "DTP" and len(elements) > 3 and elements[1] == "472":
            flush(dos=_fmt_date(elements[3]))

    flush()
    return claims
