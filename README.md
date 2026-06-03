# Claim Status Voice Agent

An AI agent that calls insurance payers to check claim statuses on behalf of
medical providers. It greets the rep, answers verification questions, extracts
structured, line-level status data (pending, or adjusted with per-line paid/denied
breakdown, plus not-found / unresolved), and writes a
result that maps to EDI 835 remittance concepts.

Three interaction modes share **one objective** (prompt + tools + handlers):

1. **Text mode** — terminal; you type the rep's lines, the agent replies as text. Fastest for iteration.
2. **Web voice mode** — browser via the Vapi Web SDK. Real voice, no phone number. The demo.
3. **Phone mode** — outbound Vapi call (stretch; not built in this MVP).

---

## Architecture

```
Interaction adapters            Shared core                     Output
─────────────────────           ─────────────────────           ─────────────
text_mode.py  ─┐                conversation_engine.py  ─┐
               ├─ rep text ───▶ (text-mode orchestration)│
web + Vapi    ─┘                                         ├─▶ CallObjective ─▶ output_handler
vapi_webhook.py ── tool calls ──────────────────────────┘   (prompt/tools/    (JSON files;
                                                              handlers)         swappable sink)
```

- **What is shared:** the `CallObjective` (system prompt, tool schemas, tool
  handlers, completion logic). Adding a new call type = a new objective file.
- **What is NOT shared:** orchestration. Text mode runs `ConversationEngine`
  (tool loop + response guardrails + turn limits). In voice mode **Vapi owns the
  LLM loop** for latency, so our Python response guardrails do not run there —
  the **system prompt** is the live safety layer, and `Guardrails.validate_tool_call`
  on the webhook path is the dependable server-side control (it runs in both modes).

Key files:

| Path | Role |
|------|------|
| `server/config.py` | Settings from `.env` (single source of truth) |
| `server/models.py` | Pydantic domain models (837 in, 835-mapped out) |
| `server/llm_client.py` | `LLMClient` protocol + OpenAI impl (swappable) |
| `server/objectives/` | `CallObjective` base, registry, `claim_status` |
| `server/conversation_engine.py` | Text-mode tool-calling loop |
| `server/guardrails.py` | Response checks + tool-call validation |
| `server/safety.py` | PII redaction + audit trail |
| `server/output_handler.py` | `OutputSink` protocol + file sink |
| `server/edi/` | 837 field parser + 835 concept mapper |
| `server/vapi_webhook.py` | Assistant config + Vapi event handlers |
| `server/app.py` | FastAPI: serves the SPA + REST + webhooks |
| `frontend/` | Vite + React + TypeScript voice UI (builds to `web/dist`) |
| `evals/` | Scenario runner + 3-dimension scorer + 9 scenarios |

### Frontend

The UI is a Vite + React + TS app in `frontend/` (Tailwind for styling, a typed
`api.ts` client, and a `useVapi` hook wrapping the Vapi Web SDK). It runs two ways:

```bash
cd frontend && npm install

npm run dev      # http://localhost:5173, hot reload, proxies /api + /vapi to :8000
npm run build    # emits to ../web/dist; FastAPI serves it at http://localhost:8000
```

FastAPI serves the production build from `web/dist`. This mirrors production: a
built SPA served behind the API/CDN. (`GET /` returns a 503 with build
instructions if `web/dist` is missing.)

---

## Setup

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then add your OPENAI_API_KEY (and Vapi keys for voice)
```

## Usage

```bash
# Text mode (only needs OPENAI_API_KEY) — you play the payer rep
python main.py text --claims sample_claims.json

# Parse an 837 to structured claims
python main.py parse-837 sample_claim.837

# Evals (needs OPENAI_API_KEY) — runs scripted scenarios, scores, saves to evals/results/latest.json
python main.py eval --verbose
python main.py eval --scenario happy_path --verbose

