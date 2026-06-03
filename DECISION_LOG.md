# Decision Log

## Scoping assumptions

- **One payer, up to 3 claims per call** (per spec); same or different patients — a different patient triggers re-verification.
- **Input is JSON or 837**; we extract only the fields we need, not the full EDI spec.
- **Output is structured data using 835 field names** (CLP/SVC/CAS/TRN/DTM/AMT), not a wire-format 835 file.
- **Adjudication is line-level**: a claim is `pending` or `adjusted`; an adjusted claim splits into service lines that are each `paid` or `denied` (CARC/RARC) — so partial payments are representable.
- **Every claim gets an outcome.** Unfinished claims (hang-up / no clear answer) record as `unresolved`; `not_found` means the payer has no record.
- **No live handoffs.** The agent can't transfer, promise a callback, or escalate in real time. Transfers / long holds / demands for data we lack are noted and flagged for async human review.
- **Uncertain or high-stakes claims are flagged, not blocked** (`needs_human_review` + `review_reasons` + `low_confidence_fields`). It's a triage queue, not a correctness oracle. Critical values are also read back to the rep in-call.
- **Demo-grade infra**: provider name hardcoded, JSON files instead of a DB, no auth/multi-user, web voice demo (not real outbound calls), not HIPAA-compliant.

## Key decisions (what we chose, what we didn't, why)

1. **Text-first engine + Vapi Web SDK for voice** (over direct Twilio/WebSocket). Testable without voice infra, Vapi abstracts audio, browser demo is immediately usable, and the objective layer is reused across both modes.
2. **Let Vapi own the LLM loop in voice mode** (over proxying all text through us). Lower latency, simpler server; we keep control via tool handlers + tool-call validation. Tradeoff: our *response*-level guardrails don't run on the voice path, so the system prompt is the live safety layer there.
3. **Function calling for structured extraction** (over post-call transcript parsing). Real-time, typed, and the agent can follow up if it missed a field.
4. **Objective-based architecture with a registry** (over hardcoding claim logic). New call types are new files; engine/webhooks/UI unchanged. DI (`factory.py`) keeps the engine testable with a fake LLM.
5. **Confidence as a binary gate, not an LLM-emitted score.** Model self-reported confidence is uncalibrated, so we expose an act/don't-act-yet gate plus concrete reasons a reviewer can action. Plus lexical anti-hallucination grounding: recorded amounts/codes must trace back to what the rep actually said, else they're flagged. GPT-4o-mini is the default behind an `LLMClient` protocol (fast/cheap for this task; swappable).

## Known risks / flags

- **Voice-mode guardrail gap.** `guardrails.py` response checks + evals exercise the text path only. Tool-call validation and grounding run on both, but voice grounding depends on Vapi sending the transcript — if absent it no-ops (fails open).
- **Grounding is lexical.** Catches invented values well, but over-flags spoken-word numbers ("eleven hundred") and won't catch a spoken-but-wrong value. Semantic/LLM-judge pass is the upgrade.
- **Bot disclosure.** The agent deflects "are you an AI?" without claiming to be human and never proactively discloses. State laws (e.g. CA B.O.T. Act) + payer policy need review before real outbound use.
- **Not HIPAA-compliant / raw PII in stored transcripts.** Needs BAAs, encryption at rest/in transit, access controls, retention policy. Money fields should move `float` → `Decimal`/integer cents.

## Next steps (≈ another week)

- Semantic/LLM-judge post-call verification pass (transcript vs extracted JSON) to upgrade lexical grounding.
- Calibrated confidence scoring to risk-rank the human-review queue.
- Full 837 parser with loop/structure validation; payer-specific IVR adapters incl. DTMF for phone mode.
- Call queue + batch processing + retry logic; PostgreSQL for results/history; dashboard with recordings/transcripts/QA flags.
- Real outbound calls; model-comparison evals; HIPAA compliance review.

## How we test the stack

Three layers, in increasing order of setup cost — so the core logic is provable with zero keys:

1. **Automated tests (no keys, ~30s)** — `pytest` runs the engine against a **fake LLM** plus unit tests: extraction, guardrails, hallucination grounding, claim amendment, 837 parsing / 835 mapping, scoring, and the Vapi webhook tool path — all offline. Proves the logic deterministically.
2. **Evals (OpenAI key, scored)** — `python main.py eval` runs **9 scripted scenarios** (`happy_path`, `denied_claim`, `multi_claim`, `not_found`, `edge_cases`, `safety`, `ivr_navigation`, `multi_patient`, `partial_payment`) through the text engine. Each is scored on **extraction (50%) + conversation (30%) + safety (20%)**: field-by-field comparison with fuzzy amounts and token-overlap for free text, boolean flow checks, and severity-weighted safety violations. *Known limitation:* open-loop scripting can desync if the agent asks something unscripted — the production upgrade is an LLM-simulated rep.
3. **Manual text + voice mode (live)** — `python main.py text` to play the rep yourself, and the Vapi web demo for the live voice path (the part evals don't cover). Validates real STT/TTS, tool firing, and read-back behavior end-to-end.