# Voice mode (needs Vapi keys + a public URL)
ngrok http 8000                          # terminal 1; put the https URL in SERVER_URL
python main.py server                    # terminal 2
# open http://localhost:8000, paste/parse claims, click Start Call, talk as the rep
```

## Extending

- **New call type** (eligibility, denial follow-up): add `server/objectives/<name>.py`
  with a `CallObjective` subclass decorated `@register_objective`; import it in
  `objectives/__init__.py`. The engine, webhooks, and UI are unchanged.
- **New model provider:** implement `LLMClient` and inject it in `factory.build_engine`.
- **Persistent storage:** implement `OutputSink` (e.g. a DB sink) — no engine change.

## Reliability, safety & guardrails

The extracted status drives irreversible money decisions (post a payment, write
off a denial, file an appeal), so the central design problem is: *a misheard or
hallucinated value looks exactly as plausible as a correct one.* The guardrails
are layered around that.

**Prompt-level (the live defense, runs in both modes):** deflect "are you an
AI?" without claiming to be human, never invent claim data, never leak PII to the
wrong party, escalate fraud mentions. Critical money/code fields are **read back
to the rep for confirmation**, and the agent is told to **leave a value blank and
flag it rather than guess** a dollar amount or denial code.

**Anti-hallucination grounding** (`_flag_data_quality` in
`objectives/claim_status.py`, runs in **both** text and voice via the tool
handler): when a claim is recorded, every money amount, check/EFT number, and
denial code is checked against what the rep actually said (`session.rep_turns`).
A value with no anchor in the transcript is added to `low_confidence_fields` —
flagged for a human, never silently dropped. It also validates denial-code shape
(CARC/RARC) and flags lines paid more than billed.

**Human-review triage** (`needs_human_review` / `review_reasons` /
`low_confidence_fields` on every result): a binary *act / don't act yet* gate plus
concrete reasons. We deliberately use a gate, **not a numeric confidence score**
(model-emitted confidence is uncalibrated). The flag fires on uncertainty
(ungrounded/unconfirmed value) or high stakes (appeal deadline, implausibly large
amount, unresolved, an amendment). It surfaces in the results UI and JSON.

**Amendable records:** a second `record_claim_status` for the same claim is
treated as the rep *correcting* an earlier value — it upserts in place (no
duplicate) and flags the amended claim. **No live handoffs:** transfers / long
holds / missing info are noted in `additional_info`, recorded as `unresolved`,
flagged for async follow-up — never escalated live.

**Code-level + PII:** `guardrails.py` also hard-rejects unknown claim IDs, bad
enums, and negative amounts; `safety.py` redacts PII from logs and writes an
audit trail. Note: the text-only response scrubber in `guardrails.py` does **not**
run in voice mode (Vapi owns that loop).

### Key tradeoffs (see `DECISION_LOG.md` for the full list)

| Area | MVP choice | Deferred / production |
|------|-----------|------------------------|
| Confidence | Binary review gate + reasons | Calibrated score to risk-rank the queue |
| Grounding | Lexical (number/code match vs transcript) | Semantic / LLM-judge verification pass |
| Voice guardrails | Tool validation + grounding (best-effort on webhook transcript) | Full parity with text-mode response checks |
| Throughput | 1–3 claims per call, one call at a time, JSON files | Call queue + batch + DB for "many in one go" |
| Amendments | Last-write-wins upsert | Full amendment history / audit |
| Money type | `float` | `Decimal` / integer cents |
| Compliance | **Not HIPAA-compliant** | BAAs, encryption at rest/in transit, retention |

## Tests / validation

The engine is dependency-injected, so the suite runs against a fake `LLMClient`
with no API key or network:

```bash
pip install -r requirements-dev.txt
python -m pytest -q          # engine, guardrails, grounding, amend, EDI, scorer, webhook
```

See `instructions.md` for full setup and manual testing steps (text, eval, voice).
